from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsp.config import Config
from jsp.models import CommerceCounter, Totals
from jsp.service import (
    parse_all_time,
    parse_commerce,
    parse_site,
    parse_summary,
    parse_visits,
    snapshot_from_client,
)


def load_fixture(directory: Path, name: str) -> dict[str, Any]:
    payload = json.loads((directory / name).read_text())
    assert isinstance(payload, dict)
    return payload


def test_each_endpoint_parser(fixture_dir: Path) -> None:
    site = parse_site(load_fixture(fixture_dir, "site.json"))
    today = parse_summary(load_fixture(fixture_dir, "summary-today.json"))
    visits = parse_visits(load_fixture(fixture_dir, "visits.json"))
    all_time = parse_all_time(load_fixture(fixture_dir, "all-time-unverified.json"))
    commerce = parse_commerce(load_fixture(fixture_dir, "commerce-orders.json"))

    assert site.id == 123456789
    assert today == Totals(1842, 1206, 31, 8)
    assert [point.views for point in visits] == [1888, 1512, 1630, 1842]
    assert all_time is None
    assert commerce == CommerceCounter(orders=14)


def test_snapshot_assembly_uses_site_dates(fixture_dir: Path, tmp_path: Path) -> None:
    class FakeClient:
        def site_info(self) -> dict[str, Any]:
            return load_fixture(fixture_dir, "site.json")

        def summary(self, *, date: str) -> dict[str, Any]:
            filename = (
                "summary-today.json"
                if date == "2026-07-27"
                else "summary-yesterday.json"
            )
            return load_fixture(fixture_dir, filename)

        def visits(self, *, quantity: int) -> dict[str, Any]:
            assert quantity == 30
            return load_fixture(fixture_dir, "visits.json")

        def all_time(self) -> dict[str, Any]:
            return load_fixture(fixture_dir, "all-time-unverified.json")

        def commerce_orders(self, *, date: str) -> dict[str, Any]:
            assert date == "2026-07-27"
            return load_fixture(fixture_dir, "commerce-orders.json")

    config = Config(
        client_id=None,
        client_secret=None,
        site="example.com",
        redirect_uri="http://localhost/callback",
        token_path=tmp_path / "token.json",
        cache_dir=tmp_path,
        series_days=30,
        timezone="Europe/Madrid",
        source="direct",
        source_url=None,
        serve_token=None,
        commerce=True,
    )
    current = datetime(2026, 7, 27, 12, 34, 56, tzinfo=UTC)

    snapshot = snapshot_from_client(
        FakeClient(),  # type: ignore[arg-type]
        config=config,
        now=current,
    )

    assert snapshot.today.views == 1842
    assert snapshot.yesterday.views == 1630
    assert snapshot.fetched_at == current
    assert snapshot.commerce == CommerceCounter(14)
