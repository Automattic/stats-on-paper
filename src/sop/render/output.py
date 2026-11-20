"""Turn the RGB working canvas into what a panel can physically show."""

from __future__ import annotations

from io import BytesIO

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


def encode_png(image: Image.Image, profile: PanelProfile) -> bytes:
    """Encode a frame in the format its panel expects.

    A palette frame is written with the fewest bits per pixel the profile's
    palette needs. Pillow would otherwise write all 256 entries at 8 bits, and
    TRMNL's own server sends the OG family 1- and 2-bit PNGs because their
    firmware cannot decode full-colour rows that wide. The depth follows the
    profile, not the picture, so the format never depends on the numbers.
    """

    output = BytesIO()
    if profile.output_mode == "P":
        bits = next(depth for depth in (1, 2, 4, 8) if len(profile.colors) <= 2**depth)
        image.save(output, format="PNG", bits=bits)
    else:
        image.save(output, format="PNG")
    return output.getvalue()


def pixel_values(image: Image.Image) -> tuple[object, ...]:
    """Read pixels on Pillow 11 and the renamed Pillow 12.1+ API."""

    modern = getattr(image, "get_flattened_data", None)
    if callable(modern):
        return tuple(modern())
    return tuple(image.getdata())
