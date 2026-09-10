"""Responsive, editorial layouts for small and large e-ink panels."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from PIL import Image, ImageDraw, ImageFont

from sop.models import Commerce, DayOrders, DayPoint, StatsSnapshot
from sop.render.assets import load_font, logo_image, source_label
from sop.render.chart import (
    bar_sparkline,
    draw_bar,
    draw_chart_legend,
    grouped_bar_chart,
    orders_bar_chart,
)
from sop.render.format import (
    AGED_AFTER_SECONDS,
    compact_count,
    safe_ratio,
    site_domain,
    trend_period_label,
    updated_label,
)
from sop.render.output import quantize
from sop.render.palette import BACKGROUND, LayoutColors, PanelProfile, layout_colors
from sop.render.text import draw_right_text, fit_middle_text, font_to_fit, text_width

_Layout = Callable[
    [Image.Image, ImageDraw.ImageDraw, StatsSnapshot, int, LayoutColors, PanelProfile],
    None,
]


class UnsupportedView(ValueError):
    """The requested view does not exist, or this snapshot cannot fill it."""


def render(
    snapshot: StatsSnapshot,
    profile: PanelProfile,
    *,
    view: str = "stats",
    now: datetime | None = None,
) -> Image.Image:
    """Render a snapshot without network, configuration, or panel access."""

    try:
        draw_compact, draw_large = VIEWS[view]
    except KeyError:
        raise UnsupportedView(
            f"Unknown view {view!r}. Choose one of: {', '.join(VIEWS)}."
        ) from None
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    age_seconds = max(
        0,
        int(
            (
                current.astimezone(UTC) - snapshot.fetched_at.astimezone(UTC)
            ).total_seconds()
        ),
    )

    image = Image.new("RGB", profile.size, BACKGROUND)
    draw = ImageDraw.Draw(image)
    if _crisp(profile):
        # A sparse colour palette has no safe home for anti-aliased grey: a
        # mid-grey pixel sits nearer red than black, so blended text edges
        # come out as red fringes. Draw text aliased instead of blending it
        # and then repairing every pixel afterwards.
        draw.fontmode = "1"
    colors = layout_colors(profile, snapshot.source)
    body = draw_compact if profile.size[1] <= 160 else draw_large
    body(image, draw, snapshot, age_seconds, colors, profile)

    return quantize(image, profile)


def _require_commerce(snapshot: StatsSnapshot) -> Commerce:
    """The commerce views need order data; a snapshot may not carry any.

    Worded in snapshot terms: this module sits below the configuration seam
    and does not know which setting would have fetched the orders.
    """

    if snapshot.commerce is None:
        raise UnsupportedView("This snapshot has no commerce data.")
    return snapshot.commerce


def _crisp(profile: PanelProfile) -> bool:
    """Whether every drawn pixel must already be a palette colour."""

    return profile.kind in {"four-color", "spectra"}


def _draw_compact(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    snapshot: StatsSnapshot,
    age_seconds: int,
    colors: LayoutColors,
    profile: PanelProfile,
) -> None:
    width, _ = image.size
    margin = 7
    right = width - margin
    label_font = load_font("regular", 9)
    secondary_font = load_font("bold", 19)
    _draw_compact_chrome(image, draw, snapshot, age_seconds, colors, profile)

    chart_left = 133
    views, hero_font = _fit_count(
        draw,
        snapshot.today.views,
        start_size=41,
        min_size=24,
        max_width=chart_left - margin - 8,
    )
    draw.text((margin, 20), "VIEWS TODAY", fill=colors.muted, font=label_font)
    draw.text((margin - 2, 28), views, fill=colors.ink, font=hero_font)

    drawn = bar_sparkline(
        draw,
        [point.views for point in snapshot.series],
        bounds=(chart_left, 37, right, 66),
        color=colors.views,
        current_color=colors.latest,
        empty_color=colors.muted,
    )
    draw.text(
        (chart_left, 20),
        trend_period_label(snapshot.series[-drawn:] if drawn else [], compact=True),
        fill=colors.muted,
        font=label_font,
    )

    draw.text((margin, 76), "VISITORS TODAY", fill=colors.muted, font=label_font)
    _draw_secondary_count(
        draw, right, snapshot.today.visitors, secondary_font, colors.ink
    )


def _draw_secondary_count(
    draw: ImageDraw.ImageDraw,
    right: int,
    value: int,
    font: ImageFont.FreeTypeFont,
    ink: tuple[int, int, int],
) -> None:
    """The compact panel's second figure, fitted to the space beside its label."""

    text, fitted = _fit_count(
        draw, value, start_size=round(font.size), min_size=11, max_width=right - 90
    )
    draw_right_text(draw, right, 70, text, font=fitted, fill=ink)


def _draw_compact_chrome(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    snapshot: StatsSnapshot,
    age_seconds: int,
    colors: LayoutColors,
    profile: PanelProfile,
) -> None:
    """Site identity, rule, and the provider/freshness footer, for any view."""

    width, _ = image.size
    margin = 7
    right = width - margin
    footer_top = 98
    domain_font = load_font("bold", 10)
    footer_font = load_font("bold", 9)
    time_font = load_font("regular", 9)

    domain = fit_middle_text(
        draw,
        site_domain(snapshot.site.url, fallback=snapshot.site.name),
        domain_font,
        right - margin,
    )
    draw.text((margin, 2), domain, fill=colors.ink, font=domain_font)
    draw.line((margin, 16, right, 16), fill=colors.divider, width=1)

    _draw_footer_rule(draw, 0, width - 1, footer_top, colors, width=2)
    logo = logo_image(
        snapshot.source, height=20, color=colors.brand, crisp=_crisp(profile)
    )
    brand_x = margin
    if logo is not None:
        image.paste(logo, (brand_x, footer_top + 2), logo)
        brand_x += logo.width + 4
    draw.text(
        (brand_x, footer_top + 7),
        source_label(snapshot.source),
        fill=colors.ink,
        font=footer_font,
    )
    draw_right_text(
        draw,
        right,
        footer_top + 7,
        updated_label(snapshot, age_seconds, compact=True),
        font=footer_font if age_seconds > AGED_AFTER_SECONDS else time_font,
        fill=colors.alert if age_seconds > AGED_AFTER_SECONDS else colors.muted,
    )


def _draw_commerce_compact(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    snapshot: StatsSnapshot,
    age_seconds: int,
    colors: LayoutColors,
    profile: PanelProfile,
) -> None:
    """Orders today, the daily orders trend, and views as the second figure."""

    commerce = _require_commerce(snapshot)
    width, _ = image.size
    margin = 7
    right = width - margin
    label_font = load_font("regular", 9)
    secondary_font = load_font("bold", 19)
    _draw_compact_chrome(image, draw, snapshot, age_seconds, colors, profile)

    chart_left = 133
    orders, hero_font = _fit_count(
        draw,
        commerce.orders,
        start_size=41,
        min_size=24,
        max_width=chart_left - margin - 8,
    )
    draw.text((margin, 20), "ORDERS TODAY", fill=colors.muted, font=label_font)
    draw.text((margin - 2, 28), orders, fill=colors.ink, font=hero_font)

    drawn = bar_sparkline(
        draw,
        [row.orders for row in commerce.series],
        bounds=(chart_left, 37, right, 66),
        color=colors.views,
        current_color=colors.latest,
        empty_color=colors.muted,
    )
    draw.text(
        (chart_left, 20),
        trend_period_label(commerce.series[-drawn:] if drawn else [], compact=True),
        fill=colors.muted,
        font=label_font,
    )

    draw.text((margin, 76), "VIEWS TODAY", fill=colors.muted, font=label_font)
    _draw_secondary_count(draw, right, snapshot.today.views, secondary_font, colors.ink)


def _draw_large(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    snapshot: StatsSnapshot,
    age_seconds: int,
    colors: LayoutColors,
    profile: PanelProfile,
) -> None:
    width, height = profile.size
    scale = min(width / 800, height / 480)
    is_extra_large = height >= 900
    margin = round(32 * scale)
    right = width - margin

    label_font = load_font("regular", max(11, round(15 * scale)))
    value_size = max(46, round(68 * scale))
    chart_title_font = load_font("bold", max(11, round(15 * scale)))
    axis_font = load_font("regular", max(9, round(12 * scale)))

    _draw_large_chrome(image, draw, snapshot, age_seconds, colors, profile)
    columns = _metric_columns(margin, right, scale)
    metric_y = round(height * 0.14)
    metric_value_y = round(height * 0.18)
    ratio = safe_ratio(snapshot.today.views, snapshot.today.visitors)
    _draw_metric(
        draw,
        bounds=columns[0],
        y=metric_y,
        value_y=metric_value_y,
        label="VIEWS",
        value=snapshot.today.views,
        font_size=value_size,
        label_font=label_font,
        color=colors.ink,
        marker_color=colors.views,
        marker_style="solid",
        align="left",
        scale=scale,
    )
    _draw_metric(
        draw,
        bounds=columns[1],
        y=metric_y,
        value_y=metric_value_y,
        label="VISITORS",
        value=snapshot.today.visitors,
        font_size=value_size,
        label_font=label_font,
        color=colors.ink,
        marker_color=colors.visitors,
        marker_style="striped",
        align="right",
        scale=scale,
    )
    _draw_metric(
        draw,
        bounds=columns[2],
        y=metric_y,
        value_y=metric_value_y,
        label="VIEWS / VISITOR",
        value=ratio,
        font_size=value_size,
        label_font=label_font,
        color=colors.ink,
        marker_color=colors.divider,
        marker_style="thin",
        align="right",
        scale=scale,
    )

    chart_title_y = round(height * (0.33 if is_extra_large else 0.39))
    chart_top = round(height * (0.39 if is_extra_large else 0.47))
    chart_bottom = round(height * (0.66 if is_extra_large else 0.79))
    plot_left, drawn = grouped_bar_chart(
        draw,
        snapshot.series,
        bounds=(margin, chart_top, right, chart_bottom),
        colors=colors,
        tick_font=axis_font,
        line_width=max(2, round(3 * scale)),
    )
    legend_left = draw_chart_legend(
        draw,
        right,
        chart_title_y,
        colors=colors,
        font=chart_title_font,
        scale=scale,
    )
    draw.text(
        (margin, chart_title_y),
        fit_middle_text(
            draw,
            f"{trend_period_label(drawn, compact=False)} · DAILY TRAFFIC",
            chart_title_font,
            max(0, legend_left - margin - round(16 * scale)),
        ),
        fill=colors.muted,
        font=chart_title_font,
    )

    _draw_chart_dates(
        draw, drawn, plot_left, right, chart_bottom, axis_font, colors, scale
    )

    if is_extra_large:
        _draw_detail_rail(
            draw, _rail_details(snapshot, drawn), colors, margin, right, height, scale
        )


def _draw_large_chrome(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    snapshot: StatsSnapshot,
    age_seconds: int,
    colors: LayoutColors,
    profile: PanelProfile,
) -> None:
    """Site identity, the period marker, and the footer, for any large view."""

    width, height = profile.size
    scale = min(width / 800, height / 480)
    margin = round(32 * scale)
    right = width - margin
    domain_font = load_font("bold", max(14, round(20 * scale)))
    period_font = load_font("regular", max(13, round(16 * scale)))
    footer_font = load_font("bold", max(12, round(16 * scale)))
    timestamp_font = load_font("regular", max(11, round(15 * scale)))

    header_y = round(height * 0.045)
    draw.text(
        (margin, header_y),
        fit_middle_text(
            draw,
            site_domain(snapshot.site.url, fallback=snapshot.site.name),
            domain_font,
            round((right - margin) * 0.72),
        ),
        fill=colors.ink,
        font=domain_font,
    )
    draw_right_text(draw, right, header_y, "TODAY", font=period_font, fill=colors.muted)

    footer_top = round(height * (0.925 if height >= 900 else 0.90))
    _draw_footer_rule(
        draw, 0, width - 1, footer_top, colors, width=max(2, round(3 * scale))
    )
    logo = logo_image(
        snapshot.source,
        height=max(20, round(26 * scale)),
        color=colors.brand,
        crisp=_crisp(profile),
    )
    brand_x = margin
    if logo is not None:
        image.paste(logo, (brand_x, footer_top + max(3, round(7 * scale))), logo)
        brand_x += logo.width + round(8 * scale)
    brand_y = footer_top + max(5, round(10 * scale))
    draw.text(
        (brand_x, brand_y),
        source_label(snapshot.source),
        fill=colors.ink,
        font=footer_font,
    )
    draw_right_text(
        draw,
        right,
        brand_y,
        updated_label(snapshot, age_seconds, compact=False),
        font=timestamp_font,
        fill=colors.alert if age_seconds > AGED_AFTER_SECONDS else colors.muted,
    )


def _draw_commerce_large(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    snapshot: StatsSnapshot,
    age_seconds: int,
    colors: LayoutColors,
    profile: PanelProfile,
) -> None:
    """Orders today and yesterday beside views, over a daily orders chart."""

    commerce = _require_commerce(snapshot)
    width, height = profile.size
    scale = min(width / 800, height / 480)
    margin = round(32 * scale)
    right = width - margin
    label_font = load_font("regular", max(11, round(15 * scale)))
    chart_title_font = load_font("bold", max(11, round(15 * scale)))
    axis_font = load_font("regular", max(9, round(12 * scale)))
    value_size = max(46, round(68 * scale))

    _draw_large_chrome(image, draw, snapshot, age_seconds, colors, profile)

    for column, (label, value) in zip(
        _metric_columns(margin, right, scale),
        (
            ("ORDERS TODAY", commerce.orders),
            ("ORDERS YESTERDAY", _orders_yesterday(commerce)),
            ("VIEWS TODAY", snapshot.today.views),
        ),
        strict=True,
    ):
        _draw_metric(
            draw,
            bounds=column,
            y=round(height * 0.14),
            value_y=round(height * 0.18),
            label=label,
            value=value,
            font_size=value_size,
            label_font=label_font,
            color=colors.ink,
            marker_color=colors.views if label.startswith("ORDERS") else colors.divider,
            marker_style="solid" if label.startswith("ORDERS") else "thin",
            align="left" if label == "ORDERS TODAY" else "right",
            scale=scale,
        )

    is_extra_large = height >= 900
    chart_top = round(height * (0.39 if is_extra_large else 0.47))
    chart_bottom = round(height * (0.66 if is_extra_large else 0.79))
    plot_left, drawn = orders_bar_chart(
        draw,
        commerce.series,
        bounds=(margin, chart_top, right, chart_bottom),
        colors=colors,
        tick_font=axis_font,
        line_width=max(2, round(3 * scale)),
    )
    # One series needs no legend, so the title takes the full width.
    draw.text(
        (margin, round(height * (0.33 if is_extra_large else 0.39))),
        fit_middle_text(
            draw,
            f"{trend_period_label(drawn, compact=False)} · DAILY ORDERS",
            chart_title_font,
            right - margin,
        ),
        fill=colors.muted,
        font=chart_title_font,
    )
    _draw_chart_dates(
        draw, drawn, plot_left, right, chart_bottom, axis_font, colors, scale
    )

    if is_extra_large:
        _draw_detail_rail(
            draw,
            [
                ("VIEWS TODAY", snapshot.today.views),
                ("VISITORS TODAY", snapshot.today.visitors),
                ("LIKES TODAY", snapshot.today.likes),
                ("COMMENTS TODAY", snapshot.today.comments),
            ],
            colors,
            margin,
            right,
            height,
            scale,
        )


def _orders_yesterday(commerce: Commerce) -> int | str:
    """Yesterday's orders, or an em dash when the series has no such row.

    Found by date rather than by position, so a series that skips a day shows
    no figure instead of relabelling an older day as yesterday.
    """

    if not commerce.series:
        return "—"
    wanted = commerce.series[-1].date - timedelta(days=1)
    return next((row.orders for row in commerce.series if row.date == wanted), "—")


def _metric_columns(margin: int, right: int, scale: float) -> list[tuple[int, int]]:
    gap = round(28 * scale)
    column_width = (right - margin - 2 * gap) // 3
    return [
        (margin, margin + column_width),
        (margin + column_width + gap, margin + 2 * column_width + gap),
        (margin + 2 * (column_width + gap), right),
    ]


def _draw_chart_dates(
    draw: ImageDraw.ImageDraw,
    drawn: list[DayPoint] | list[DayOrders],
    plot_left: int,
    right: int,
    chart_bottom: int,
    axis_font: ImageFont.FreeTypeFont,
    colors: LayoutColors,
    scale: float,
) -> None:
    if not drawn:
        return
    date_y = chart_bottom + round(8 * scale)
    first, last = drawn[0].date, drawn[-1].date
    draw.text(
        (plot_left, date_y),
        f"{first.day} {first:%b}",
        fill=colors.muted,
        font=axis_font,
    )
    draw_right_text(
        draw, right, date_y, f"{last.day} {last:%b}", font=axis_font, fill=colors.muted
    )


def _draw_metric(
    draw: ImageDraw.ImageDraw,
    *,
    bounds: tuple[int, int],
    y: int,
    value_y: int,
    label: str,
    value: int | str,
    font_size: int,
    label_font: ImageFont.FreeTypeFont,
    color: tuple[int, int, int],
    marker_color: tuple[int, int, int],
    marker_style: str,
    align: str,
    scale: float,
) -> None:
    """One headline metric: a marker in the series' bar style, a label, a value.

    A count is fitted exactly while any legible size holds it and compacted
    only past that, so two neighbouring values can never overprint.
    """

    left, right = bounds
    marker_length = max(18, round(34 * scale))
    marker_y = y - max(3, round(6 * scale))
    if align == "right":
        marker_left = right - marker_length
        draw_right_text(draw, right, y, label, font=label_font, fill=color)
    else:
        marker_left = left
        draw.text((left, y), label, fill=color, font=label_font)
    if marker_style in {"solid", "striped"}:
        half = max(2, round(4 * scale))
        draw_bar(
            draw,
            (
                marker_left,
                marker_y - half,
                marker_left + marker_length,
                marker_y + half,
            ),
            fill=marker_color,
            style=marker_style,
        )
    else:
        draw.line(
            (marker_left, marker_y, marker_left + marker_length, marker_y),
            fill=marker_color,
            width=1,
        )

    min_size = max(30, round(font_size * 0.62))
    if isinstance(value, int):
        text, value_font = _fit_count(
            draw, value, start_size=font_size, min_size=min_size, max_width=right - left
        )
    else:
        text = value
        value_font = font_to_fit(
            draw,
            value,
            weight="bold",
            start_size=font_size,
            min_size=min_size,
            max_width=right - left,
        )
    if align == "right":
        draw_right_text(draw, right, value_y, text, font=value_font, fill=color)
    else:
        draw.text((left, value_y), text, fill=color, font=value_font)


def _fit_count(
    draw: ImageDraw.ImageDraw,
    count: int,
    *,
    start_size: int,
    min_size: int,
    max_width: int,
) -> tuple[str, ImageFont.FreeTypeFont]:
    """Fit an exact count, compacting it only when no legible size can hold it."""

    exact = f"{count:,}"
    font = font_to_fit(
        draw,
        exact,
        weight="bold",
        start_size=start_size,
        min_size=min_size,
        max_width=max_width,
    )
    if text_width(draw, exact, font) <= max_width:
        return exact, font
    compact = compact_count(count)
    return compact, font_to_fit(
        draw,
        compact,
        weight="bold",
        start_size=start_size,
        min_size=min_size,
        max_width=max_width,
    )


def _rail_details(
    snapshot: StatsSnapshot, drawn: list[DayPoint]
) -> list[tuple[str, int]]:
    """Facts for the detail rail, computed over the days the chart shows.

    A long series is windowed before drawing, so a period high or a day count
    taken from the full series would describe days the reader cannot see.
    """

    views = [point.views for point in drawn]
    average = round(sum(views) / len(views)) if views else 0
    high = max(views, default=0)
    if snapshot.source.lower() == "wpcom":
        fourth = (
            ("ORDERS TODAY", snapshot.commerce.orders)
            if snapshot.commerce
            else ("PERIOD HIGH", high)
        )
        return [
            ("YESTERDAY VIEWS", snapshot.yesterday.views),
            ("LIKES TODAY", snapshot.today.likes),
            ("COMMENTS TODAY", snapshot.today.comments),
            fourth,
        ]
    return [
        ("YESTERDAY VIEWS", snapshot.yesterday.views),
        ("PERIOD HIGH", high),
        ("DAILY AVERAGE", average),
        ("DAYS SHOWN", len(drawn)),
    ]


def _draw_detail_rail(
    draw: ImageDraw.ImageDraw,
    details: list[tuple[str, int]],
    colors: LayoutColors,
    left: int,
    right: int,
    height: int,
    scale: float,
) -> None:
    rail_y = round(height * 0.76)
    label_font = load_font("regular", max(18, round(15 * scale)))
    value_size = max(34, round(38 * scale))
    column = (right - left) / len(details)
    gap = round(16 * scale)
    rule_y = rail_y - round(16 * scale)
    draw.line(
        (left, rule_y, right, rule_y),
        fill=colors.divider,
        width=max(1, round(scale)),
    )
    for index, (label, value) in enumerate(details):
        x = round(left + index * column)
        draw.text((x, rail_y), label, fill=colors.muted, font=label_font)
        # Fitted like every other figure: at a fixed size a seven-digit count
        # prints into the next column and the two numbers merge.
        text, value_font = _fit_count(
            draw,
            value,
            start_size=value_size,
            min_size=max(18, round(value_size * 0.55)),
            max_width=round(column) - gap,
        )
        draw.text(
            (x, rail_y + round(30 * scale)), text, fill=colors.ink, font=value_font
        )


def _draw_footer_rule(
    draw: ImageDraw.ImageDraw,
    left: int,
    right: int,
    y: int,
    colors: LayoutColors,
    *,
    width: int,
) -> None:
    draw.line((left, y, right, y), fill=colors.footer_rule, width=width)


VIEWS: dict[str, tuple[_Layout, _Layout]] = {
    "stats": (_draw_compact, _draw_large),
    "commerce": (_draw_commerce_compact, _draw_commerce_large),
}
