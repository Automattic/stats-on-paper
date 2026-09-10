"""The TRMNL templates must render against the JSON `jsp serve` actually sends.

Rendered with a real Liquid engine rather than pattern-matched, so a missing
root variable, a missing nested key, and an unknown filter all fail here
rather than on the device.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from liquid import DictLoader, Environment, StrictUndefined
from liquid.exceptions import LiquidError

from jsp.models import snapshot_from_public_json

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


def test_every_layout_is_present() -> None:
    """Guard the loop below: an empty directory must not pass vacuously."""
    assert sorted(path.stem for path in TEMPLATES.glob("*.liquid")) == sorted(
        [*LAYOUTS, "shared"]
    )


@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("has_commerce", [True, False])
def test_layout_renders_against_the_wire_contract(
    layout: str, has_commerce: bool, fixture_dir: Path
) -> None:
    """Both sides of `{% if commerce %}` run against the real payload."""
    payload = _wire_payload(fixture_dir)
    if not has_commerce:
        payload["commerce"] = None

    output = _environment().from_string(_layout_source(layout)).render(**payload)

    assert f"view--{layout}" in output
    # Rendered through TRMNL's own delimiter filter, as the device would.
    assert f"{payload['today']['views']:,}" in output


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
