from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jsp.render import render
from jsp.render.palette import PROFILES


@pytest.mark.parametrize(
    ("profile_name", "mode"),
    [
        ("waveshare-4in26", "1"),
        ("impression-7in3", "P"),
        ("trmnl", "1"),
    ],
)
def test_render_smoke(profile_name: str, mode: str, snapshot: object) -> None:
    image = render(
        snapshot,
        PROFILES[profile_name],
        now=datetime(2026, 7, 27, 12, 35, 0, tzinfo=UTC),
    )

    assert image.size == (800, 480)
    assert image.mode == mode


def test_stale_render_differs_from_fresh(snapshot: object) -> None:
    fresh = render(
        snapshot,
        PROFILES["impression-7in3"],
        now=datetime(2026, 7, 27, 12, 35, 0, tzinfo=UTC),
    )
    stale = render(
        snapshot,
        PROFILES["impression-7in3"],
        now=datetime(2026, 7, 27, 13, 35, 0, tzinfo=UTC),
    )

    assert fresh.tobytes() != stale.tobytes()
