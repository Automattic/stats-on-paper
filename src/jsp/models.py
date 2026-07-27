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
class CommerceCounter:
    orders: int


@dataclass(frozen=True)
class StatsSnapshot:
    schema: int
    site: SiteRef
    fetched_at: datetime
    today: Totals
    yesterday: Totals
    series: list[DayPoint]
    all_time: Totals | None
    commerce: CommerceCounter | None
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
                {"orders": self.commerce.orders} if self.commerce is not None else None
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
        try:
            point_date = date.fromisoformat(
                _string(point.get("date"), f"series[{index}].date")
            )
        except ValueError as error:
            raise SnapshotFormatError(
                f"series[{index}].date must be YYYY-MM-DD"
            ) from error
        series.append(
            DayPoint(
                date=point_date,
                views=_integer(point.get("views"), f"series[{index}].views"),
                visitors=_integer(point.get("visitors"), f"series[{index}].visitors"),
            )
        )

    all_time_raw = root.get("all_time")
    all_time = None if all_time_raw is None else _totals(all_time_raw, "all_time")

    commerce_raw = root.get("commerce")
    commerce = None
    if commerce_raw is not None:
        commerce_data = _mapping(commerce_raw, "commerce")
        commerce = CommerceCounter(
            orders=_integer(commerce_data.get("orders"), "commerce.orders")
        )

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
        views=_integer(data.get("views"), f"{name}.views"),
        visitors=_integer(data.get("visitors"), f"{name}.visitors"),
        likes=_integer(data.get("likes"), f"{name}.likes"),
        comments=_integer(data.get("comments"), f"{name}.comments"),
    )


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SnapshotFormatError(f"{name} must be an object")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SnapshotFormatError(f"{name} must be an integer")
    return value


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
