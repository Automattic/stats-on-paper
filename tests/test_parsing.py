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


def test_commerce_parser_orders_rows_by_date() -> None:
    """Today is the last row, so the rows must be sorted before it is taken."""
    payload = {
        "fields": ["period", "orders"],
        "data": [["2026-07-27", 14], ["2026-07-26", 9]],
    }

    commerce = parse_commerce(payload, expected_date=date(2026, 7, 27))

    assert commerce.orders == 14
    assert [row.orders for row in commerce.series] == [9, 14]


def test_site_from_token_accepts_string_blog_id() -> None:
    site = site_from_token(
        {"blog_id": "123456789", "blog_url": "https://northstar.test"},
        configured_site="northstar.test",
    )

    assert site == SiteRef(
        id=123456789, name="northstar.test", url="https://northstar.test"
    )


def test_site_from_token_prefers_configured_domain_for_mapped_blogs() -> None:
    site = site_from_token(
        {"blog_id": "9288856", "blog_url": "http://internal.wordpress.com"},
        configured_site="pretty.example.com",
    )

    assert site == SiteRef(
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


def test_summary_parser_rejects_negative_counts(fixture_dir: Path) -> None:
    payload = load_fixture(fixture_dir, "summary-today.json")
    payload["visitors"] = -1

    with pytest.raises(ApiShapeError, match="visitors must not be negative"):
        parse_summary(payload)


def test_visits_parser_rejects_negative_counts(fixture_dir: Path) -> None:
    payload = load_fixture(fixture_dir, "visits.json")
    payload["data"][0][payload["fields"].index("views")] = -3

    with pytest.raises(ApiShapeError, match="row 0 field views must not be negative"):
        parse_visits(payload)


def test_all_time_parser_omits_negative_counts() -> None:
    """All-time totals are optional and never rendered; a bad value is absent,
    not fatal to the whole snapshot."""
    payload = {"stats": {"views": 10, "visitors": 5, "likes": -1, "comments": 0}}

    assert parse_all_time(payload) is None


def test_commerce_parser_requires_the_day_it_asked_for() -> None:
    """Today's figure must be today's row, not whatever row came last.

    The orders endpoint has never been captured live, so a response that omits
    the requested day is a contract violation rather than a fallback.
    """
    payload = {"fields": ["period", "orders"], "data": [["2026-07-26", 9]]}

    with pytest.raises(ApiShapeError, match="does not cover 2026-07-27"):
        parse_commerce(payload, expected_date=date(2026, 7, 27))


def test_commerce_parser_rejects_a_repeated_day() -> None:
    payload = {
        "fields": ["period", "orders"],
        "data": [["2026-07-26", 2], ["2026-07-26", 8], ["2026-07-27", 7]],
    }

    with pytest.raises(ApiShapeError, match="more than one 2026-07-26"):
        parse_commerce(payload, expected_date=date(2026, 7, 27))
