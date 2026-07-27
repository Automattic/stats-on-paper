from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from jsp.cache import SnapshotCache
from jsp.client import AuthenticationError, ResponseError, TransientClientError
from jsp.service import SnapshotService


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
