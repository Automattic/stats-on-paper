from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jsp.models import SnapshotFormatError, snapshot_from_public_json


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


def test_unknown_schema_fails_loudly(snapshot: object) -> None:
    payload = snapshot.to_public_json()
    payload["schema"] = 2

    with pytest.raises(SnapshotFormatError, match="Unsupported snapshot schema 2"):
        snapshot_from_public_json(payload)
