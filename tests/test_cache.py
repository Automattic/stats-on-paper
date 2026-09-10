from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from sop.cache import SnapshotCache
from sop.client import AuthenticationError, ResponseError, TransientClientError
from sop.service import ApiShapeError, SnapshotService, SnapshotUnavailable


def test_fresh_cache_is_reused_and_stale_cache_is_replaced(
    tmp_path: object, snapshot: object
) -> None:
    cache = SnapshotCache(tmp_path)
    current = datetime.now(UTC)
    cache.save(replace(snapshot, fetched_at=current))
    calls = 0

    def fetch() -> object:
        nonlocal calls
        calls += 1
        return replace(snapshot, fetched_at=datetime.now(UTC))

    service = SnapshotService(cache=cache, fetch=fetch)

    assert service.get_snapshot(max_age=60).fetched_at == current
    assert calls == 0

    cache.save(replace(snapshot, fetched_at=current - timedelta(hours=1)))
    fresh = service.get_snapshot(max_age=60)

    assert calls == 1
    assert fresh.fetched_at > current - timedelta(hours=1)
    assert cache.load() == fresh


def test_fetch_failures_return_stale_without_changing_timestamp(
    tmp_path: object, snapshot: object
) -> None:
    """Offline, rate limited, or a changed API shape: the last good snapshot
    is shown with its original time, so the panel reports an honest age."""
    cache = SnapshotCache(tmp_path)
    old_timestamp = datetime.now(UTC) - timedelta(days=1)
    cache.save(replace(snapshot, fetched_at=old_timestamp))

    for error in (
        TransientClientError("offline"),
        ResponseError("rate limited", status_code=429),
        ApiShapeError("stats/summary views must not be negative."),
    ):

        def failing(error: Exception = error) -> object:
            raise error

        result = SnapshotService(cache=cache, fetch=failing).get_snapshot(max_age=0)

        assert result.fetched_at == old_timestamp, type(error).__name__
        assert result.to_public_json()["age_seconds"] > 0


def test_authentication_failure_never_hides_behind_cache(
    tmp_path: object, snapshot: object
) -> None:
    cache = SnapshotCache(tmp_path)
    cache.save(snapshot)

    def unauthorized() -> object:
        raise AuthenticationError("bad token")

    with pytest.raises(AuthenticationError):
        SnapshotService(cache=cache, fetch=unauthorized).get_snapshot(max_age=0)


def test_corrupt_cache_does_not_block_a_fresh_fetch(
    tmp_path: object, snapshot: object, caplog: pytest.LogCaptureFixture
) -> None:
    """A cache written by an older build must never brick every command."""
    cache = SnapshotCache(tmp_path)
    stale = snapshot.to_public_json()
    stale["today"]["views"] = -1
    cache.path.write_text(json.dumps(stale), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        result = SnapshotService(cache=cache, fetch=lambda: snapshot).get_snapshot(
            max_age=0
        )

    assert result == snapshot
    assert cache.load() == snapshot, "the bad file is replaced, not kept"
    assert "cache" in caplog.text.lower()


def test_corrupt_cache_with_failed_fetch_is_unavailable(
    tmp_path: object, snapshot: object
) -> None:
    cache = SnapshotCache(tmp_path)
    cache.path.write_text("{not json", encoding="utf-8")

    def offline() -> object:
        raise TransientClientError("offline")

    with pytest.raises(SnapshotUnavailable):
        SnapshotService(cache=cache, fetch=offline).get_snapshot(max_age=0)
