"""Waveshare 4.26-inch monochrome panel driver."""

from __future__ import annotations

from typing import Any

from PIL import Image


class Waveshare4in26:
    def __init__(self) -> None:
        try:
            from waveshare_epd import epd4in26  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError(
                "The Waveshare epd4in26 driver is not installed. The vendor does "
                "not currently publish this model as a compatible PyPI wheel, so "
                "this panel is render-only until that changes."
            ) from error
        self._display: Any = epd4in26.EPD()

    def show(self, image: Image.Image) -> None:
        self._display.init()
        self._display.display(self._display.getbuffer(image.convert("1")))

    def sleep(self) -> None:
        self._display.sleep()
