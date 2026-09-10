from __future__ import annotations

from unittest.mock import Mock

import pytest
import requests

from jsp.client import (
    API_V1_BASE_URL,
    AuthenticationError,
    StatsClient,
    TransientClientError,
)


def response(status: int, payload: dict[str, object]) -> Mock:
    item = Mock(spec=requests.Response)
    item.status_code = status
    item.json.return_value = payload
    item.text = str(payload)
    return item


def test_client_uses_bearer_and_endpoint_params() -> None:
    session = Mock(spec=requests.Session)
    session.headers = {}
    session.get.return_value = response(
        200,
        {
            "fields": ["period", "views", "visitors"],
            "data": [],
        },
    )
    client = StatsClient(token="secret", site="example.com", session=session)

    client.visits(quantity=30)

    assert session.headers["Authorization"] == "Bearer secret"
    session.get.assert_called_once_with(
        f"{API_V1_BASE_URL}/sites/example.com/stats/visits",
        params={
            "unit": "day",
            "quantity": 30,
            "stat_fields": "views,visitors",
        },
        timeout=20,
    )


def test_client_does_not_retry_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = Mock(spec=requests.Session)
    session.headers = {}
    session.get.return_value = response(401, {"error": "unauthorized"})
    sleep = Mock()
    monkeypatch.setattr("jsp.client.time.sleep", sleep)
    client = StatsClient(token="bad", site="example.com", session=session)

    with pytest.raises(AuthenticationError, match="jsp login --manual"):
        client.summary(date="2026-07-27")

    assert session.get.call_count == 1
    sleep.assert_not_called()


def test_client_retries_server_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Mock(spec=requests.Session)
    session.headers = {}
    session.get.side_effect = [
        response(503, {"error": "down"}),
        response(503, {"error": "down"}),
        response(503, {"error": "down"}),
    ]
    monkeypatch.setattr("jsp.client.time.sleep", Mock())
    client = StatsClient(token="token", site="example.com", session=session)

    with pytest.raises(TransientClientError):
        client.all_time()

    assert session.get.call_count == 3
