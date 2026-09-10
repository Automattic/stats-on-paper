"""Small interface shared by optional hardware drivers."""

from __future__ import annotations

from typing import Protocol

from PIL import Image


class Panel(Protocol):
    def show(self, image: Image.Image) -> None: ...

    def sleep(self) -> None: ...


def open_panel(name: str) -> Panel:
    if name == "waveshare-4in26":
        from sop.panels.waveshare import Waveshare4in26

        return Waveshare4in26()
    if name in {"impression-4in0", "impression-7in3"}:
        from sop.panels.inky import InkyImpression

        return InkyImpression()
    raise ValueError(f"Panel {name!r} is render-only and has no local driver.")
