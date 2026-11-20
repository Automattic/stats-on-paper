"""The TRMNL templates must render against the JSON `sop serve` actually sends.

Rendered with a real Liquid engine rather than pattern-matched, so a missing
root variable, a missing nested key, and an unknown filter all fail here
rather than on the device.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from liquid import DictLoader, Environment, StrictUndefined
from liquid.exceptions import LiquidError

from sop.models import snapshot_from_public_json
from sop.render.format import AGED_AFTER_SECONDS

TEMPLATES = Path(__file__).parents[1] / "trmnl"
LAYOUTS = ("full", "half_horizontal", "half_vertical", "quadrant")
SHARED = TEMPLATES / "shared.liquid"
# TRMNL defines shared markup as `{% template name %}…{% endtemplate %}` and
# invokes it with `{% render "name" %}`; `{% include %}` is not in its
# vocabulary. python-liquid has no `template` tag, so the partials are lifted
# out of the shared file and registered by name — the same name-to-body
# resolution the device performs.
_TEMPLATE_TAG = re.compile(
    r"{%-?\s*template\s+(\w+)\s*-?%}(.*?){%-?\s*endtemplate\s*-?%}", re.DOTALL
)

# TRMNL supplies these; a stub is enough to prove the template calls them
# correctly. This dict is the list `trmnl/README.md` must name, so the
# tutorial and the test cannot drift apart.
TRMNL_FILTERS = {
    "number_with_delimiter": lambda value, *_: f"{int(value):,}",
}


def _shared_partials() -> dict[str, str]:
    partials = dict(_TEMPLATE_TAG.findall(SHARED.read_text(encoding="utf-8")))
    assert partials, "shared.liquid defines no {% template %} block"
    return partials


def _environment() -> Environment:
    env = Environment(
        loader=DictLoader(_shared_partials()),
        # Strict on both axes: an unknown root or nested key raises, and so
        # does an unknown filter (`strict_filters` is the default).
        undefined=StrictUndefined,
    )
    env.filters.update(TRMNL_FILTERS)
    return env


def _layout_source(layout: str) -> str:
    """The markup as TRMNL assembles it: shared prepended to the view."""

    shared = _TEMPLATE_TAG.sub("", SHARED.read_text(encoding="utf-8"))
    view = (TEMPLATES / f"{layout}.liquid").read_text(encoding="utf-8")
    return f"{shared}\n{view}"


def _wire_payload(fixture_dir: Path) -> dict[str, Any]:
    payload = json.loads((fixture_dir / "sample-stats.json").read_text())
    snapshot = snapshot_from_public_json(payload)
    return snapshot.to_public_json(now=snapshot.fetched_at)


def test_every_layout_renders_against_the_wire_contract(fixture_dir: Path) -> None:
    """Both sides of `{% if commerce %}` run against the real payload.

    The directory listing is checked first so an empty directory cannot pass
    vacuously.
    """
    assert sorted(path.stem for path in TEMPLATES.glob("*.liquid")) == sorted(
        [*LAYOUTS, "shared"]
    )

    for layout in LAYOUTS:
        for has_commerce in (True, False):
            payload = _wire_payload(fixture_dir)
            if not has_commerce:
                payload["commerce"] = None

            output = (
                _environment().from_string(_layout_source(layout)).render(**payload)
            )

            # Rendered through TRMNL's own delimiter filter, as the device would.
            assert f"{payload['today']['views']:,}" in output, (layout, has_commerce)


def test_a_template_that_drifts_from_the_contract_fails(fixture_dir: Path) -> None:
    """The three ways a template goes stale must each raise, not render blank."""
    env = _environment()
    payload = _wire_payload(fixture_dir)

    for source in (
        "{{ nope }}",
        "{{ today.viewz }}",
        "{{ today.views | no_such_filter }}",
    ):
        with pytest.raises(LiquidError):
            env.from_string(source).render(**payload)


def test_a_real_count_is_never_a_zero_height_bar(fixture_dir: Path) -> None:
    """The chart obeys the same floor the PNG renderer does.

    Integer division would round a small day to `height: 0%`, making a day
    that happened indistinguishable from one that did not.
    """
    payload = _wire_payload(fixture_dir)
    payload["series"] = [
        {"date": "2026-07-26", "views": 1, "visitors": 1},
        {"date": "2026-07-27", "views": 1000, "visitors": 900},
    ]

    output = _environment().from_string(_layout_source("full")).render(**payload)
    heights = re.findall(r"height:\s*([\d.]+)%", output)

    assert len(heights) == 2
    assert all(float(height) > 0 for height in heights), heights


def test_every_layout_says_how_old_its_numbers_are(fixture_dir: Path) -> None:
    """TRMNL keeps showing the last screen it drew, so when pushes stop the
    numbers must still say when they were fetched. The delayed warning uses
    the PNG renderer's threshold, so both screens agree on what "late" is."""
    for layout in LAYOUTS:
        for age, delayed in (
            (0, False),
            (AGED_AFTER_SECONDS, False),
            (AGED_AFTER_SECONDS + 1, True),
        ):
            payload = _wire_payload(fixture_dir)
            payload["age_seconds"] = age

            output = (
                _environment().from_string(_layout_source(layout)).render(**payload)
            )

            assert "2026-07-27 12:34 UTC" in output, (layout, age)
            assert ("Refresh delayed" in output) is delayed, (layout, age)
            assert ("Updated" in output) is not delayed, (layout, age)


class _Attributes(HTMLParser):
    """Every class token and style attribute in some markup, however quoted."""

    def __init__(self) -> None:
        super().__init__()
        self.classes: list[str] = []
        self.styles: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        for name, value in attrs:
            if name == "class" and value:
                self.classes.extend(value.split())
            if name == "style" and value:
                self.styles.append(value)


def test_templates_follow_trmnl_recipe_lint() -> None:
    """Two rules from TRMNL's recipe linter (`trmnlp lint`) that these
    templates can break: TRMNL wraps each layout in its own `view--*` element,
    so the markup must not, and the markup may use at most six inline style
    declarations in all, counting every Liquid branch."""
    parser = _Attributes()
    for path in TEMPLATES.glob("*.liquid"):
        parser.feed(path.read_text(encoding="utf-8"))
    parser.close()

    wrappers = {
        name
        for name in parser.classes
        if name in {f"view--{layout}" for layout in LAYOUTS} or name == "view"
    }
    assert not wrappers, wrappers

    declarations = 0
    for style in parser.styles:
        css = re.sub(r"{{.*?}}", "value", style)
        css = re.sub(r"{%.*?%}", "", css)
        declarations += sum(1 for part in css.split(";") if ":" in part)
    assert parser.styles, "the chart's bar heights are inline"
    assert declarations <= 6, declarations
