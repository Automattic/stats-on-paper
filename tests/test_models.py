from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sop.models import SnapshotFormatError, snapshot_from_public_json


def test_public_json_has_root_keys_and_truthful_age(snapshot: object) -> None:
    now = datetime(2026, 7, 27, 12, 35, 56, tzinfo=UTC)
    payload = snapshot.to_public_json(now=now)

    assert next(iter(payload)) == "schema"
    assert payload["age_seconds"] == 60
    assert "data" not in payload
    assert payload["site"]["id"] == 123456789

    restored = snapshot_from_public_json(payload)
    assert restored.fetched_at == snapshot.fetched_at
    assert restored.series == snapshot.series
    assert restored.commerce == snapshot.commerce


def test_unknown_schema_fails_loudly(snapshot: object) -> None:
    payload = snapshot.to_public_json()
    payload["schema"] = 2

    with pytest.raises(SnapshotFormatError, match="Unsupported snapshot schema 2"):
        snapshot_from_public_json(payload)


def test_negative_counts_are_rejected_at_the_boundary(snapshot: object) -> None:
    """A count is a magnitude; a negative one means the payload is wrong.

    Letting it through would have the renderer clamp it to zero and draw a
    corrupt day as a quiet one.
    """
    payload = snapshot.to_public_json()
    payload["today"]["views"] = -1
    with pytest.raises(SnapshotFormatError, match=r"today\.views must not be negative"):
        snapshot_from_public_json(payload)

    payload = snapshot.to_public_json()
    payload["series"][1]["visitors"] = -5
    with pytest.raises(
        SnapshotFormatError, match=r"series\[1\].visitors must not be negative"
    ):
        snapshot_from_public_json(payload)


def test_commerce_today_must_agree_with_the_series(snapshot: object) -> None:
    """Two representations of today's orders must not contradict each other.

    The large view labels `orders` as today while the chart's last bar comes
    from the series; a payload where they disagree is corrupt, not renderable.
    """
    payload = snapshot.to_public_json()
    payload["commerce"]["orders"] = 99

    with pytest.raises(SnapshotFormatError, match=r"commerce\.orders must equal"):
        snapshot_from_public_json(payload)


def test_a_day_may_appear_only_once(snapshot: object) -> None:
    """A repeated date would be drawn as two days and counted as two."""
    payload = snapshot.to_public_json()
    payload["series"][1]["date"] = payload["series"][0]["date"]

    with pytest.raises(
        SnapshotFormatError, match="series has more than one 2026-07-25"
    ):
        snapshot_from_public_json(payload)

    orders = snapshot.to_public_json()
    orders["commerce"]["series"][1]["date"] = orders["commerce"]["series"][0]["date"]

    with pytest.raises(
        SnapshotFormatError, match=r"commerce\.series has more than one"
    ):
        snapshot_from_public_json(orders)
