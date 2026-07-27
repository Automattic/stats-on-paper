"""A deliberately plain e-ink layout."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from jsp.models import DayPoint, StatsSnapshot
from jsp.render.palette import PanelProfile

_BACKGROUND = (255, 255, 255)
_INK = (17, 17, 17)
_MUTED = (84, 84, 84)
_BLUE = (35, 82, 170)
_STALE = (190, 32, 32)
_STALE_AFTER_SECONDS = 40


def render(
    snapshot: StatsSnapshot,
    profile: PanelProfile,
    *,
    now: datetime | None = None,
) -> Image.Image:
    """Render a snapshot without network, configuration, or panel access."""

    if profile.size != (800, 480):
        raise ValueError("Layout v1 requires an 800×480 profile.")

    current = now or datetime.now(UTC)
    age_seconds = max(
        0,
        int(
            (
                current.astimezone(UTC) - snapshot.fetched_at.astimezone(UTC)
            ).total_seconds()
        ),
    )

    image = Image.new("RGB", profile.size, _BACKGROUND)
    draw = ImageDraw.Draw(image)
    regular = _font("regular", 34)
    small = _font("regular", 22)
    tiny = _font("regular", 18)
    hero = _font("bold", 164)
    secondary = _font("bold", 52)

    draw.text((42, 28), "TODAY", fill=_MUTED, font=small)
    draw.text((36, 48), f"{snapshot.today.views:,}", fill=_INK, font=hero)
    draw.text((48, 232), "views", fill=_MUTED, font=regular)

    draw.text((455, 47), "VISITORS", fill=_MUTED, font=small)
    draw.text(
        (450, 76),
        f"{snapshot.today.visitors:,}",
        fill=_INK,
        font=secondary,
    )

    draw.text((455, 157), "LAST 30 DAYS", fill=_MUTED, font=small)
    _sparkline(
        draw,
        snapshot.series,
        bounds=(455, 196, 758, 326),
        color=_BLUE,
    )

    draw.line((42, 376, 758, 376), fill=(168, 164, 153), width=2)
    site_name = _truncate(snapshot.site.name, 34)
    draw.text((42, 401), site_name, fill=_INK, font=small)

    timestamp = snapshot.fetched_at.astimezone(UTC).strftime("%d %b %Y · %H:%M UTC")
    status = f"Updated {timestamp}"
    status_color = _MUTED
    if age_seconds > _STALE_AFTER_SECONDS:
        status = f"STALE · {_human_age(age_seconds)} old · {timestamp}"
        status_color = _STALE
    right = draw.textbbox((0, 0), status, font=tiny)[2]
    draw.text((758 - right, 407), status, fill=status_color, font=tiny)

    return _quantize(image, profile)


def _sparkline(
    draw: ImageDraw.ImageDraw,
    points: list[DayPoint],
    *,
    bounds: tuple[int, int, int, int],
    color: tuple[int, int, int],
) -> None:
    left, top, right, bottom = bounds
    draw.line((left, bottom, right, bottom), fill=(186, 182, 172), width=2)
    if not points:
        draw.text(
            (left, top + 40),
            "No series data",
            fill=_MUTED,
            font=_font("regular", 18),
        )
        return

    values = [point.views for point in points]
    maximum = max(values)
    minimum = min(values)
    spread = max(1, maximum - minimum)
    x_step = (right - left) / max(1, len(values) - 1)
    coordinates = [
        (
            round(left + index * x_step),
            round(bottom - ((value - minimum) / spread) * (bottom - top)),
        )
        for index, value in enumerate(values)
    ]
    if len(coordinates) == 1:
        x, y = coordinates[0]
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=color)
    else:
        draw.line(coordinates, fill=color, width=5, joint="curve")


def _quantize(image: Image.Image, profile: PanelProfile) -> Image.Image:
    dither = (
        Image.Dither.FLOYDSTEINBERG
        if profile.dither == "floyd-steinberg"
        else Image.Dither.NONE
    )
    if profile.output_mode == "1":
        return image.convert("1", dither=dither)

    palette = Image.new("P", (1, 1))
    flat = [channel for color in profile.colors for channel in color]
    padded = flat + [0] * (768 - len(flat))
    palette.putpalette(padded)
    return image.quantize(palette=palette, dither=dither)


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    filename = (
        "AtkinsonHyperlegible-Bold.otf"
        if weight == "bold"
        else "AtkinsonHyperlegible-Regular.otf"
    )
    packaged = files("jsp").joinpath("assets", "fonts", filename)
    if packaged.is_file():
        return ImageFont.truetype(str(packaged), size=size)

    repository_asset = (
        Path(__file__).resolve().parents[3] / "assets" / "fonts" / filename
    )
    if repository_asset.is_file():
        return ImageFont.truetype(str(repository_asset), size=size)
    raise RuntimeError(
        f"Bundled font {filename} is missing; reinstall jetpack-stats-on-paper."
    )


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"


def _human_age(seconds: int) -> str:
    if seconds < 120:
        return f"{seconds} sec"
    if seconds < 7200:
        return f"{seconds // 60} min"
    if seconds < 172800:
        return f"{seconds // 3600} hr"
    return f"{seconds // 86400} days"
