"""The one 800×480 canvas expressed through three panel palettes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CANVAS_SIZE = (800, 480)


@dataclass(frozen=True)
class PanelProfile:
    name: str
    size: tuple[int, int]
    colors: tuple[tuple[int, int, int], ...]
    dither: Literal["none", "floyd-steinberg"]
    output_mode: Literal["1", "P"]


PROFILES: dict[str, PanelProfile] = {
    "waveshare-4in26": PanelProfile(
        name="waveshare-4in26",
        size=CANVAS_SIZE,
        colors=((255, 255, 255), (0, 0, 0)),
        dither="none",
        output_mode="1",
    ),
    "impression-7in3": PanelProfile(
        name="impression-7in3",
        size=CANVAS_SIZE,
        colors=(
            (0, 0, 0),
            (255, 255, 255),
            (220, 38, 38),
            (245, 196, 0),
            (35, 82, 170),
            (48, 135, 74),
        ),
        dither="floyd-steinberg",
        output_mode="P",
    ),
    "trmnl": PanelProfile(
        name="trmnl",
        size=CANVAS_SIZE,
        colors=((255, 255, 255), (0, 0, 0)),
        dither="none",
        output_mode="1",
    ),
}


def get_profile(name: str) -> PanelProfile:
    try:
        return PROFILES[name]
    except KeyError as error:
        choices = ", ".join(PROFILES)
        raise ValueError(f"Unknown panel {name!r}. Choose one of: {choices}") from error
