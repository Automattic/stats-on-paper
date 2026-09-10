from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import pytest
from record_render_hashes import frame_key, render_frames

from sop.models import Commerce, DayOrders, DayPoint
from sop.render import render
from sop.render.assets import logo_image
from sop.render.chart import (
    MIN_PAIR_COLUMN,
    _format_axis,
    bar_columns,
    bar_top,
    chart_frame,
    chart_range,
    chart_ticks,
    draw_bar,
    pair_widths,
    visible_days,
)
from sop.render.format import trend_period_label
from sop.render.layout import VIEWS, UnsupportedView, _fit_count, _rail_details
from sop.render.output import pixel_values
from sop.render.palette import PROFILES
from sop.render.text import text_width


def test_every_frame_matches_the_recorded_reference() -> None:
    """Pin the sample frame on every view and profile.

    This is the guard for refactors: a change that is meant to be invisible
    must leave every hash alone. Along the way it proves each frame's size,
    mode, and that no rendered colour lies outside the panel's palette.

    Re-record only for an intended rendering change, in its own commit:
        uv run python tests/record_render_hashes.py
    """
    path = Path(__file__).parent / "fixtures" / "render-hashes.json"
    table: dict[str, dict[str, object]] = json.loads(path.read_text(encoding="utf-8"))
    # A key removed from the table must fail, not silently reduce coverage.
    assert set(table) == {f"{view}/{name}" for view in VIEWS for name in PROFILES}

    for view, name, image in render_frames():
        assert frame_key(image) == table[f"{view}/{name}"], (view, name)
        palette = set(PROFILES[name].colors)
        assert set(pixel_values(image.convert("RGB"))) <= palette, (view, name)


def test_compact_four_color_uses_yellow_for_structure_not_red_alert(
    snapshot: object,
) -> None:
    fresh = render(
        snapshot,
        PROFILES["waveshare-2in13-four-color"],
        now=datetime(2026, 7, 27, 12, 35, 0, tzinfo=UTC),
    ).convert("RGB")
    fresh_counts = Counter(pixel_values(fresh))

    delayed = render(
        snapshot,
        PROFILES["waveshare-2in13-four-color"],
        now=datetime(2026, 7, 27, 16, 35, 0, tzinfo=UTC),
    ).convert("RGB")
    delayed_counts = Counter(pixel_values(delayed))

    assert fresh_counts[(220, 38, 38)] == 0
    yellow = [
        (x, y)
        for y in range(fresh.height)
        for x in range(fresh.width)
        if fresh.getpixel((x, y)) == (245, 196, 0)
    ]
    assert yellow
    # Yellow is structure only: the footer rule, and today's cap on the
    # sparkline's last column (plot x >= 133, rows 37..66).
    assert all(y >= 98 or (37 <= y <= 66 and x >= 133) for x, y in yellow)
    # Two hours on, the footer turns red and nothing else does.
    assert 0 < delayed_counts[(220, 38, 38)] < 500


def test_axis_ticks_and_labels_are_truthful() -> None:
    """Ticks are whole counts, never a fractional midpoint, and labels have units."""
    assert chart_ticks(0.0, 1.0) == (1.0, 0.0)
    assert chart_ticks(0.0, 5.0) == (5.0, 0.0)
    assert chart_ticks(0.0, 2_000.0) == (2_000.0, 1_000.0, 0.0)

    assert _format_axis(2_000_000_000) == "2b"
    assert _format_axis(1_500_000_000) == "1.5b"
    assert _format_axis(1_200) == "1.2k"
    assert _format_axis(2_000) == "2k"


def test_actual_provider_marks_are_bundled_and_distinct() -> None:
    jetpack = logo_image("wpcom", height=24, color=(0, 0, 0))
    parsely = logo_image("parsely", height=24, color=(0, 0, 0))

    assert jetpack is not None
    assert parsely is not None
    assert jetpack.mode == "RGBA"
    assert parsely.mode == "RGBA"
    assert jetpack.getbbox() is not None
    assert parsely.getbbox() is not None
    assert jetpack.tobytes() != parsely.tobytes()


def test_edge_case_snapshots_render_compact_and_large(snapshot: object) -> None:
    cases = [
        replace(snapshot, series=[]),
        replace(
            snapshot,
            series=[DayPoint(date=date(2026, 7, 27), views=0, visitors=0)],
            today=replace(snapshot.today, views=0, visitors=0),
        ),
        replace(snapshot, source="parsely"),
        replace(snapshot, source="custom-source"),
        replace(
            snapshot,
            site=replace(
                snapshot.site,
                url="https://www.a-very-long-publication-name.example.test/path",
            ),
        ),
    ]

    for case in cases:
        compact = render(case, PROFILES["waveshare-2in13-four-color"])
        large = render(case, PROFILES["impression-7in3"])

        assert compact.size == (250, 122)
        assert large.size == (800, 480)


def test_unknown_provider_does_not_inherit_jetpack_green(snapshot: object) -> None:
    unknown = replace(snapshot, source="custom-source")
    image = render(unknown, PROFILES["impression-7in3"]).convert("RGB")
    colors = Counter(pixel_values(image))

    assert colors[(48, 135, 74)] == 0
    assert colors[(35, 82, 170)] > 0


def test_chart_is_anchored_at_zero() -> None:
    """Counts are magnitudes, so a narrow band high above zero stays flat.

    A site at 800 to 1,100 views a day must not be rescaled into an apparent
    collapse and recovery; bars drawn against a floating baseline would
    encode that lie as height.
    """
    for values in ([1512, 1630, 1842], [0, 0, 0], [7], [3, 400_000], [800, 1100]):
        lower, _upper = chart_range(values)
        assert lower == 0.0, values

    upper = chart_range([800, 1100])[1]
    shortest = 100 - bar_top(800, upper, 0, 100)
    tallest = 100 - bar_top(1100, upper, 0, 100)
    assert tallest / shortest < 1.5


def test_bar_columns_stay_inside_bounds_and_never_overlap() -> None:
    """Columns abut inside the plot; a plot narrower than the series still
    yields one column per day rather than dropping days."""
    for left, right, count in (
        (100, 400, 1),
        (100, 400, 7),
        (100, 400, 90),
        (0, 20, 60),
    ):
        columns = bar_columns(left, right, count)

        assert len(columns) == count
        for column_left, column_right in columns:
            assert left <= column_left < column_right <= right
        if count <= right - left:
            for (_, first_right), (second_left, _) in pairwise(columns):
                assert second_left >= first_right


def _column_ink_tops(image: object, box: tuple[int, int, int, int]) -> list[int | None]:
    """Return, per column inside `box`, the topmost row holding non-background ink."""
    left, top, right, bottom = box
    pixels = image.convert("RGB").load()
    tops: list[int | None] = []
    for x in range(left, right + 1):
        found: int | None = None
        for y in range(top, bottom + 1):
            if pixels[x, y] != (255, 255, 255):
                found = y
                break
        tops.append(found)
    return tops


def test_todays_bar_never_reads_taller_than_its_value(snapshot: object) -> None:
    """Emphasis must not be added to the height that encodes the number.

    On a mono panel the accent ink equals the series ink, so a cap drawn above
    the bar is indistinguishable from bar height and inflates today's value.
    """
    # 700 against an 800 axis, so the bars sit mid-plot and are not clamped
    # flat against the ceiling by saturation.
    flat = replace(
        snapshot,
        series=[
            DayPoint(date=date(2026, 8, 1 + offset), views=700, visitors=400)
            for offset in range(28)
        ],
    )

    image = render(flat, PROFILES["waveshare-2in13"])
    # Row 66 is the zero rule, which every column carries; exclude it so only
    # bar ink is measured.
    tops = [
        top for top in _column_ink_tops(image, (133, 37, 243, 65)) if top is not None
    ]

    assert tops, "expected bar ink"
    assert min(tops) > 37, "bars should not be saturated against the plot ceiling"
    assert len(set(tops)) == 1, (
        f"identical days drew different bar heights: {set(tops)}"
    )


def test_a_single_count_is_visible_on_every_panel(snapshot: object) -> None:
    """One view, or one visitor, must draw ink that zero does not.

    On the 1872x1404 profile the zero rule is six pixels tall; it has to hang
    below the baseline, or a one-pixel bar is painted in the ink the rule
    already covers. Views are held equal in the visitors case so the striped
    bar is the only thing that can differ.
    """
    base = [
        DayPoint(date=date(2026, 8, 1), views=1100, visitors=900),
        DayPoint(date=date(2026, 8, 2), views=0, visitors=0),
    ]
    for profile in ("trmnl", "waveshare-10in3"):
        for views, visitors in ((1, 0), (1000, 1)):
            with_count = replace(
                snapshot,
                series=[
                    *base,
                    DayPoint(date=date(2026, 8, 3), views=views, visitors=visitors),
                ],
            )
            without = replace(
                snapshot,
                series=[
                    *base,
                    DayPoint(
                        date=date(2026, 8, 3),
                        views=views if visitors else 0,
                        visitors=0,
                    ),
                ],
            )

            assert (
                render(with_count, PROFILES[profile]).tobytes()
                != render(without, PROFILES[profile]).tobytes()
            ), (profile, views, visitors)


def test_pair_widths_never_spill_and_stay_legible() -> None:
    """A pair never exceeds its column, and from MIN_PAIR_COLUMN up both bars
    keep the three pixels that still read as a bar at a glance."""
    for span in range(1, 40):
        views, gap, visitors = pair_widths(span)

        assert views >= 1
        assert views + gap + visitors <= span, span
        if span >= MIN_PAIR_COLUMN:
            assert views >= 3 and visitors >= 3, (span, views, visitors)


def test_striped_bar_inks_its_top_row_and_alternates_from_the_bottom() -> None:
    """Stripes are what separate visitors from views when both are the same ink.

    The top row is always inked so the bar's height is exact to the pixel,
    whatever the stripe parity; below it every other row is inked, phased
    from the bottom edge so bars on one baseline share rows. The pattern
    survives a one-pixel-wide and a one-row-tall bar.
    """
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (10, 12), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw_bar(draw, (2, 3, 4, 10), fill=(0, 0, 0), style="striped")

    for x in (2, 3, 4):
        assert image.getpixel((x, 10)) == (0, 0, 0), "bottom row starts the phase"
        assert image.getpixel((x, 9)) == (255, 255, 255)
        assert image.getpixel((x, 8)) == (0, 0, 0)
        assert image.getpixel((x, 4)) == (0, 0, 0), "phase row"
        assert image.getpixel((x, 3)) == (0, 0, 0), "top row is inked off-phase"
    assert image.getpixel((5, 10)) == (255, 255, 255), "nothing outside the box"
    assert image.getpixel((3, 2)) == (255, 255, 255), "nothing above the top"

    narrow = Image.new("RGB", (4, 12), (255, 255, 255))
    draw_bar(ImageDraw.Draw(narrow), (1, 0, 1, 11), fill=(0, 0, 0), style="striped")
    assert narrow.getpixel((1, 11)) == (0, 0, 0)
    assert narrow.getpixel((1, 10)) == (255, 255, 255)
    assert narrow.getpixel((1, 0)) == (0, 0, 0)

    single = Image.new("RGB", (4, 4), (255, 255, 255))
    draw_bar(ImageDraw.Draw(single), (1, 2, 2, 2), fill=(0, 0, 0), style="striped")
    assert single.getpixel((1, 2)) == (0, 0, 0), "a one-row bar still draws"


def test_visitors_bars_are_distinguishable_from_views_on_mono(snapshot: object) -> None:
    """On a one-bit panel shape is the only cue, so it must survive rendering.

    Bars are found by scanning, not by assuming where the axis gutter ends.
    """
    flat = replace(
        snapshot,
        series=[
            DayPoint(date=date(2026, 8, 1 + offset), views=1000, visitors=1000)
            for offset in range(30)
        ],
    )
    image = render(flat, PROFILES["trmnl"]).convert("RGB")
    pixels = image.load()
    # Chart rows on the 800x480 layout; sample below the mid gridline.
    top, bottom = round(480 * 0.47), round(480 * 0.79)
    row = (top + bottom) // 2 + 10

    def column_kind(x: int) -> str:
        column = [pixels[x, y] for y in range(row - 4, row + 5)]
        if all(pixel == (0, 0, 0) for pixel in column):
            return "solid"
        if (0, 0, 0) in column and (255, 255, 255) in column:
            return "striped"
        return "blank"

    kinds = [column_kind(x) for x in range(image.width)]
    first_views = kinds.index("solid")
    after_views = next(
        x for x in range(first_views, image.width) if kinds[x] != "solid"
    )
    first_visitors = next(
        x for x in range(after_views, image.width) if kinds[x] != "blank"
    )

    assert kinds[first_visitors] == "striped", kinds[first_views : first_visitors + 3]


def test_chart_range_rejects_counts_it_cannot_plot() -> None:
    with pytest.raises(ValueError, match="too large"):
        chart_range([10**309])


def test_colour_panels_never_leak_fringe_ink(snapshot: object) -> None:
    """Anti-aliased grey sits nearer red than black on a sparse palette.

    Whatever mechanism keeps it off the panel, a fresh render must show red
    nowhere (red means a delayed refresh) and, on Spectra, yellow nowhere.
    """
    fresh = datetime(2026, 7, 27, 12, 35, 0, tzinfo=UTC)

    four = render(snapshot, PROFILES["waveshare-4in26-four-color"], now=fresh)
    counts = Counter(pixel_values(four.convert("RGB")))
    assert counts[(220, 38, 38)] == 0

    spectra = render(snapshot, PROFILES["impression-7in3"], now=fresh)
    counts = Counter(pixel_values(spectra.convert("RGB")))
    assert counts[(220, 38, 38)] == 0
    assert counts[(245, 196, 0)] == 0


def test_detail_rail_describes_only_the_days_drawn(snapshot: object) -> None:
    """A windowed chart must not be captioned with facts about hidden days."""
    series = [
        DayPoint(
            date=date(2025, 9, 1) + timedelta(days=offset),
            views=5000 if offset == 0 else 100,
            visitors=50,
        )
        for offset in range(365)
    ]
    drawn = visible_days(series, 1000, MIN_PAIR_COLUMN)
    assert len(drawn) < len(series)

    neutral = dict(
        _rail_details(replace(snapshot, series=series, source="custom"), drawn)
    )
    assert neutral["DAYS SHOWN"] == len(drawn)
    assert neutral["PERIOD HIGH"] == 100
    assert neutral["DAILY AVERAGE"] == 100

    jetpack = dict(
        _rail_details(replace(snapshot, series=series, commerce=None), drawn)
    )
    assert jetpack["PERIOD HIGH"] == 100


def test_bars_never_repaint_the_zero_rule(snapshot: object) -> None:
    """The rule owns its rows; a bar may touch it but never overwrite it.

    On the Inky 4" the rule is a single row, so any bar ending on that row
    turns the black baseline green or blue.
    """
    days = [date(2026, 8, 1 + offset) for offset in range(10)]
    all_zero = [DayPoint(date=day, views=0, visitors=0) for day in days]
    normal = [
        DayPoint(date=day, views=900 + 20 * i, visitors=500)
        for i, day in enumerate(days)
    ]
    # chart_bottom on the 600x400 layout is round(height * 0.79).
    rule_row = round(400 * 0.79)

    for series in (all_zero, normal):
        image = render(replace(snapshot, series=series), PROFILES["impression-4in0"])
        row = [image.convert("RGB").getpixel((x, rule_row)) for x in range(image.width)]

        assert (48, 135, 74) not in row, "views ink on the zero rule"
        assert (35, 82, 170) not in row, "visitors ink on the zero rule"


def test_striped_bars_encode_every_height_a_solid_bar_can(snapshot: object) -> None:
    """Both series share one scale, so they must resolve the same heights.

    The hero numbers come from `today`, not the series, so sweeping one bar's
    value changes nothing but that bar.
    """
    base = [
        DayPoint(date=date(2026, 8, 1), views=1100, visitors=900),
        DayPoint(date=date(2026, 8, 2), views=1000, visitors=500),
    ]
    for profile in ("trmnl", "waveshare-10in3"):
        solid = {
            render(
                replace(snapshot, series=[*base, DayPoint(date(2026, 8, 3), v, 0)]),
                PROFILES[profile],
            ).tobytes()
            for v in range(1, 40)
        }
        striped = {
            render(
                replace(snapshot, series=[*base, DayPoint(date(2026, 8, 3), 1000, v)]),
                PROFILES[profile],
            ).tobytes()
            for v in range(1, 40)
        }

        assert len(striped) == len(solid), (profile, len(striped), len(solid))


def test_metric_values_are_compacted_rather_than_overflowing() -> None:
    from PIL import Image, ImageDraw

    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    exact, _ = _fit_count(draw, 1842, start_size=68, min_size=42, max_width=226)
    assert exact == "1,842"

    for value in (12_345_678, 123_456_789, 1_234_567_890, 10**12):
        text, font = _fit_count(draw, value, start_size=68, min_size=42, max_width=226)
        assert text_width(draw, text, font) <= 226, (value, text)

    compact, _ = _fit_count(
        draw, 123_456_789, start_size=68, min_size=42, max_width=226
    )
    assert compact == "123m"


def test_caption_counts_the_days_drawn_not_the_calendar_span() -> None:
    points = [
        DayPoint(date=date(2026, 8, day), views=1, visitors=1) for day in (1, 4, 7, 10)
    ]

    assert trend_period_label(points, compact=False) == "LAST 4 DAYS"
    assert trend_period_label(points, compact=True) == "4 DAYS"


@pytest.mark.parametrize("view", sorted(VIEWS))
def test_a_windowed_render_matches_the_window_rendered_alone(
    view: str, snapshot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Caption, chart and rail must describe the drawn window and nothing else.

    Hooked at `chart_frame` because it is the one place every view's window
    is chosen, whichever chart draws it.
    """
    import sop.render.chart as chart_module

    drawn_lengths: list[int] = []
    real = chart_module.chart_frame

    def recording(*args: object, **kwargs: object) -> object:
        frame = real(*args, **kwargs)  # type: ignore[arg-type]
        drawn_lengths.append(frame.days)
        return frame

    monkeypatch.setattr(chart_module, "chart_frame", recording)
    days = [date(2025, 9, 1) + timedelta(days=offset) for offset in range(365)]
    series = [
        DayPoint(
            date=day,
            views=100 + (index * 37) % 900,
            visitors=50 + (index * 13) % 400,
        )
        for index, day in enumerate(days)
    ]
    orders = [
        DayOrders(date=day, orders=1 + (index * 7) % 40)
        for index, day in enumerate(days)
    ]
    full_snapshot = replace(
        snapshot,
        series=series,
        commerce=Commerce(orders=orders[-1].orders, series=orders),
    )
    windowed = False
    for profile in ("trmnl", "waveshare-10in3"):
        drawn_lengths.clear()
        full = render(full_snapshot, PROFILES[profile], view=view)
        window = drawn_lengths[0]
        windowed = windowed or window < len(series)

        alone = render(
            replace(
                full_snapshot,
                series=series[-window:],
                commerce=Commerce(orders=orders[-1].orders, series=orders[-window:]),
            ),
            PROFILES[profile],
            view=view,
        )

        assert full.tobytes() == alone.tobytes(), (view, profile)

    # The property is trivial if nothing was ever dropped; prove it was.
    assert windowed, view


def test_a_view_the_snapshot_cannot_fill_is_refused(snapshot: object) -> None:
    """Both refusals are the renderer's own; neither names a config variable."""
    with pytest.raises(UnsupportedView, match="Unknown view 'orders'"):
        render(snapshot, PROFILES["trmnl"], view="orders")

    storeless = replace(snapshot, commerce=None)
    with pytest.raises(UnsupportedView, match="no commerce data"):
        render(storeless, PROFILES["trmnl"], view="commerce")
    # The stats view does not need it.
    assert render(storeless, PROFILES["trmnl"]).size == (800, 480)


def test_paired_columns_never_fall_below_the_minimum(
    snapshot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gutter must be measured before the window is chosen, not guessed."""
    import sop.render.chart as chart_module

    spans: list[int] = []
    real = chart_module.bar_columns

    def recording(left: int, right: int, count: int) -> list[tuple[int, int]]:
        columns = real(left, right, count)
        spans.extend(right_edge - left_edge for left_edge, right_edge in columns)
        return columns

    monkeypatch.setattr(chart_module, "bar_columns", recording)
    for profile, days, magnitude in (
        ("waveshare-10in3", 365, 184_235),
        ("trmnl", 90, 184_235_000),
    ):
        spans.clear()
        series = [
            DayPoint(date(2025, 9, 1) + timedelta(days=i), magnitude, magnitude // 2)
            for i in range(days)
        ]
        render(replace(snapshot, series=series), PROFILES[profile])

        assert min(spans) >= MIN_PAIR_COLUMN, (profile, min(spans))


def test_a_windowed_chart_ignores_values_outside_its_window() -> None:
    """An old spike must not keep sizing the axis after it scrolls away.

    The gutter is re-measured for the window actually drawn, so a discarded
    outlier cannot steal horizontal space from the days on screen.
    """
    from PIL import Image, ImageDraw

    from sop.render.assets import load_font
    from sop.render.palette import layout_colors

    draw = ImageDraw.Draw(Image.new("RGB", (800, 480)))
    colors = layout_colors(PROFILES["trmnl"], "wpcom")
    font = load_font("regular", 12)
    quiet = [[1, 1] for _ in range(365)]
    with_spike = [[1_000_000, 1_000_000], *[[1, 1] for _ in range(364)]]

    frames = [
        chart_frame(
            draw,
            values,
            bounds=(32, 226, 768, 379),
            colors=colors,
            tick_font=font,
            line_width=3,
            min_column=MIN_PAIR_COLUMN,
        )
        for values in (quiet, with_spike)
    ]

    assert frames[0].plot_left == frames[1].plot_left
    assert frames[0].days == frames[1].days


def test_rail_numbers_never_collide_on_the_large_panel(snapshot: object) -> None:
    """Rail figures are fitted like every other number on the screen.

    At a fixed size a seven-digit count runs past its column and prints into
    the next one, so two numbers merge into an unreadable run of digits.
    """
    crowded = replace(
        snapshot,
        yesterday=replace(snapshot.yesterday, views=1_842_357),
        today=replace(snapshot.today, views=2_104_998, visitors=1_402_311),
    )
    image = render(crowded, PROFILES["waveshare-10in3"]).convert("RGB")
    scale = min(1872 / 800, 1404 / 480)
    margin = round(32 * scale)
    right = 1872 - margin
    column = (right - margin) / 4
    rail_top = round(1404 * 0.76) + round(30 * scale)

    # Each rail column must leave its last pixels blank, or it has run into
    # the column beside it.
    pixels = image.load()
    for index in range(4):
        edge = round(margin + (index + 1) * column) - 1
        gutter = [
            pixels[x, y]
            for x in range(edge - 3, edge + 1)
            for y in range(rail_top, rail_top + round(38 * scale))
        ]
        assert all(pixel == (255, 255, 255) for pixel in gutter), index
