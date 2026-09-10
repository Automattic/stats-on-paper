"""Human-readable numbers, labels and identity strings."""

from __future__ import annotations

from collections.abc import Sized
from datetime import UTC
from urllib.parse import urlsplit

from jsp.models import StatsSnapshot

AGED_AFTER_SECONDS = 2 * 60 * 60


def compact_count(value: int) -> str:
    for divisor, suffix in (
        (1_000_000_000, "b"),
        (1_000_000, "m"),
        (1_000, "k"),
    ):
        if abs(value) >= divisor:
            scaled = value / divisor
            precision = 1 if abs(scaled) < 100 else 0
            formatted = f"{scaled:.{precision}f}"
            if "." in formatted:
                formatted = formatted.rstrip("0").rstrip(".")
            return formatted + suffix
    return f"{value:,}"


def safe_ratio(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "—"
    return f"{numerator / denominator:.1f}×"


def trend_period_label(points: Sized, *, compact: bool) -> str:
    if not points:
        return "NO TREND" if compact else "TREND"
    # Count the days drawn, not the calendar span: a series with gaps is drawn
    # one bar per point, and the caption must agree with the rail's DAYS SHOWN.
    days = len(points)
    unit = "DAY" if days == 1 else "DAYS"
    return f"{days} {unit}" if compact else f"LAST {days} {unit}"


def updated_label(snapshot: StatsSnapshot, age_seconds: int, *, compact: bool) -> str:
    timestamp = snapshot.fetched_at.astimezone(UTC)
    if age_seconds > AGED_AFTER_SECONDS:
        if compact:
            return f"{human_age(age_seconds)} old"
        return f"Refresh delayed · {human_age(age_seconds)} old"
    if compact:
        return f"{timestamp:%H:%M} UTC"
    return f"Updated {timestamp:%H:%M} UTC · {timestamp.day} {timestamp:%b}"


def human_age(seconds: int) -> str:
    if seconds < 120:
        return f"{seconds} sec"
    if seconds < 7200:
        return f"{seconds // 60} min"
    if seconds < 172800:
        return f"{seconds // 3600} hr"
    return f"{seconds // 86400} days"


def site_domain(url: str, *, fallback: str = "") -> str:
    parsed = urlsplit(url if "://" in url else f"//{url}")
    domain = parsed.hostname or parsed.path.split("/", 1)[0]
    domain = domain.removeprefix("www.").rstrip(".") or fallback
    try:
        return domain.encode("ascii").decode("idna")
    except (UnicodeError, UnicodeDecodeError):
        return domain


def truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"
