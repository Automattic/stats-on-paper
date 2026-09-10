from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import pytest
from record_render_hashes import frame_key, render_frames

from jsp.models import Commerce, DayOrders, DayPoint
from jsp.render import render
from jsp.render.assets import logo_image
from jsp.render.chart import (
    MIN_PAIR_COLUMN,
    _format_axis,
    _orders_bar_width,
    bar_columns,
    bar_top,
    chart_frame,
    chart_range,
    chart_ticks,
    draw_bar,
    pair_widths,
    visible_days,
)
from jsp.render.format import trend_period_label
from jsp.render.layout import VIEWS, UnsupportedView, _fit_count, _rail_details
from jsp.render.output import pixel_values
from jsp.render.palette import PROFILES
from jsp.render.text import text_width


@pytest.mark.parametrize(
    ("profile_name", "mode", "size"),
    [
        ("waveshare-2in13", "1", (250, 122)),
        ("waveshare-2in13-four-color", "P", (250, 122)),
        ("impression-4in0", "P", (600, 400)),
        ("waveshare-4in26", "1", (800, 480)),
        ("waveshare-4in26-four-color", "P", (800, 480)),
        ("impression-7in3", "P", (800, 480)),
        ("waveshare-10in3", "P", (1872, 1404)),
        ("trmnl", "1", (800, 480)),
    ],
)
@pytest.mark.parametrize("view", sorted(VIEWS))
def test_render_smoke(
    profile_name: str,
    mode: str,
    size: tuple[int, int],
    view: str,
    snapshot: object,
) -> None:
    image = render(
        snapshot,
        PROFILES[profile_name],
        view=view,
        now=datetime(2026, 7, 27, 12, 35, 0, tzinfo=UTC),
    )

    assert image.size == size
    assert image.mode == mode
    assert set(pixel_values(image.convert("RGB"))) <= set(PROFILES[profile_name].colors)


def test_aged_render_differs_from_fresh(snapshot: object) -> None:
    fresh = render(
        snapshot,
        PROFILES["impression-7in3"],
        now=datetime(2026, 7, 27, 12, 35, 0, tzinfo=UTC),
    )
    aged = render(
        snapshot,
        PROFILES["impression-7in3"],
        now=datetime(2026, 7, 27, 16, 35, 0, tzinfo=UTC),
    )

    assert fresh.tobytes() != aged.tobytes()


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
    assert 0 < delayed_counts[(220, 38, 38)] < 500


def test_long_totals_still_render_at_both_layout_sizes(snapshot: object) -> None:
    today = replace(snapshot.today, views=12_345_678, visitors=9_876_543)
    crowded = replace(snapshot, today=today)

    compact = render(crowded, PROFILES["waveshare-2in13"])
    landscape = render(crowded, PROFILES["impression-7in3"])

    assert compact.size == (250, 122)
    assert landscape.size == (800, 480)


def test_count_axis_ticks_never_invent_fractional_counts() -> None:
    assert chart_ticks(0.0, 1.0) == (1.0, 0.0)
    assert chart_ticks(0.0, 5.0) == (5.0, 0.0)
    assert chart_ticks(0.0, 2_000.0) == (2_000.0, 1_000.0, 0.0)


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


def test_chart_range_anchors_at_zero_for_narrow_high_bands() -> None:
    """A narrow band high above zero must not be rescaled into a dramatic swing.

    George Howlett's site sits at 800-1,100 views a day. An auto-scaled lower
    bound turns that ordinary variation into an apparent collapse and back.
    """
    lower, upper = chart_range([800, 850, 900, 1100, 1050, 980])

    assert lower == 0.0
    assert upper >= 1100


def test_chart_range_anchors_at_zero_for_every_shape() -> None:
    for values in ([1512, 1630, 1842], [0, 0, 0], [7], [3, 400_000]):
        lower, _upper = chart_range(values)
        assert lower == 0.0, values


def test_bar_top_is_proportional_to_a_zero_anchored_value() -> None:
    assert bar_top(0, 1000.0, 0, 100) == 100
    assert bar_top(500, 1000.0, 0, 100) == 50
    assert bar_top(1000, 1000.0, 0, 100) == 0


def test_narrow_band_bars_stay_visually_flat() -> None:
    """The anti-dramatisation guarantee, stated as bar heights."""
    upper = chart_range([800, 1100])[1]
    shortest = 100 - bar_top(800, upper, 0, 100)
    tallest = 100 - bar_top(1100, upper, 0, 100)

    assert tallest / shortest < 1.5


def test_bar_columns_stay_inside_bounds_and_never_overlap() -> None:
    for count in (1, 2, 3, 7, 30, 90):
        columns = bar_columns(100, 400, count)

        assert len(columns) == count
        for left, right in columns:
            assert left >= 100
            assert right <= 400
            assert right > left
        for (_, first_right), (second_left, _) in pairwise(columns):
            assert second_left >= first_right


def test_bar_columns_survive_a_plot_narrower_than_the_series() -> None:
    columns = bar_columns(0, 20, 60)

    assert len(columns) == 60
    for left, right in columns:
        assert right > left
        assert left >= 0 and right <= 20


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


def test_a_real_count_is_never_rendered_as_nothing() -> None:
    """A positive count must draw ink; only zero may sit flat on the baseline."""
    assert bar_top(0, 1200.0, 37, 66) == 66
    for value in (1, 2, 5, 23):
        assert bar_top(value, 1200.0, 37, 66) < 66, value


def test_one_view_is_visually_distinct_from_none(snapshot: object) -> None:
    quiet = replace(
        snapshot,
        series=[
            DayPoint(date=date(2026, 8, 1), views=1100, visitors=900),
            DayPoint(date=date(2026, 8, 2), views=0, visitors=0),
            DayPoint(date=date(2026, 8, 3), views=1, visitors=1),
        ],
    )
    image = render(quiet, PROFILES["trmnl"])
    empty = replace(
        quiet,
        series=[
            quiet.series[0],
            quiet.series[1],
            DayPoint(date=date(2026, 8, 3), views=0, visitors=0),
        ],
    )

    assert image.tobytes() != render(empty, PROFILES["trmnl"]).tobytes()


def test_pair_widths_keep_both_bars_legible() -> None:
    """Three pixels is the narrowest bar that still reads as a bar at a glance."""
    for span in range(MIN_PAIR_COLUMN, 40):
        views, gap, visitors = pair_widths(span)

        assert visitors >= 3, (span, visitors)
        assert views >= 3, (span, views)
        assert views + gap + visitors <= span, span


def test_pair_widths_never_spill_into_the_next_day() -> None:
    for span in range(1, 40):
        views, gap, visitors = pair_widths(span)

        assert views >= 1
        assert views + gap + visitors <= span, span


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


def test_one_visitor_is_visually_distinct_from_none(snapshot: object) -> None:
    """A short striped bar must not vanish under the axis rule.

    Views are held equal so the visitors bar is the only thing that can differ.
    """
    base = [
        DayPoint(date=date(2026, 8, 1), views=1100, visitors=900),
        DayPoint(date=date(2026, 8, 2), views=1000, visitors=0),
    ]
    one = replace(
        snapshot,
        series=[*base, DayPoint(date=date(2026, 8, 3), views=1000, visitors=1)],
    )
    none = replace(
        snapshot,
        series=[*base, DayPoint(date=date(2026, 8, 3), views=1000, visitors=0)],
    )

    assert (
        render(one, PROFILES["trmnl"]).tobytes()
        != render(none, PROFILES["trmnl"]).tobytes()
    )


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


def test_a_year_long_series_renders_without_overdrawing_days(
    snapshot: object,
) -> None:
    """Days must never inherit a neighbour's bar, so a quiet day stays quiet."""
    series = [
        DayPoint(
            date=date(2025, 9, 1) + timedelta(days=offset),
            views=0 if offset % 2 else 1000,
            visitors=0 if offset % 2 else 600,
        )
        for offset in range(365)
    ]
    long_run = replace(snapshot, series=series)

    for profile in ("trmnl", "impression-4in0", "waveshare-2in13"):
        image = render(long_run, PROFILES[profile])
        assert image.size == PROFILES[profile].size


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


def test_one_view_is_visible_above_a_thick_axis_rule(snapshot: object) -> None:
    """On the 1872x1404 profile the zero rule is six pixels tall.

    It must hang below the baseline, not straddle it, or a one-pixel bar is
    painted in the same ink as the rule that already covers that row.
    """
    base = [
        DayPoint(date=date(2026, 8, 1), views=1100, visitors=900),
        DayPoint(date=date(2026, 8, 2), views=0, visitors=0),
    ]
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
                    date=date(2026, 8, 3), views=views if visitors else 0, visitors=0
                ),
            ],
        )

        assert (
            render(with_count, PROFILES["waveshare-10in3"]).tobytes()
            != render(without, PROFILES["waveshare-10in3"]).tobytes()
        ), (views, visitors)


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


def test_axis_labels_have_a_billions_unit() -> None:
    assert _format_axis(2_000_000_000) == "2b"
    assert _format_axis(1_500_000_000) == "1.5b"
    assert _format_axis(1_200) == "1.2k"
    assert _format_axis(2_000) == "2k"


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
    import jsp.render.chart as chart_module

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


def test_font_cache_holds_every_size_a_full_render_set_needs(snapshot: object) -> None:
    """`jsp serve` renders every panel from one process; nothing may evict."""
    from jsp.render.assets import load_font

    big = replace(
        snapshot,
        today=replace(snapshot.today, views=1_842_357_123, visitors=999_999_999),
    )
    for profile in PROFILES.values():
        render(big, profile)
    misses_before = load_font.cache_info().misses

    for profile in PROFILES.values():
        render(big, profile)

    assert load_font.cache_info().misses == misses_before


def test_paired_columns_never_fall_below_the_minimum(
    snapshot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gutter must be measured before the window is chosen, not guessed."""
    import jsp.render.chart as chart_module

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


def _render_reference() -> dict[str, dict[str, object]]:
    path = Path(__file__).parent / "fixtures" / "render-hashes.json"
    table: dict[str, dict[str, object]] = json.loads(path.read_text(encoding="utf-8"))
    return table


@pytest.mark.parametrize("key", sorted(_render_reference()))
def test_rendered_frame_matches_the_recorded_reference(key: str) -> None:
    """Pin the sample frame on every view and profile.

    This is the guard for refactors: a change that is meant to be invisible
    must leave every hash alone. It pins one frame each — the aged banner,
    the empty series, and the Parse.ly rail have their own tests.

    Re-record only for an intended rendering change, in its own commit:
        uv run python tests/record_render_hashes.py
    """
    expected = _render_reference()[key]
    view, _, profile = key.partition("/")
    image = next(
        image
        for frame_view, frame_profile, image in render_frames()
        if (frame_view, frame_profile) == (view, profile)
    )

    assert image.mode == expected["mode"]
    assert list(image.size) == expected["size"]
    assert frame_key(image)["sha256"] == expected["sha256"]


def test_the_reference_covers_every_view_and_profile() -> None:
    """A key removed from the table must fail, not silently reduce coverage."""
    expected = {f"{view}/{name}" for view in VIEWS for name in PROFILES}

    assert set(_render_reference()) == expected


def test_a_windowed_chart_ignores_values_outside_its_window() -> None:
    """An old spike must not keep sizing the axis after it scrolls away.

    The gutter is re-measured for the window actually drawn, so a discarded
    outlier cannot steal horizontal space from the days on screen.
    """
    from PIL import Image, ImageDraw

    from jsp.render.assets import load_font
    from jsp.render.palette import layout_colors

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


def test_commerce_bars_keep_a_separator_at_the_minimum_column() -> None:
    """Equal neighbouring days must not merge into one rectangle."""
    for span in range(2, 30):
        assert _orders_bar_width(span) < span, span
        assert _orders_bar_width(span) >= 1


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
