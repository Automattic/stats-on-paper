"""Build and refresh ``StatsSnapshot`` objects."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from sop.auth import (
    AuthError,
    granted_blog,
    load_access_token,
    load_token_payload,
    token_matches_site,
)
from sop.cache import CacheError, SnapshotCache
from sop.client import (
    AuthenticationError,
    ClientError,
    ResponseError,
    StatsClient,
    TransientClientError,
)
from sop.config import Config
from sop.models import (
    Commerce,
    DayOrders,
    DayPoint,
    SiteRef,
    SnapshotFormatError,
    StatsSnapshot,
    Totals,
    snapshot_from_public_json,
)

LOGGER = logging.getLogger(__name__)


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
        try:
            cached = self.cache.load()
        except CacheError as error:
            # A file an older build wrote, or a half-written one, must not stop
            # every command; the next successful fetch replaces it.
            LOGGER.warning("Ignoring unreadable snapshot cache: %s", error)
            cached = None
        if cached is not None and self.cache.is_fresh(cached, max_age=max_age):
            return cached

        try:
            fresh = self.fetch()
        except AuthenticationError:
            raise
        except (
            ApiShapeError,
            ResponseError,
            SnapshotFormatError,
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
            raise SnapshotUnavailable("SOP_SOURCE=url requires SOP_SOURCE_URL.")
        source_url = config.source_url
        return SnapshotService(
            cache=cache,
            fetch=lambda: _fetch_from_url(source_url, token=config.serve_token),
        )

    if not config.site:
        raise SnapshotUnavailable("Direct stats require WPCOM_SITE.")
    token = load_access_token(config.token_path)
    payload = load_token_payload(config.token_path)
    if payload.get("scope") == "global":
        site = SiteRef(id=None, name=config.site, url=f"https://{config.site}")
    elif payload.get("verified_site") == config.site or token_matches_site(
        payload, config.site
    ):
        site = site_from_token(payload, configured_site=config.site)
    else:
        raise AuthError(
            f"The saved token grants {granted_blog(payload)}, but WPCOM_SITE "
            f"is {config.site}. Run `sop login --manual` to authorize "
            f"{config.site}."
        )
    client = StatsClient(token=token, site=config.site)
    return SnapshotService(
        cache=cache,
        fetch=lambda: snapshot_from_client(client, config=config, site=site),
    )


def site_from_token(payload: Mapping[str, Any], *, configured_site: str) -> SiteRef:
    """Build the site reference from the login payload.

    Reading `GET /sites/{site}` requires the broader `sites` API scope, which
    the least-privilege `stats` token deliberately does not carry. The token
    response already identifies the authorized blog.
    """

    raw_id = payload.get("blog_id")
    site_id: int | None = None
    if isinstance(raw_id, int) and not isinstance(raw_id, bool):
        site_id = raw_id
    elif isinstance(raw_id, str) and raw_id.isdigit():
        site_id = int(raw_id)

    expected = configured_site.strip().lower()
    url = payload.get("blog_url")
    keep_url = False
    if isinstance(url, str) and url:
        host = urlparse(url).hostname or ""
        # A mapped custom domain makes blog_url report the internal
        # *.wordpress.com address; display identity follows the configured
        # site unless the two agree.
        keep_url = host.lower() == expected or (
            expected.isdigit() and str(raw_id) == expected
        )
    if not keep_url or not isinstance(url, str):
        url = f"https://{expected}"
    return SiteRef(id=site_id, name=configured_site, url=url)


def snapshot_from_client(
    client: StatsClient,
    *,
    config: Config,
    site: SiteRef,
    now: datetime | None = None,
) -> StatsSnapshot:
    """Turn thin endpoint responses into the stable model."""

    current = now or datetime.now(UTC)
    site_today = current.astimezone(ZoneInfo(config.timezone)).date()
    site_yesterday = site_today - timedelta(days=1)

    today = parse_summary(client.summary(date=site_today.isoformat()))
    yesterday = parse_summary(client.summary(date=site_yesterday.isoformat()))
    series = parse_visits(client.visits(quantity=config.series_days))
    all_time = parse_all_time(client.all_time())

    commerce: Commerce | None = None
    if config.commerce:
        try:
            commerce = parse_commerce(
                client.commerce_orders(
                    date=site_today.isoformat(), quantity=config.series_days
                ),
                expected_date=site_today,
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
    values = {key: stats[key] for key in keys}
    if any(value < 0 for value in values.values()):
        # Optional and never rendered: a corrupt total is absent, not fatal.
        return None
    return Totals(**values)


def parse_commerce(payload: dict[str, Any], *, expected_date: date) -> Commerce:
    """Parse the daily orders series; today is the row for `expected_date`.

    Rows are sorted by date before that row is taken, mirroring what
    `snapshot_from_client` does for the visits series, so the parser and the
    wire reader agree on ordering. The requested day must be present: this
    endpoint has never been captured live, and taking whatever row came last
    would silently label yesterday's orders as today's.
    """

    fields = payload.get("fields")
    data = payload.get("data")
    if not isinstance(fields, list) or not {"period", "orders"}.issubset(fields):
        raise ApiShapeError("stats/orders fields must include period and orders.")
    if not isinstance(data, list) or not data:
        raise ApiShapeError("stats/orders response is missing data.")
    period_index = fields.index("period")
    orders_index = fields.index("orders")

    rows: list[DayOrders] = []
    for row_index, row in enumerate(data):
        if not isinstance(row, list) or len(row) <= max(period_index, orders_index):
            raise ApiShapeError(
                f"stats/orders data row {row_index} does not match fields."
            )
        raw_period = row[period_index]
        if not isinstance(raw_period, str):
            raise ApiShapeError(f"stats/orders row {row_index} period is not a string.")
        try:
            period = date.fromisoformat(raw_period)
        except ValueError as error:
            raise ApiShapeError(
                f"stats/orders row {row_index} has unknown day {raw_period!r}."
            ) from error
        rows.append(
            DayOrders(
                date=period,
                orders=_row_integer(row[orders_index], "orders", row_index),
            )
        )
    seen: set[date] = set()
    for row in rows:
        if row.date in seen:
            raise ApiShapeError(
                f"stats/orders returned more than one {row.date.isoformat()}."
            )
        seen.add(row.date)
    rows.sort(key=lambda row: row.date)
    if rows[-1].date != expected_date:
        raise ApiShapeError(
            f"stats/orders does not cover {expected_date.isoformat()}; "
            f"its latest day is {rows[-1].date.isoformat()}."
        )
    return Commerce(orders=rows[-1].orders, series=rows)


def _fetch_from_url(url: str, *, token: str | None) -> StatsSnapshot:
    endpoint = f"{url.rstrip('/')}/v1/stats.json"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.get(endpoint, headers=headers, timeout=20)
    if response.status_code in {401, 403}:
        raise AuthenticationError(
            f"The snapshot server rejected SOP_SERVE_TOKEN ({response.status_code})."
        )
    response.raise_for_status()
    return snapshot_from_public_json(response.json())


def _integer(payload: dict[str, Any], key: str, *, endpoint: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiShapeError(f"{endpoint} response is missing integer {key}.")
    if value < 0:
        raise ApiShapeError(f"{endpoint} {key} must not be negative.")
    return value


def _row_integer(value: object, field: str, row_index: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiShapeError(
            f"API data row {row_index} field {field} is not an integer."
        )
    if value < 0:
        raise ApiShapeError(
            f"API data row {row_index} field {field} must not be negative."
        )
    return value
