"""Bundled fonts and provider marks, resolved from the wheel or the checkout."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import cast

from PIL import Image, ImageFont

from jsp.render.format import truncate
from jsp.render.output import pixel_values


def _asset_path(kind: str, filename: str) -> Path:
    """Find a bundled asset in the installed package, else the repository."""

    packaged = files("jsp").joinpath("assets", kind, filename)
    if packaged.is_file():
        return Path(str(packaged))
    repository = Path(__file__).resolve().parents[3] / "assets" / kind / filename
    if repository.is_file():
        return repository
    raise RuntimeError(
        f"Bundled asset {filename} is missing; reinstall jetpack-stats-on-paper."
    )


@lru_cache(maxsize=256)
def load_font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a bundled face once per weight and size.

    Auto-sizing text probes many sizes per metric, so an uncached load reads the
    same file from disk dozens of times per frame. One `serve` process renders
    every panel, which needs well over a hundred distinct keys once counts run
    to twelve digits; the bound is generous so nothing is evicted mid-frame.
    """

    filename = "Inter-Bold.otf" if weight == "bold" else "Inter-Regular.otf"
    return ImageFont.truetype(str(_asset_path("fonts", filename)), size=size)


@lru_cache(maxsize=24)
def logo_image(
    source: str,
    *,
    height: int,
    color: tuple[int, int, int],
    crisp: bool = False,
) -> Image.Image | None:
    """The provider mark at `height`, recoloured to the brand ink.

    With `crisp`, edge alpha is snapped to opaque or clear so compositing can
    never produce a blend the panel's palette cannot show.
    """

    filename = _logo_filename(source)
    if filename is None:
        return None
    with Image.open(_asset_path("logos", filename)) as opened:
        raw = opened.convert("RGBA")
    target_width = max(1, round(raw.width * height / raw.height))
    resized = raw.resize((target_width, height), Image.Resampling.LANCZOS)
    recolored: list[tuple[int, int, int, int]] = []
    for red, green, blue, alpha in cast(
        tuple[tuple[int, int, int, int], ...], pixel_values(resized)
    ):
        if crisp:
            alpha = 255 if alpha >= 128 else 0
        if alpha == 0:
            recolored.append((0, 0, 0, 0))
        elif min(red, green, blue) > 215:
            recolored.append((255, 255, 255, alpha))
        else:
            recolored.append((*color, alpha))
    output = Image.new("RGBA", resized.size)
    output.putdata(recolored)
    return output


def _logo_filename(source: str) -> str | None:
    normalized = source.lower()
    if normalized in {"parsely", "parse.ly"}:
        return "parsely-mark.png"
    if normalized in {"wpcom", "jetpack", "wordpress.com"}:
        return "jetpack-mark.png"
    return None


def source_label(source: str) -> str:
    normalized = source.lower()
    if normalized in {"parsely", "parse.ly"}:
        return "Parse.ly"
    if normalized in {"wpcom", "jetpack", "wordpress.com"}:
        return "Jetpack Stats"
    return truncate(source, 18)
