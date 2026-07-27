"""Pimoroni Inky Impression driver."""

from __future__ import annotations

from typing import Any

from PIL import Image


class InkyImpression:
    def __init__(self) -> None:
        try:
            from inky.auto import auto  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError(
                "The Inky driver is not installed. Run `pip install "
                '"jetpack-stats-on-paper[inky]"`.'
            ) from error
        self._display: Any = auto()

    def show(self, image: Image.Image) -> None:
        self._display.set_image(image)
        self._display.show()

    def sleep(self) -> None:
        # Inky's show() completes the refresh and leaves the panel holding it.
        # There is no separate sleep call in the public Inky interface.
        return None
