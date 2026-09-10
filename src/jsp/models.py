"""Stable data models at the I/O-to-rendering seam."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any


class SnapshotFormatError(ValueError):
    """A snapshot JSON object does not match schema 1."""


@dataclass(frozen=True)
class Totals:
    views: int
    visitors: int
    likes: int
    comments: int


@dataclass(frozen=True)
class DayPoint:
    date: date
    views: int
    visitors: int


@dataclass(frozen=True)
class SiteRef:
    id: int | None
    name: str
    url: str


@dataclass(frozen=True)
class DayOrders:
    date: date
    orders: int


@dataclass(frozen=True)
class Commerce:
    """Store orders: today's count and the daily series behind it.

    `orders` is today's figure and equals `series[-1].orders` whenever the
    series is present. It stays on the wire because a reader older than the
    series requires it, and a writer older than the series sends only it.
    """

    orders: int
    series: list[DayOrders]


@dataclass(frozen=True)
class StatsSnapshot:
    schema: int
    site: SiteRef
    fetched_at: datetime
    today: Totals
    yesterday: Totals
    series: list[DayPoint]
    all_time: Totals | None
    commerce: Commerce | None
    source: str

    def to_public_json(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Return the root-level TRMNL wire contract."""

        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        fetched_at = self.fetched_at.astimezone(UTC)
        age_seconds = max(
            0,
            int((current.astimezone(UTC) - fetched_at).total_seconds()),
        )

        # Insertion order is intentional: schema is the first wire key.
        return {
            "schema": self.schema,
            "site": {
                "id": self.site.id,
                "name": self.site.name,
                "url": self.site.url,
            },
            "fetched_at": _format_datetime(fetched_at),
            "age_seconds": age_seconds,
            "today": _totals_json(self.today),
            "yesterday": _totals_json(self.yesterday),
            "series": [
                {
                    "date": point.date.isoformat(),
                    "views": point.views,
                    "visitors": point.visitors,
                }
                for point in self.series
            ],
            "all_time": (
                _totals_json(self.all_time) if self.all_time is not None else None
            ),
            "commerce": (
                {
                    "orders": self.commerce.orders,
                    "series": [
                        {"date": row.date.isoformat(), "orders": row.orders}
                        for row in self.commerce.series
                    ],
                }
                if self.commerce is not None
                else None
            ),
            "source": self.source,
        }


def snapshot_from_public_json(payload: object) -> StatsSnapshot:
    """Parse schema-1 public/cache JSON into a snapshot."""

    root = _mapping(payload, "snapshot")
    schema = _integer(root.get("schema"), "schema")
    if schema != 1:
        raise SnapshotFormatError(
            f"Unsupported snapshot schema {schema}; this version supports schema 1."
        )

    site_data = _mapping(root.get("site"), "site")
    site_id_raw = site_data.get("id")
    site_id = None if site_id_raw is None else _integer(site_id_raw, "site.id")
    site = SiteRef(
        id=site_id,
        name=_string(site_data.get("name"), "site.name"),
        url=_string(site_data.get("url"), "site.url"),
    )

    fetched_at = _datetime(root.get("fetched_at"), "fetched_at")
    today = _totals(root.get("today"), "today")
    yesterday = _totals(root.get("yesterday"), "yesterday")

    series_raw = root.get("series")
    if not isinstance(series_raw, list):
        raise SnapshotFormatError("series must be an array")
    series: list[DayPoint] = []
    for index, raw_point in enumerate(series_raw):
        point = _mapping(raw_point, f"series[{index}]")
        point_date = _date(point.get("date"), f"series[{index}].date")
        series.append(
            DayPoint(
                date=point_date,
                views=_count(point.get("views"), f"series[{index}].views"),
                visitors=_count(point.get("visitors"), f"series[{index}].visitors"),
            )
        )

    all_time_raw = root.get("all_time")
    all_time = None if all_time_raw is None else _totals(all_time_raw, "all_time")

    commerce_raw = root.get("commerce")
    commerce = None
    if commerce_raw is not None:
        commerce_data = _mapping(commerce_raw, "commerce")
        commerce = Commerce(
            orders=_count(commerce_data.get("orders"), "commerce.orders"),
            # A writer older than the series sends only `orders`.
            series=_order_series(commerce_data.get("series", [])),
        )
        if commerce.series and commerce.series[-1].orders != commerce.orders:
            # Today is stated twice on the wire; the view reads one and the
            # chart the other, so they may not disagree.
            raise SnapshotFormatError(
                f"commerce.orders must equal the last day of commerce.series "
                f"({commerce.orders} != {commerce.series[-1].orders})"
            )

    _reject_repeated_days([point.date for point in series], "series")
    return StatsSnapshot(
        schema=schema,
        site=site,
        fetched_at=fetched_at,
        today=today,
        yesterday=yesterday,
        series=sorted(series, key=lambda point: point.date),
        all_time=all_time,
        commerce=commerce,
        source=_string(root.get("source"), "source"),
    )


def _order_series(value: object) -> list[DayOrders]:
    if not isinstance(value, list):
        raise SnapshotFormatError("commerce.series must be an array")
    rows = [
        DayOrders(
            date=_date(
                _mapping(row, f"commerce.series[{index}]").get("date"),
                f"commerce.series[{index}].date",
            ),
            orders=_count(
                _mapping(row, f"commerce.series[{index}]").get("orders"),
                f"commerce.series[{index}].orders",
            ),
        )
        for index, row in enumerate(value)
    ]
    _reject_repeated_days([row.date for row in rows], "commerce.series")
    return sorted(rows, key=lambda row: row.date)


def _reject_repeated_days(dates: list[date], name: str) -> None:
    """One row per day: the renderer draws a bar per row and counts rows.

    A repeated date would be drawn twice and captioned as two days.
    """

    seen: set[date] = set()
    for day in dates:
        if day in seen:
            raise SnapshotFormatError(f"{name} has more than one {day.isoformat()}")
        seen.add(day)


def _date(value: object, name: str) -> date:
    try:
        return date.fromisoformat(_string(value, name))
    except ValueError as error:
        raise SnapshotFormatError(f"{name} must be YYYY-MM-DD") from error


def _totals_json(totals: Totals) -> dict[str, int]:
    return {
        "views": totals.views,
        "visitors": totals.visitors,
        "likes": totals.likes,
        "comments": totals.comments,
    }


def _totals(value: object, name: str) -> Totals:
    data = _mapping(value, name)
    return Totals(
        views=_count(data.get("views"), f"{name}.views"),
        visitors=_count(data.get("visitors"), f"{name}.visitors"),
        likes=_count(data.get("likes"), f"{name}.likes"),
        comments=_count(data.get("comments"), f"{name}.comments"),
    )


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SnapshotFormatError(f"{name} must be an object")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SnapshotFormatError(f"{name} must be an integer")
    return value


def _count(value: object, name: str) -> int:
    """An audience count is a magnitude; a negative one is corrupt input.

    Rejecting it here keeps the renderer from ever having to decide what a
    negative day looks like.
    """

    count = _integer(value, name)
    if count < 0:
        raise SnapshotFormatError(f"{name} must not be negative")
    return count


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise SnapshotFormatError(f"{name} must be a string")
    return value


def _datetime(value: object, name: str) -> datetime:
    raw = _string(value, name)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise SnapshotFormatError(f"{name} must be an ISO 8601 timestamp") from error
    if parsed.tzinfo is None:
        raise SnapshotFormatError(f"{name} must include a timezone")
    return parsed.astimezone(UTC)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
