"""Build and refresh ``StatsSnapshot`` objects."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

from jsp.auth import load_access_token
from jsp.cache import SnapshotCache
from jsp.client import (
    AuthenticationError,
    ClientError,
    ResponseError,
    StatsClient,
    TransientClientError,
)
from jsp.config import Config
from jsp.models import (
    CommerceCounter,
    DayPoint,
    SiteRef,
    StatsSnapshot,
    Totals,
    snapshot_from_public_json,
)


class SnapshotUnavailable(RuntimeError):
    """No fresh or cached snapshot can be returned."""


class ApiShapeError(RuntimeError):
    """A live API response contradicted the recorded contract."""


class SnapshotService:
    """Cache policy around a callable that performs I/O."""

    def __init__(
        self,
        *,
        cache: SnapshotCache,
        fetch: Callable[[], StatsSnapshot],
    ) -> None:
        self.cache = cache
        self.fetch = fetch

    def get_snapshot(self, *, max_age: float = 0) -> StatsSnapshot:
        cached = self.cache.load()
        if cached is not None and self.cache.is_fresh(cached, max_age=max_age):
            return cached

        try:
            fresh = self.fetch()
        except AuthenticationError:
            raise
        except (
            ResponseError,
            TransientClientError,
            requests.RequestException,
        ) as error:
            if cached is not None:
                return cached
            raise SnapshotUnavailable(
                f"Could not fetch stats and no cached snapshot exists: {error}"
            ) from error

        self.cache.save(fresh)
        return fresh


def build_service(config: Config) -> SnapshotService:
    cache = SnapshotCache(config.cache_dir)
    if config.source == "url":
        if not config.source_url:
            raise SnapshotUnavailable("JSP_SOURCE=url requires JSP_SOURCE_URL.")
        source_url = config.source_url
        return SnapshotService(
            cache=cache,
            fetch=lambda: _fetch_from_url(source_url, token=config.serve_token),
        )

    if not config.site:
        raise SnapshotUnavailable("Direct stats require WPCOM_SITE.")
    token = load_access_token(config.token_path)
    client = StatsClient(token=token, site=config.site)
    return SnapshotService(
        cache=cache,
        fetch=lambda: snapshot_from_client(client, config=config),
    )


def snapshot_from_client(
    client: StatsClient,
    *,
    config: Config,
    now: datetime | None = None,
) -> StatsSnapshot:
    """Turn thin endpoint responses into the stable model."""

    current = now or datetime.now(UTC)
    site_today = current.astimezone(ZoneInfo(config.timezone)).date()
    site_yesterday = site_today - timedelta(days=1)

    site = parse_site(client.site_info())
    today = parse_summary(client.summary(date=site_today.isoformat()))
    yesterday = parse_summary(client.summary(date=site_yesterday.isoformat()))
    series = parse_visits(client.visits(quantity=config.series_days))
    all_time = parse_all_time(client.all_time())

    commerce: CommerceCounter | None = None
    if config.commerce:
        try:
            commerce = parse_commerce(
                client.commerce_orders(date=site_today.isoformat())
            )
        except AuthenticationError:
            raise
        except (ClientError, ApiShapeError):
            # Store-less and unsupported sites intentionally omit the counter.
            commerce = None

    return StatsSnapshot(
        schema=1,
        site=site,
        fetched_at=current.astimezone(UTC),
        today=today,
        yesterday=yesterday,
        series=sorted(series, key=lambda point: point.date),
        all_time=all_time,
        commerce=commerce,
        source="wpcom",
    )


def parse_site(payload: dict[str, Any]) -> SiteRef:
    raw_id = payload.get("ID")
    if isinstance(raw_id, bool) or not isinstance(raw_id, int):
        raise ApiShapeError("Site response is missing integer ID.")
    return SiteRef(
        id=raw_id,
        name=_string(payload, "name", endpoint="site"),
        url=_string(payload, "URL", endpoint="site"),
    )


def parse_summary(payload: dict[str, Any]) -> Totals:
    return Totals(
        views=_integer(payload, "views", endpoint="stats/summary"),
        visitors=_integer(payload, "visitors", endpoint="stats/summary"),
        likes=_integer(payload, "likes", endpoint="stats/summary"),
        comments=_integer(payload, "comments", endpoint="stats/summary"),
    )


def parse_visits(payload: dict[str, Any]) -> list[DayPoint]:
    fields = payload.get("fields")
    data = payload.get("data")
    if not isinstance(fields, list) or not all(
        isinstance(field, str) for field in fields
    ):
        raise ApiShapeError("stats/visits response is missing string fields.")
    if not isinstance(data, list):
        raise ApiShapeError("stats/visits response is missing data.")
    required = {"period", "views", "visitors"}
    if not required.issubset(fields):
        raise ApiShapeError(
            "stats/visits fields must include period, views, and visitors."
        )
    indexes = {field: fields.index(field) for field in required}

    points: list[DayPoint] = []
    for row_index, row in enumerate(data):
        if not isinstance(row, list):
            raise ApiShapeError(f"stats/visits data row {row_index} is not an array.")
        try:
            raw_period = row[indexes["period"]]
            raw_views = row[indexes["views"]]
            raw_visitors = row[indexes["visitors"]]
        except IndexError as error:
            raise ApiShapeError(
                f"stats/visits data row {row_index} is shorter than fields."
            ) from error
        if not isinstance(raw_period, str):
            raise ApiShapeError(f"stats/visits row {row_index} period is not a string.")
        try:
            period = date.fromisoformat(raw_period.replace("W", ""))
        except ValueError as error:
            raise ApiShapeError(
                f"stats/visits row {row_index} has unknown day {raw_period!r}."
            ) from error
        points.append(
            DayPoint(
                date=period,
                views=_row_integer(raw_views, "views", row_index),
                visitors=_row_integer(raw_visitors, "visitors", row_index),
            )
        )
    return points


def parse_all_time(payload: dict[str, Any]) -> Totals | None:
    """Parse only the documented direct mapping; unknown shapes stay absent."""

    stats = payload.get("stats")
    if not isinstance(stats, dict):
        return None
    keys = ("views", "visitors", "likes", "comments")
    if not all(
        isinstance(stats.get(key), int) and not isinstance(stats.get(key), bool)
        for key in keys
    ):
        return None
    return Totals(
        views=stats["views"],
        visitors=stats["visitors"],
        likes=stats["likes"],
        comments=stats["comments"],
    )


def parse_commerce(payload: dict[str, Any]) -> CommerceCounter:
    fields = payload.get("fields")
    data = payload.get("data")
    if not isinstance(fields, list) or "orders" not in fields:
        raise ApiShapeError("stats/orders response is missing orders field.")
    if not isinstance(data, list) or not data:
        raise ApiShapeError("stats/orders response is missing data.")
    orders_index = fields.index("orders")
    last_row = data[-1]
    if not isinstance(last_row, list) or len(last_row) <= orders_index:
        raise ApiShapeError("stats/orders data does not match fields.")
    return CommerceCounter(
        orders=_row_integer(last_row[orders_index], "orders", len(data) - 1)
    )


def _fetch_from_url(url: str, *, token: str | None) -> StatsSnapshot:
    endpoint = f"{url.rstrip('/')}/v1/stats.json"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.get(endpoint, headers=headers, timeout=20)
    if response.status_code in {401, 403}:
        raise AuthenticationError(
            f"The snapshot server rejected JSP_SERVE_TOKEN ({response.status_code})."
        )
    response.raise_for_status()
    return snapshot_from_public_json(response.json())


def _integer(payload: dict[str, Any], key: str, *, endpoint: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiShapeError(f"{endpoint} response is missing integer {key}.")
    return value


def _string(payload: dict[str, Any], key: str, *, endpoint: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ApiShapeError(f"{endpoint} response is missing string {key}.")
    return value


def _row_integer(value: object, field: str, row_index: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiShapeError(
            f"API data row {row_index} field {field} is not an integer."
        )
    return value
