"""Measure, fit and place text."""

from __future__ import annotations

from math import ceil

from PIL import ImageDraw, ImageFont

from jsp.render.assets import load_font


def text_width(
    draw: ImageDraw.ImageDraw,
    value: str,
    font: ImageFont.FreeTypeFont,
) -> int:
    left, _, right, _ = draw.textbbox((0, 0), value, font=font)
    return round(right - left)


def font_height(font: ImageFont.FreeTypeFont) -> int:
    top, bottom = font.getbbox("0123456789")[1::2]
    return round(bottom - top)


def draw_right_text(
    draw: ImageDraw.ImageDraw,
    right: int,
    y: int,
    value: str,
    *,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
) -> None:
    draw.text((right - text_width(draw, value, font), y), value, fill=fill, font=font)


def fit_middle_text(
    draw: ImageDraw.ImageDraw,
    value: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> str:
    if text_width(draw, value, font) <= max_width:
        return value
    keep = max(2, len(value) - 1)
    while keep > 2:
        left_count = ceil(keep * 0.55)
        right_count = keep - left_count
        candidate = f"{value[:left_count]}…{value[-right_count:]}"
        if text_width(draw, candidate, font) <= max_width:
            return candidate
        keep -= 1
    return "…"


def font_to_fit(
    draw: ImageDraw.ImageDraw,
    value: str,
    *,
    weight: str,
    start_size: int,
    min_size: int,
    max_width: int,
) -> ImageFont.FreeTypeFont:
    size = start_size
    face = load_font(weight, size)
    while size > min_size and text_width(draw, value, face) > max_width:
        size -= 1
        face = load_font(weight, size)
    return face
