from __future__ import annotations

import pytest

from sop.cache import SnapshotCache
from sop.http_service import create_app
from sop.render.layout import UnsupportedView
from sop.service import SnapshotService


def test_stats_route_is_root_level_and_authenticated(
    tmp_path: object, snapshot: object
) -> None:
    service = SnapshotService(cache=SnapshotCache(tmp_path), fetch=lambda: snapshot)
    app = create_app(service, bearer_token="serve-secret", cache_max_age=600)
    client = app.test_client()

    assert client.get("/v1/stats.json").status_code == 401
    response = client.get(
        "/v1/stats.json",
        headers={"Authorization": "Bearer serve-secret"},
    )

    assert response.status_code == 200
    assert response.data.startswith(b'{"schema":1,')
    assert "data" not in response.get_json()


def test_screen_route_returns_png(tmp_path: object, snapshot: object) -> None:
    service = SnapshotService(cache=SnapshotCache(tmp_path), fetch=lambda: snapshot)
    client = create_app(service, bearer_token=None, cache_max_age=600).test_client()

    response = client.get("/v1/screen.png?panel=waveshare-4in26")

    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.data.startswith(b"\x89PNG")
    assert response.headers["Cache-Control"] == "private, max-age=600"
    etag = response.headers["ETag"]

    unchanged = client.get(
        "/v1/screen.png?panel=waveshare-4in26",
        headers={"If-None-Match": etag},
    )

    assert unchanged.status_code == 304
    assert unchanged.data == b""


def test_view_selects_the_screen(tmp_path: object, snapshot: object) -> None:
    service = SnapshotService(cache=SnapshotCache(tmp_path), fetch=lambda: snapshot)
    client = create_app(service, bearer_token=None, cache_max_age=600).test_client()

    stats = client.get("/v1/screen.png?panel=trmnl")
    commerce = client.get("/v1/screen.png?panel=trmnl&view=commerce")

    assert commerce.status_code == 200
    assert commerce.mimetype == "image/png"
    assert commerce.data != stats.data


def test_a_bad_panel_or_view_is_refused(tmp_path: object, snapshot: object) -> None:
    """Per request it is the caller's fault (400); a typo in SOP_VIEW must
    fail once at startup, not 400 every request forever."""
    service = SnapshotService(cache=SnapshotCache(tmp_path), fetch=lambda: snapshot)
    client = create_app(service, bearer_token=None, cache_max_age=600).test_client()

    assert client.get("/v1/screen.png?panel=unknown").status_code == 400
    assert client.get("/v1/screen.png?view=nope").status_code == 400

    with pytest.raises(UnsupportedView, match="Unknown view 'nope'"):
        create_app(service, bearer_token=None, cache_max_age=600, default_view="nope")
