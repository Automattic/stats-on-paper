from __future__ import annotations

from jsp.cache import SnapshotCache
from jsp.http_service import create_app
from jsp.service import SnapshotService


def test_stats_route_is_root_level_and_authenticated(
    tmp_path: object, snapshot: object
) -> None:
    service = SnapshotService(cache=SnapshotCache(tmp_path), fetch=lambda: snapshot)
    app = create_app(service, bearer_token="serve-secret")
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
    client = create_app(service, bearer_token=None).test_client()

    response = client.get("/v1/screen.png?panel=waveshare-4in26")

    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.data.startswith(b"\x89PNG")


def test_unknown_panel_is_a_client_error(tmp_path: object, snapshot: object) -> None:
    service = SnapshotService(cache=SnapshotCache(tmp_path), fetch=lambda: snapshot)
    client = create_app(service, bearer_token=None).test_client()

    response = client.get("/v1/screen.png?panel=unknown")

    assert response.status_code == 400
