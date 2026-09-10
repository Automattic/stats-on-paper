"""Zero-anchored bar charts sized to the pixels a panel actually has."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor, log10
from typing import TypeVar

from PIL import ImageDraw, ImageFont

from sop.models import DayOrders, DayPoint
from sop.render.assets import load_font
from sop.render.palette import LayoutColors
from sop.render.text import draw_right_text, font_height, text_width

# A paired column needs 3px per bar, 1px between them, 1px between days.
MIN_PAIR_COLUMN = 8
# A single-series bar needs only itself and a separator.
MIN_SPARK_COLUMN = 2
# Beyond this a count is not a real audience measurement, and the float
# axis arithmetic below stops being exact.
MAX_PLOTTABLE_COUNT = 10**15

_Day = TypeVar("_Day")


@dataclass(frozen=True)
class ChartFrame:
    """The scale and geometry a chart draws into, shared by every view."""

    plot_left: int
    days: int
    upper: float
    columns: list[tuple[int, int]]


def _orders_bar_width(span: int) -> int:
    """Bar width inside a column, leaving a pixel between days where there is one.

    Without the separator, two equal neighbouring days merge into a single
    rectangle and the chart reads as one long bar. A one-pixel column has
    nothing to spare; `visible_days` keeps columns at `MIN_SPARK_COLUMN` or
    wider, so that case does not arise in a real chart.
    """

    return max(1, span - 1)


def chart_frame(
    draw: ImageDraw.ImageDraw,
    day_values: list[list[int]],
    *,
    bounds: tuple[int, int, int, int],
    colors: LayoutColors,
    tick_font: ImageFont.FreeTypeFont,
    line_width: int,
    min_column: int,
) -> ChartFrame:
    """Draw the axis, gridlines and zero rule, and return the bar geometry.

    `day_values` holds one list of same-day values per day, so a chart with
    one series and a chart with two share the scale, the window, and the
    columns. An empty input draws the no-data text and returns no columns.
    """

    left, top, right, bottom = bounds
    if not day_values:
        draw.text((left, top), "No trend data", fill=colors.muted, font=tick_font)
        return ChartFrame(plot_left=left, days=0, upper=0.0, columns=[])

    # Choosing the window and measuring the axis are circular: a wider label
    # narrows the plot, which can shrink the window, which can change the
    # label. Re-measure for each candidate window rather than keeping the
    # widest gutter seen, or an outlier the window has already discarded goes
    # on stealing space from the days actually on screen.
    gutter = 0
    drawn = day_values
    for _ in range(3):
        ceiling = chart_range([value for day in drawn for value in day])[1]
        labels = [_format_axis(value) for value in chart_ticks(0.0, ceiling)]
        gutter = max(text_width(draw, label, tick_font) for label in labels)
        candidate = visible_days(day_values, right - (left + gutter + 10), min_column)
        if candidate == drawn:
            break
        drawn = candidate
    plot_left = left + gutter + 10

    lower, upper = chart_range([value for day in drawn for value in day])
    tick_values = chart_ticks(lower, upper)
    tick_labels = [_format_axis(value) for value in tick_values]

    for index, (_value, label) in enumerate(zip(tick_values, tick_labels, strict=True)):
        y = round(top + index * (bottom - top) / max(1, len(tick_values) - 1))
        draw_right_text(
            draw,
            plot_left - 8,
            y - font_height(tick_font) // 2,
            label,
            font=tick_font,
            fill=colors.muted,
        )
        _dotted_rule(draw, plot_left, right, y, colors.divider)

    # The zero rule owns the baseline row and everything below it; bars stop
    # one row above. On the largest panel the rule is six pixels tall, and a
    # bar that shared its first row would either be hidden under it or, on a
    # colour panel, repaint the baseline in the bar's own ink.
    rule_height = max(1, line_width - 1)
    draw.rectangle(
        (plot_left, bottom, right, bottom + rule_height - 1), fill=colors.ink
    )
    return ChartFrame(
        plot_left=plot_left,
        days=len(drawn),
        upper=upper,
        columns=bar_columns(plot_left, right, len(drawn)),
    )


def grouped_bar_chart(
    draw: ImageDraw.ImageDraw,
    points: list[DayPoint],
    *,
    bounds: tuple[int, int, int, int],
    colors: LayoutColors,
    tick_font: ImageFont.FreeTypeFont,
    line_width: int,
) -> tuple[int, list[DayPoint]]:
    """Draw paired views and visitors bars on one zero-anchored scale.

    Returns the plot's left edge and the days actually drawn, so the caller can
    caption the window it is looking at rather than the window it asked for.
    """

    _left, top, _right, bottom = bounds
    frame = chart_frame(
        draw,
        [[point.views, point.visitors] for point in points],
        bounds=bounds,
        colors=colors,
        tick_font=tick_font,
        line_width=line_width,
        min_column=MIN_PAIR_COLUMN,
    )
    if not frame.columns:
        return (frame.plot_left, [])
    drawn = points[-frame.days :]
    for column, point in zip(frame.columns, drawn, strict=True):
        _draw_bar_pair(
            draw,
            column,
            top=top,
            bottom=bottom,
            point=point,
            upper=frame.upper,
            colors=colors,
        )
    return (frame.plot_left, drawn)


def orders_bar_chart(
    draw: ImageDraw.ImageDraw,
    rows: list[DayOrders],
    *,
    bounds: tuple[int, int, int, int],
    colors: LayoutColors,
    tick_font: ImageFont.FreeTypeFont,
    line_width: int,
) -> tuple[int, list[DayOrders]]:
    """Draw daily orders as one solid series on the same frame as the pair."""

    _left, top, _right, bottom = bounds
    frame = chart_frame(
        draw,
        [[row.orders] for row in rows],
        bounds=bounds,
        colors=colors,
        tick_font=tick_font,
        line_width=line_width,
        min_column=MIN_SPARK_COLUMN,
    )
    if not frame.columns:
        return (frame.plot_left, [])
    drawn = rows[-frame.days :]
    for (column_left, column_right), row in zip(frame.columns, drawn, strict=True):
        width = max(
            1,
            column_right - column_left - (1 if column_right - column_left >= 4 else 0),
        )
        draw_bar(
            draw,
            (
                column_left,
                bar_top(row.orders, frame.upper, top, bottom),
                column_left + width - 1,
                bottom - 1,
            ),
            fill=colors.views,
            style="solid",
        )
    return (frame.plot_left, drawn)


def _draw_bar_pair(
    draw: ImageDraw.ImageDraw,
    column: tuple[int, int],
    *,
    top: int,
    bottom: int,
    point: DayPoint,
    upper: float,
    colors: LayoutColors,
) -> None:
    """Draw one day as a solid views bar beside a striped visitors bar.

    Bars end on the row above `bottom`; the zero rule owns `bottom` itself. A
    zero count therefore yields an empty box and draws nothing at all.
    """

    column_left, column_right = column
    views_width, inner_gap, visitors_width = pair_widths(column_right - column_left)
    bar_bottom = bottom - 1

    draw_bar(
        draw,
        (
            column_left,
            bar_top(point.views, upper, top, bottom),
            column_left + views_width - 1,
            bar_bottom,
        ),
        fill=colors.views,
        style="solid",
    )
    if visitors_width <= 0:
        return
    visitors_left = column_left + views_width + inner_gap
    draw_bar(
        draw,
        (
            visitors_left,
            bar_top(point.visitors, upper, top, bottom),
            visitors_left + visitors_width - 1,
            bar_bottom,
        ),
        fill=colors.visitors,
        style="striped",
    )


def draw_chart_legend(
    draw: ImageDraw.ImageDraw,
    right: int,
    y: int,
    *,
    colors: LayoutColors,
    font: ImageFont.FreeTypeFont,
    scale: float,
) -> int:
    """Name the two bar styles beside the chart, and return its left edge.

    A reader should never have to infer which bar is which from position alone.
    """

    height = font_height(font)
    swatch = max(6, round(height * 0.8))
    pad = max(3, round(4 * scale))
    spacing = pad * 3
    entries = (
        ("VIEWS", colors.views, "solid"),
        ("VISITORS", colors.visitors, "striped"),
    )
    widths = [swatch + pad + text_width(draw, label, font) for label, _, _ in entries]
    x = right - (sum(widths) + spacing * (len(entries) - 1))
    legend_left = x
    swatch_top = y + max(0, (height - swatch) // 2)
    for (label, color, style), width in zip(entries, widths, strict=True):
        draw_bar(
            draw,
            (x, swatch_top, x + swatch, swatch_top + swatch),
            fill=color,
            style=style,
        )
        draw.text((x + swatch + pad, y), label, fill=colors.muted, font=font)
        x += width + spacing
    return legend_left


def bar_sparkline(
    draw: ImageDraw.ImageDraw,
    values: list[int],
    *,
    bounds: tuple[int, int, int, int],
    color: tuple[int, int, int],
    current_color: tuple[int, int, int],
    empty_color: tuple[int, int, int],
) -> int:
    """Draw one daily series as zero-anchored bars, latest day emphasised.

    Discrete bars survive a one-bit panel better than a polyline: no
    anti-aliasing to lose, no stair-stepped diagonals, and each day stays a
    countable object rather than a bend in a curve.
    """

    left, top, right, bottom = bounds
    if not values:
        draw.text(
            (left, top),
            "NO DATA",
            fill=empty_color,
            font=load_font("bold", max(9, round((bottom - top) * 0.32))),
        )
        return 0

    values = visible_days(values, right - left, MIN_SPARK_COLUMN)
    _lower, upper = chart_range(values)
    columns = bar_columns(left, right, len(values))
    last = len(values) - 1
    draw.line((left, bottom, right, bottom), fill=color, width=1)
    for index, ((bar_left, bar_right), value) in enumerate(
        zip(columns, values, strict=True)
    ):
        gap = 1 if bar_right - bar_left >= 3 else 0
        bar_right = max(bar_left, bar_right - gap - 1)
        top_y = bar_top(value, upper, top, bottom)
        if top_y >= bottom:
            continue
        draw.rectangle((bar_left, top_y, bar_right, bottom - 1), fill=color)
        if index == last:
            # Emphasise today inside the bar it belongs to. Drawn above it, an
            # accent that matches the series ink on mono would read as extra
            # height, and today would silently outgrow its own value.
            draw.rectangle(
                (bar_left, top_y, bar_right, min(bottom - 1, top_y + 1)),
                fill=current_color,
            )
    return len(values)


def draw_bar(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill: tuple[int, int, int],
    style: str,
) -> None:
    """Draw one bar, solid or striped.

    Stripes are what separate visitors from views on a one-bit panel, where
    both series resolve to the same ink: every other row is inked, so the bar
    reads as a mid grey beside a solid one. The top row is always inked so the
    bar's height is exact to the pixel, just like a solid bar; the stripes
    below it are phase-locked to the bottom edge so neighbouring bars on one
    baseline share rows. The pattern survives a single pixel of width.
    """

    left, top, right, bottom = box
    if bottom < top or right < left:
        return
    if style == "solid":
        draw.rectangle((left, top, right, bottom), fill=fill)
        return
    draw.line((left, top, right, top), fill=fill, width=1)
    for y in range(bottom, top, -2):
        draw.line((left, y, right, y), fill=fill, width=1)


def bar_columns(left: int, right: int, count: int) -> list[tuple[int, int]]:
    """Return left-to-right x-spans for `count` bar columns inside the plot.

    Columns abut rather than overlap whenever the plot is at least as wide as
    the series. A denser series still yields one column per point, one pixel
    wide, so no day is silently dropped from the chart.
    """

    if count <= 0:
        return []
    span = max(1, right - left)
    columns: list[tuple[int, int]] = []
    for index in range(count):
        start = min(left + round(index * span / count), right - 1)
        end = min(max(left + round((index + 1) * span / count), start + 1), right)
        columns.append((start, end))
    return columns


def visible_days(points: list[_Day], plot_width: int, min_column: int) -> list[_Day]:
    """Return the most recent days that fit at `min_column` pixels each.

    Drawing more days than there are pixel columns makes neighbours overwrite
    one another, and a quiet day inherits a busy day's bar. Showing a shorter,
    contiguous, correctly labelled window is the honest degradation: callers
    take the period label from what this returns, so the caption always names
    what is actually on screen.
    """

    if not points:
        return points
    capacity = max(1, plot_width // max(1, min_column))
    return points[-capacity:] if len(points) > capacity else points


def pair_widths(span: int) -> tuple[int, int, int]:
    """Split a column into (views width, inner gap, visitors width).

    The pair never exceeds its column, so one day can never draw over the next.
    """

    span = max(1, span)
    column_gap = 1 if span >= 4 else 0
    inner_gap = 1 if span >= MIN_PAIR_COLUMN else 0
    usable = max(1, span - column_gap - inner_gap)
    views = max(1, (usable + 1) // 2)
    visitors = max(1, usable - views)
    if views + inner_gap + visitors > span:
        visitors = span - views - inner_gap
    return (views, inner_gap, max(0, visitors))


def bar_top(value: int, upper: float, top: int, bottom: int) -> int:
    """Return the y of a bar's top edge, measured up from the zero baseline."""

    ceiling = max(1.0, upper)
    ratio = min(1.0, max(0.0, value / ceiling))
    y = round(bottom - ratio * (bottom - top))
    if value > 0:
        # A day that happened is never indistinguishable from a day that did
        # not. Sub-pixel heights round up to one pixel rather than vanishing.
        y = max(top, min(y, bottom - 1))
    return y


def chart_range(values: list[int]) -> tuple[float, float]:
    """Return a zero-anchored range framing the largest value.

    Counts are magnitudes, so the axis starts at zero. A floating lower bound
    rescales an ordinary band — 800 to 1,100 views a day — into what reads as a
    collapse and a recovery, and bars drawn against it would encode that lie as
    height. Two nice intervals keep the tallest bar near the top of the plot.
    """

    maximum = max(values)
    if maximum > MAX_PLOTTABLE_COUNT:
        raise ValueError(
            f"Count {maximum} is too large to plot truthfully; "
            f"the renderer supports up to {MAX_PLOTTABLE_COUNT}."
        )
    if maximum <= 0:
        return (0.0, 1.0)
    step = _nice_step(maximum / 2)
    return (0.0, float(step * ceil(maximum / step)))


def _nice_step(value: float) -> float:
    """Round up to a readable axis step, never below one whole count."""

    if value <= 1:
        return 1.0
    magnitude = 10.0 ** floor(log10(value))
    fraction = value / magnitude
    for candidate in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if fraction <= candidate:
            return max(1.0, candidate * magnitude)
    return max(1.0, 10 * magnitude)


def chart_ticks(lower: float, upper: float) -> tuple[float, ...]:
    """Return truthful integer-count ticks without fractional midpoints."""

    midpoint = (upper + lower) / 2
    if upper - lower < 2 or not midpoint.is_integer():
        return (upper, lower)
    return (upper, midpoint, lower)


def _format_axis(value: float) -> str:
    for divisor, suffix in ((1e9, "b"), (1e6, "m"), (1e3, "k")):
        if value >= divisor:
            scaled = value / divisor
            if scaled < 10 and not scaled.is_integer():
                return f"{scaled:.1f}{suffix}"
            return f"{scaled:g}{suffix}"
    return f"{value:g}"


def _dotted_rule(
    draw: ImageDraw.ImageDraw, left: int, right: int, y: int, fill: tuple[int, int, int]
) -> None:
    """Draw a horizontal gridline as two-pixel dots on a five-pixel pitch."""

    points: list[tuple[int, int]] = []
    for x in range(left, right, 5):
        points.append((x, y))
        points.append((min(x + 1, right), y))
    draw.point(points, fill=fill)
