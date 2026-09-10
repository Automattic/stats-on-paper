"""Turn the RGB working canvas into what a panel can physically show."""

from __future__ import annotations

from PIL import Image

from sop.render.palette import PanelProfile


def quantize(image: Image.Image, profile: PanelProfile) -> Image.Image:
    """Map the canvas onto the panel's palette.

    Nothing is repaired here. The layout draws only palette-safe pixels on the
    sparse colour panels, so nearest-colour quantization is exact for them.
    """

    dither = (
        Image.Dither.FLOYDSTEINBERG
        if profile.dither == "floyd-steinberg"
        else Image.Dither.NONE
    )
    if profile.output_mode == "1":
        return image.convert("1", dither=dither)

    palette = Image.new("P", (1, 1))
    flat = [channel for color in profile.colors for channel in color]
    palette.putpalette(flat + [0] * (768 - len(flat)))
    return image.quantize(palette=palette, dither=dither)


def pixel_values(image: Image.Image) -> tuple[object, ...]:
    """Read pixels on Pillow 11 and the renamed Pillow 12.1+ API."""

    modern = getattr(image, "get_flattened_data", None)
    if callable(modern):
        return tuple(modern())
    return tuple(image.getdata())
