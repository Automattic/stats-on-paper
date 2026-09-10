"""Native-size render targets and their physical panel palettes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Layout inks. Panel palettes are the physical colours a panel can show; these
# are the colours the layout asks for, and quantization snaps one to the other.
BACKGROUND = (255, 255, 255)
INK = (17, 17, 17)
MUTED = (84, 84, 84)
BLUE = (35, 82, 170)
RED = (220, 38, 38)
YELLOW = (245, 196, 0)
JETPACK_GREEN = (6, 158, 8)
PARSELY_GREEN = (89, 170, 71)

PaletteKind = Literal["mono", "four-color", "spectra", "grayscale"]

COMPACT_SIZE = (250, 122)
INKY_4_SIZE = (600, 400)
LANDSCAPE_SIZE = (800, 480)
LARGE_SIZE = (1872, 1404)


@dataclass(frozen=True)
class PanelProfile:
    name: str
    size: tuple[int, int]
    colors: tuple[tuple[int, int, int], ...]
    dither: Literal["none", "floyd-steinberg"]
    output_mode: Literal["1", "P"]

    @property
    def kind(self) -> PaletteKind:
        """Which ink policy and quantization path this panel needs."""

        if self.output_mode == "1":
            return "mono"
        palette = set(self.colors)
        if RED in palette and YELLOW in palette and len(palette) == 4:
            return "four-color"
        if BLUE in palette:
            return "spectra"
        return "grayscale"


PROFILES: dict[str, PanelProfile] = {
    "waveshare-2in13": PanelProfile(
        name="waveshare-2in13",
        size=COMPACT_SIZE,
        colors=((255, 255, 255), (0, 0, 0)),
        dither="none",
        output_mode="1",
    ),
    "waveshare-2in13-four-color": PanelProfile(
        name="waveshare-2in13-four-color",
        size=COMPACT_SIZE,
        colors=(
            (255, 255, 255),
            (0, 0, 0),
            (220, 38, 38),
            (245, 196, 0),
        ),
        dither="none",
        output_mode="P",
    ),
    "impression-4in0": PanelProfile(
        name="impression-4in0",
        size=INKY_4_SIZE,
        colors=(
            (0, 0, 0),
            (255, 255, 255),
            (220, 38, 38),
            (245, 196, 0),
            (35, 82, 170),
            (48, 135, 74),
        ),
        dither="none",
        output_mode="P",
    ),
    "waveshare-4in26": PanelProfile(
        name="waveshare-4in26",
        size=LANDSCAPE_SIZE,
        colors=((255, 255, 255), (0, 0, 0)),
        dither="none",
        output_mode="1",
    ),
    "waveshare-4in26-four-color": PanelProfile(
        name="waveshare-4in26-four-color",
        size=LANDSCAPE_SIZE,
        colors=(
            (255, 255, 255),
            (0, 0, 0),
            (220, 38, 38),
            (245, 196, 0),
        ),
        dither="none",
        output_mode="P",
    ),
    "impression-7in3": PanelProfile(
        name="impression-7in3",
        size=LANDSCAPE_SIZE,
        colors=(
            (0, 0, 0),
            (255, 255, 255),
            (220, 38, 38),
            (245, 196, 0),
            (35, 82, 170),
            (48, 135, 74),
        ),
        dither="none",
        output_mode="P",
    ),
    "waveshare-10in3": PanelProfile(
        name="waveshare-10in3",
        size=LARGE_SIZE,
        colors=(
            (0, 0, 0),
            (85, 85, 85),
            (170, 170, 170),
            (255, 255, 255),
        ),
        dither="none",
        output_mode="P",
    ),
    "trmnl": PanelProfile(
        name="trmnl",
        size=LANDSCAPE_SIZE,
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


@dataclass(frozen=True, kw_only=True)
class LayoutColors:
    """The inks one render uses, chosen once per panel kind and provider."""

    ink: tuple[int, int, int]
    muted: tuple[int, int, int]
    views: tuple[int, int, int]
    visitors: tuple[int, int, int]
    latest: tuple[int, int, int]
    brand: tuple[int, int, int]
    footer_rule: tuple[int, int, int]
    divider: tuple[int, int, int]
    alert: tuple[int, int, int]


def layout_colors(profile: PanelProfile, source: str) -> LayoutColors:
    normalized_source = source.lower()
    is_parsely = normalized_source in {"parsely", "parse.ly"}
    is_jetpack = normalized_source in {"wpcom", "jetpack", "wordpress.com"}
    brand_green = PARSELY_GREEN if is_parsely else JETPACK_GREEN

    if profile.kind == "mono":
        return LayoutColors(
            ink=INK,
            muted=INK,
            views=INK,
            visitors=INK,
            latest=INK,
            brand=INK,
            footer_rule=INK,
            divider=INK,
            alert=INK,
        )
    if profile.kind == "four-color":
        return LayoutColors(
            ink=INK,
            muted=INK,
            views=INK,
            visitors=INK,
            latest=YELLOW,
            brand=INK,
            footer_rule=YELLOW,
            divider=INK,
            alert=RED,
        )
    if profile.kind == "spectra":
        views = brand_green if is_parsely or is_jetpack else INK
        brand = brand_green if is_parsely or is_jetpack else INK
        return LayoutColors(
            ink=INK,
            muted=INK,
            views=views,
            visitors=BLUE,
            latest=views,
            brand=brand,
            footer_rule=brand,
            divider=INK,
            alert=RED,
        )
    return LayoutColors(
        ink=INK,
        muted=MUTED,
        views=INK,
        visitors=MUTED,
        latest=INK,
        brand=INK,
        footer_rule=INK,
        divider=(168, 164, 153),
        alert=INK,
    )
