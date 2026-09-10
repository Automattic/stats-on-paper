"""Record the render reference table and the committed preview images.

Not a test module: pytest collects `test_*.py` only. `tests/test_render.py`
imports `render_frames` from here so one function produces both the hashes it
asserts and the PNGs the README shows, and the two can never drift.

Run after an intended rendering change:

    uv run python tests/record_render_hashes.py
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path

from PIL import Image

from jsp.models import snapshot_from_public_json
from jsp.render import render
from jsp.render.layout import VIEWS
from jsp.render.palette import PROFILES

FIXTURES = Path(__file__).parent / "fixtures"
TABLE_PATH = FIXTURES / "render-hashes.json"
PREVIEWS = Path(__file__).parents[1] / "assets" / "previews"
# The frames README shows. Each is also a key in the table.
PREVIEW_FRAMES = (
    ("stats", "impression-7in3"),
    ("stats", "trmnl"),
    ("stats", "waveshare-2in13"),
    ("commerce", "impression-7in3"),
)


def render_frames() -> Iterator[tuple[str, str, Image.Image]]:
    """Yield (view, profile, image) for every view and profile.

    Rendering at the snapshot's own `fetched_at` fixes the only clock the
    renderer reads, which makes the output byte-deterministic.
    """

    snapshot = snapshot_from_public_json(
        json.loads((FIXTURES / "sample-stats.json").read_text(encoding="utf-8"))
    )
    for view in VIEWS:
        for name, profile in PROFILES.items():
            yield (
                view,
                name,
                render(snapshot, profile, view=view, now=snapshot.fetched_at),
            )


def frame_key(image: Image.Image) -> dict[str, object]:
    """Identify a frame by the bytes sent to the panel and the inks they mean.

    Neither half is enough on its own. A P-mode image's raw bytes are palette
    indices, so recolouring a profile leaves them identical; hashing only the
    resolved RGB misses a reordered palette, which changes every byte the
    panel is clocked while the picture looks the same.
    """

    palette = image.getpalette() or []
    return {
        "mode": image.mode,
        "size": list(image.size),
        "sha256": sha256(image.tobytes() + bytes(palette)).hexdigest(),
    }


def main() -> None:
    table: dict[str, dict[str, object]] = {}
    for view, name, image in render_frames():
        table[f"{view}/{name}"] = frame_key(image)
        _save_preview(view, name, image)
    TABLE_PATH.write_text(json.dumps(table, indent=2) + "\n", encoding="utf-8")
    print(f"{TABLE_PATH}: {len(table)} frames")


def _save_preview(view: str, name: str, image: Image.Image) -> None:
    """Write this frame as a preview image if the README shows it."""

    if (view, name) in PREVIEW_FRAMES:
        PREVIEWS.mkdir(parents=True, exist_ok=True)
        stem = name if view == "stats" else f"{view}-{name}"
        image.save(PREVIEWS / f"{stem}.png", format="PNG")


if __name__ == "__main__":
    main()
