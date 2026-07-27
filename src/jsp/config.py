"""Environment-based configuration.

The renderer never imports this module. Configuration belongs above the
``StatsSnapshot`` seam.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


class ConfigError(ValueError):
    """A configuration value is missing or invalid."""


@dataclass(frozen=True)
class Config:
    """Configuration read from environment variables and ``.env``."""

    client_id: str | None
    client_secret: str | None
    site: str | None
    redirect_uri: str
    token_path: Path
    cache_dir: Path
    series_days: int
    timezone: str
    source: Literal["direct", "url"]
    source_url: str | None
    serve_token: str | None
    commerce: bool


_ENV_FOR_FIELD = {
    "client_id": "WPCOM_CLIENT_ID",
    "client_secret": "WPCOM_CLIENT_SECRET",
    "site": "WPCOM_SITE",
    "source_url": "JSP_SOURCE_URL",
    "serve_token": "JSP_SERVE_TOKEN",
}


def _optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(
            f"{name} must be a whole number; got {raw!r}. See .env.example."
        ) from error
    if value < 1:
        raise ConfigError(f"{name} must be at least 1. See .env.example.")
    return value


def _boolean(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be true or false; got {raw!r}. See .env.example.")


def load_config(*, required: tuple[str, ...] = ()) -> Config:
    """Load configuration and validate only the values a command needs."""

    load_dotenv()

    source_value = os.getenv("JSP_SOURCE", "direct").strip().lower()
    if source_value not in {"direct", "url"}:
        raise ConfigError("JSP_SOURCE must be 'direct' or 'url'. See .env.example.")
    source: Literal["direct", "url"] = "url" if source_value == "url" else "direct"

    timezone = os.getenv("JSP_TZ", "Europe/Madrid").strip()
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ConfigError(
            f"JSP_TZ names an unknown timezone: {timezone!r}. See .env.example."
        ) from error

    config = Config(
        client_id=_optional("WPCOM_CLIENT_ID"),
        client_secret=_optional("WPCOM_CLIENT_SECRET"),
        site=_optional("WPCOM_SITE"),
        redirect_uri=os.getenv(
            "WPCOM_REDIRECT_URI", "http://localhost/callback"
        ).strip(),
        token_path=Path.home() / ".config" / "jsp" / "token.json",
        cache_dir=Path(
            os.getenv("JSP_CACHE_DIR", str(Path.home() / ".cache" / "jsp"))
        ).expanduser(),
        series_days=_positive_int("JSP_SERIES_DAYS", 30),
        timezone=timezone,
        source=source,
        source_url=_optional("JSP_SOURCE_URL"),
        serve_token=_optional("JSP_SERVE_TOKEN"),
        commerce=_boolean("JSP_COMMERCE"),
    )

    required_fields = list(required)
    if source == "url" and "source_url" not in required_fields:
        required_fields.append("source_url")

    for field in required_fields:
        if field not in _ENV_FOR_FIELD:
            raise ValueError(f"Unknown required configuration field: {field}")
        if not getattr(config, field):
            env_name = _ENV_FOR_FIELD[field]
            raise ConfigError(
                f"Missing {env_name}. Copy .env.example to .env, set {env_name}, "
                "and try again."
            )

    return config
