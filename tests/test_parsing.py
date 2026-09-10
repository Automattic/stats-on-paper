from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from sop.config import Config
from sop.models import Commerce, DayOrders, SiteRef, Totals
from sop.service import (
    ApiShapeError,
    parse_all_time,
    parse_commerce,
    parse_summary,
    parse_visits,
    site_from_token,
    snapshot_from_client,
)


def load_fixture(directory: Path, name: str) -> dict[str, Any]:
    payload = json.loads((directory / name).read_text())
    assert isinstance(payload, dict)
    return payload


def test_each_endpoint_parser(fixture_dir: Path) -> None:
    today = parse_summary(load_fixture(fixture_dir, "summary-today.json"))
    visits = parse_visits(load_fixture(fixture_dir, "visits.json"))
    all_time = parse_all_time(load_fixture(fixture_dir, "all-time-unverified.json"))
    commerce = parse_commerce(
        load_fixture(fixture_dir, "commerce-orders.json"),
        expected_date=date(2026, 7, 27),
    )

    assert today == Totals(1842, 1206, 31, 8)
    assert [point.views for point in visits] == [1888, 1512, 1630, 1842]
    assert all_time is None
    assert commerce == Commerce(
        orders=14,
        series=[
            DayOrders(date=date(2026, 7, 26), orders=9),
            DayOrders(date=date(2026, 7, 27), orders=14),
        ],
    )


def test_site_from_token_reads_the_granted_blog() -> None:
    """The token response names the blog; a string id is accepted, and a mapped
    domain keeps the configured name rather than the internal *.wordpress.com."""
    assert site_from_token(
        {"blog_id": "123456789", "blog_url": "https://northstar.test"},
        configured_site="northstar.test",
    ) == SiteRef(id=123456789, name="northstar.test", url="https://northstar.test")

    assert site_from_token(
        {"blog_id": "9288856", "blog_url": "http://internal.wordpress.com"},
        configured_site="pretty.example.com",
    ) == SiteRef(
        id=9288856, name="pretty.example.com", url="https://pretty.example.com"
    )


def test_snapshot_assembly_uses_site_dates(fixture_dir: Path, tmp_path: Path) -> None:
    class FakeClient:
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

        def commerce_orders(self, *, date: str, quantity: int) -> dict[str, Any]:
            assert date == "2026-07-27"
            assert quantity == 30
            return load_fixture(fixture_dir, "commerce-orders.json")

    config = Config(
        client_id=None,
        client_secret=None,
        site="example.com",
        oauth_scope="stats",
        redirect_uri="http://localhost/callback",
        token_path=tmp_path / "token.json",
        cache_dir=tmp_path,
        series_days=30,
        poll_interval_seconds=600,
        timezone="Europe/Madrid",
        source="direct",
        source_url=None,
        serve_token=None,
        commerce=True,
        view="stats",
        panel=None,
    )
    current = datetime(2026, 7, 27, 12, 34, 56, tzinfo=UTC)

    snapshot = snapshot_from_client(
        FakeClient(),  # type: ignore[arg-type]
        config=config,
        site=SiteRef(id=123456789, name="example.com", url="https://example.com"),
        now=current,
    )

    assert snapshot.site.id == 123456789
    assert snapshot.today.views == 1842
    assert snapshot.yesterday.views == 1630
    assert snapshot.fetched_at == current
    assert snapshot.commerce.orders == 14


def test_parsers_reject_negative_counts(fixture_dir: Path) -> None:
    """Required figures fail loudly; the optional all-time total is simply
    absent, because it is never rendered and must not sink the snapshot."""
    summary = load_fixture(fixture_dir, "summary-today.json")
    summary["visitors"] = -1
    with pytest.raises(ApiShapeError, match="visitors must not be negative"):
        parse_summary(summary)

    visits = load_fixture(fixture_dir, "visits.json")
    visits["data"][0][visits["fields"].index("views")] = -3
    with pytest.raises(ApiShapeError, match="row 0 field views must not be negative"):
        parse_visits(visits)

    all_time = {"stats": {"views": 10, "visitors": 5, "likes": -1, "comments": 0}}
    assert parse_all_time(all_time) is None


def test_commerce_parser_enforces_its_contract() -> None:
    """Today is the row for the requested day, found after sorting.

    The orders endpoint has never been captured live, so a response that omits
    the requested day or repeats a day is a contract violation, not something
    to paper over by taking whatever row came last.
    """
    unsorted = {
        "fields": ["period", "orders"],
        "data": [["2026-07-27", 14], ["2026-07-26", 9]],
    }
    commerce = parse_commerce(unsorted, expected_date=date(2026, 7, 27))
    assert commerce.orders == 14
    assert [row.orders for row in commerce.series] == [9, 14]

    missing_today = {"fields": ["period", "orders"], "data": [["2026-07-26", 9]]}
    with pytest.raises(ApiShapeError, match="does not cover 2026-07-27"):
        parse_commerce(missing_today, expected_date=date(2026, 7, 27))

    repeated = {
        "fields": ["period", "orders"],
        "data": [["2026-07-26", 2], ["2026-07-26", 8], ["2026-07-27", 7]],
    }
    with pytest.raises(ApiShapeError, match="more than one 2026-07-26"):
        parse_commerce(repeated, expected_date=date(2026, 7, 27))
