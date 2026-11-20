from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from sop.cache import SnapshotCache
from sop.client import AuthenticationError, ResponseError, TransientClientError
from sop.config import load_config
from sop.service import (
    ApiShapeError,
    SnapshotService,
    SnapshotUnavailable,
    build_service,
    cache_key,
)


def test_fresh_cache_is_reused_and_stale_cache_is_replaced(
    tmp_path: object, snapshot: object
) -> None:
    cache = SnapshotCache(tmp_path, key="example.com")
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
    tmp_path: object, snapshot: object, caplog: pytest.LogCaptureFixture
) -> None:
    """Offline, rate limited, or a changed API shape: the last good snapshot
    is shown with its original time, so the panel reports an honest age. The
    reason is logged, so a scheduled job's log says why the numbers are old."""
    cache = SnapshotCache(tmp_path, key="example.com")
    old_timestamp = datetime.now(UTC) - timedelta(days=1)
    cache.save(replace(snapshot, fetched_at=old_timestamp))

    for error in (
        TransientClientError("offline"),
        ResponseError("rate limited", status_code=429),
        ApiShapeError("stats/summary views must not be negative."),
    ):

        def failing(error: Exception = error) -> object:
            raise error

        caplog.clear()
        with caplog.at_level(logging.WARNING):
            result = SnapshotService(cache=cache, fetch=failing).get_snapshot(max_age=0)

        assert result.fetched_at == old_timestamp, type(error).__name__
        assert result.to_public_json()["age_seconds"] > 0
        assert str(error) in caplog.text, type(error).__name__


def test_authentication_failure_never_hides_behind_cache(
    tmp_path: object, snapshot: object
) -> None:
    cache = SnapshotCache(tmp_path, key="example.com")
    cache.save(snapshot)

    def unauthorized() -> object:
        raise AuthenticationError("bad token")

    with pytest.raises(AuthenticationError):
        SnapshotService(cache=cache, fetch=unauthorized).get_snapshot(max_age=0)


def test_corrupt_cache_does_not_block_a_fresh_fetch(
    tmp_path: object, snapshot: object, caplog: pytest.LogCaptureFixture
) -> None:
    """A cache written by an older build must never brick every command."""
    cache = SnapshotCache(tmp_path, key="example.com")
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
    cache = SnapshotCache(tmp_path, key="example.com")
    cache.path.write_text("{not json", encoding="utf-8")

    def offline() -> object:
        raise TransientClientError("offline")

    with pytest.raises(SnapshotUnavailable):
        SnapshotService(cache=cache, fetch=offline).get_snapshot(max_age=0)


def test_a_site_never_answers_from_another_sites_cache(
    tmp_path: object, snapshot: object
) -> None:
    """Switching sites with a failing first fetch must not show, or push to a
    TRMNL, the previous site's numbers."""
    SnapshotCache(tmp_path, key="a.example").save(snapshot)

    def offline() -> object:
        raise TransientClientError("offline")

    other = SnapshotCache(tmp_path, key="b.example")
    with pytest.raises(SnapshotUnavailable):
        SnapshotService(cache=other, fetch=offline).get_snapshot(max_age=0)


def test_the_cache_is_named_after_where_the_numbers_come_from(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setenv("SOP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SOP_SOURCE", "direct")
    monkeypatch.setenv("WPCOM_SITE", "Example.COM")
    direct = cache_key(load_config())
    monkeypatch.setenv("WPCOM_SITE", "other.example")
    assert cache_key(load_config()) != direct
    assert direct == "example.com", "readable, so a person can find the file"

    monkeypatch.setenv("SOP_SOURCE", "url")
    paths = set()
    for url in ("https://a.example", "https://b.example"):
        monkeypatch.setenv("SOP_SOURCE_URL", url)
        paths.add(build_service(load_config()).cache.path)
    assert len(paths) == 2
    assert all(path.parent == tmp_path for path in paths)
