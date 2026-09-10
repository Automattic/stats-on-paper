from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from sop.cache import SnapshotCache
from sop.client import AuthenticationError, ResponseError, TransientClientError
from sop.service import ApiShapeError, SnapshotService, SnapshotUnavailable


def test_cache_hit_skips_fetch(tmp_path: object, snapshot: object) -> None:
    cache = SnapshotCache(tmp_path)
    current = datetime.now(UTC)
    cached = replace(snapshot, fetched_at=current)
    cache.save(cached)
    calls = 0

    def fetch() -> object:
        nonlocal calls
        calls += 1
        return snapshot

    service = SnapshotService(cache=cache, fetch=fetch)
    result = service.get_snapshot(max_age=60)

    assert result.fetched_at == current
    assert calls == 0


def test_stale_cache_is_replaced(tmp_path: object, snapshot: object) -> None:
    cache = SnapshotCache(tmp_path)
    old = replace(snapshot, fetched_at=datetime.now(UTC) - timedelta(hours=1))
    fresh = replace(snapshot, fetched_at=datetime.now(UTC))
    cache.save(old)
    service = SnapshotService(cache=cache, fetch=lambda: fresh)

    assert service.get_snapshot(max_age=60).fetched_at == fresh.fetched_at
    assert cache.load() == fresh


def test_network_failure_returns_stale_without_changing_timestamp(
    tmp_path: object, snapshot: object
) -> None:
    cache = SnapshotCache(tmp_path)
    old_timestamp = datetime.now(UTC) - timedelta(days=1)
    old = replace(snapshot, fetched_at=old_timestamp)
    cache.save(old)

    def unavailable() -> object:
        raise TransientClientError("offline")

    result = SnapshotService(cache=cache, fetch=unavailable).get_snapshot(max_age=0)

    assert result.fetched_at == old_timestamp
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


def test_other_api_failure_can_return_stale(tmp_path: object, snapshot: object) -> None:
    cache = SnapshotCache(tmp_path)
    cache.save(snapshot)

    def api_failure() -> object:
        raise ResponseError("rate limited", status_code=429)

    result = SnapshotService(cache=cache, fetch=api_failure).get_snapshot(max_age=0)

    assert result.fetched_at == snapshot.fetched_at


def test_malformed_api_response_returns_stale_cache(
    tmp_path: object, snapshot: object
) -> None:
    cache = SnapshotCache(tmp_path)
    cache.save(snapshot)

    def malformed() -> object:
        raise ApiShapeError("stats/summary views must not be negative.")

    result = SnapshotService(cache=cache, fetch=malformed).get_snapshot(max_age=0)

    assert result.fetched_at == snapshot.fetched_at


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
