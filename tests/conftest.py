from __future__ import annotations

import socket
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from sop.models import (
    Commerce,
    DayOrders,
    DayPoint,
    SiteRef,
    StatsSnapshot,
    Totals,
)


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked_connect(self: socket.socket, address: object) -> None:
        del self, address
        raise AssertionError("Tests must not use the network")

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)


@pytest.fixture(autouse=True)
def no_real_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite hermetic: never read a developer's real .env file."""

    monkeypatch.setattr("sop.config.load_dotenv", lambda: None)


@pytest.fixture
def snapshot() -> StatsSnapshot:
    return StatsSnapshot(
        schema=1,
        site=SiteRef(
            id=123456789,
            name="The North Star",
            url="https://northstar.test",
        ),
        fetched_at=datetime(2026, 7, 27, 12, 34, 56, tzinfo=UTC),
        today=Totals(views=1842, visitors=1206, likes=31, comments=8),
        yesterday=Totals(views=1630, visitors=1094, likes=27, comments=5),
        series=[
            DayPoint(date=date(2026, 7, 25), views=1512, visitors=998),
            DayPoint(date=date(2026, 7, 26), views=1630, visitors=1094),
            DayPoint(date=date(2026, 7, 27), views=1842, visitors=1206),
        ],
        all_time=None,
        commerce=Commerce(
            orders=14,
            series=[
                DayOrders(date=date(2026, 7, 25), orders=11),
                DayOrders(date=date(2026, 7, 26), orders=9),
                DayOrders(date=date(2026, 7, 27), orders=14),
            ],
        ),
        source="wpcom",
    )


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures"
