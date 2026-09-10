"""Thin WordPress.com Stats API client."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

import requests

BASE_URL = "https://public-api.wordpress.com/rest"
API_VERSION = "v1.1"
API_BASE_URL = f"{BASE_URL}/{API_VERSION}"
API_V1_BASE_URL = f"{BASE_URL}/v1"
WPCOM_V2_BASE_URL = "https://public-api.wordpress.com/wpcom/v2"


class ClientError(RuntimeError):
    """A WordPress.com request failed."""


class AuthenticationError(ClientError):
    """The access token is invalid or lacks permission."""


class TransientClientError(ClientError):
    """A timeout, connection problem, or server error may succeed later."""


class ResponseError(ClientError):
    """A non-retryable API response was returned."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class StatsClient:
    """One readable method per WordPress.com endpoint."""

    def __init__(
        self,
        *,
        token: str,
        site: str,
        session: requests.Session | None = None,
        timeout: float = 20,
    ) -> None:
        self.site = quote(site, safe="")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def summary(self, *, date: str) -> dict[str, Any]:
        return self._get(
            f"{API_BASE_URL}/sites/{self.site}/stats/summary",
            params={"period": "day", "num": 1, "date": date},
        )

    def visits(self, *, quantity: int) -> dict[str, Any]:
        # The visits endpoint must stay on API v1: WordPress.com rejects the
        # v1.1 form for tokens that carry only the narrow `stats` scope.
        return self._get(
            f"{API_V1_BASE_URL}/sites/{self.site}/stats/visits",
            params={
                "unit": "day",
                "quantity": quantity,
                "stat_fields": "views,visitors",
            },
        )

    def all_time(self) -> dict[str, Any]:
        return self._get(f"{API_BASE_URL}/sites/{self.site}/stats")

    def commerce_orders(self, *, date: str, quantity: int) -> dict[str, Any]:
        return self._get(
            f"{WPCOM_V2_BASE_URL}/sites/{self.site}/stats/orders",
            params={
                "unit": "day",
                "quantity": quantity,
                "date": date,
                "stat_fields": "orders",
            },
        )

    def _get(
        self, url: str, *, params: dict[str, str | int] | None = None
    ) -> dict[str, Any]:
        attempts = 3
        last_error: BaseException | None = None

        for attempt in range(attempts):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except (requests.Timeout, requests.ConnectionError) as error:
                last_error = error
                if attempt + 1 < attempts:
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise TransientClientError(
                    f"WordPress.com request failed after {attempts} attempts: {error}"
                ) from error
            except requests.RequestException as error:
                raise ResponseError(
                    f"WordPress.com request could not be sent: {error}",
                    status_code=0,
                ) from error

            if response.status_code in {401, 403}:
                raise AuthenticationError(
                    "WordPress.com rejected the token "
                    f"({response.status_code}). Run `jsp login --manual` again."
                )

            if response.status_code >= 500:
                last_error = RuntimeError(
                    f"WordPress.com returned {response.status_code}"
                )
                if attempt + 1 < attempts:
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise TransientClientError(str(last_error))

            if response.status_code >= 400:
                raise ResponseError(
                    f"WordPress.com returned {response.status_code}: "
                    f"{response.text[:200]}",
                    status_code=response.status_code,
                )

            try:
                payload = response.json()
            except requests.JSONDecodeError as error:
                raise ResponseError(
                    "WordPress.com returned invalid JSON.", status_code=200
                ) from error
            if not isinstance(payload, dict):
                raise ResponseError(
                    "WordPress.com returned JSON that is not an object.",
                    status_code=200,
                )
            return payload

        raise TransientClientError(f"WordPress.com request failed: {last_error}")
