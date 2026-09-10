"""WordPress.com OAuth login and token storage."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import webbrowser
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse

import requests

from jsp.config import Config

AUTHORIZE_URL = "https://public-api.wordpress.com/oauth2/authorize"
TOKEN_URL = "https://public-api.wordpress.com/oauth2/token"
STATS_PROBE_URL = (
    "https://public-api.wordpress.com/rest/v1.1/sites/{site}/stats/summary"
)


class AuthError(RuntimeError):
    """Login or token storage failed."""


def load_token_payload(path: Path) -> dict[str, Any]:
    """Read the private token file as a JSON object."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise AuthError(
            f"No token found at {path}. Run `jsp login --manual` first."
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise AuthError(f"Could not read token file {path}: {error}") from error
    if not isinstance(payload, dict):
        raise AuthError(f"Token file {path} is not a JSON object.")
    return payload


def load_access_token(path: Path) -> str:
    """Read the access token from the private token file."""

    payload = load_token_payload(path)
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise AuthError(f"Token file {path} does not contain an access_token.")
    return token


def save_token(payload: Mapping[str, Any], path: Path) -> None:
    """Atomically write a token file with mode ``0600``."""

    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise AuthError("WordPress.com token response did not contain access_token.")

    allowed = {
        "access_token",
        "blog_id",
        "blog_url",
        "expires_in",
        "refresh_token",
        "scope",
        "token_type",
        "verified_site",
    }
    safe_payload = {key: payload[key] for key in allowed if key in payload}

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".token-",
            suffix=".json",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(safe_payload, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
        os.chmod(path, 0o600)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def token_matches_site(payload: Mapping[str, Any], site: str) -> bool:
    """Whether a token payload grants the configured site.

    The authorization screen's `blog` parameter is a request, not a
    guarantee: the user can approve a different blog, and the token response
    names the blog that was actually granted. Matches on the numeric blog id
    or the blog URL hostname; a mapped custom domain can make the hostname
    comparison fail for the right blog, so callers must name the granted
    blog in their error message.
    """

    expected = site.strip().lower()
    if expected.isdigit() and str(payload.get("blog_id")) == expected:
        return True
    url = payload.get("blog_url")
    if isinstance(url, str):
        host = urlparse(url).hostname
        if host and host.lower() == expected:
            return True
    return False


def granted_blog(payload: Mapping[str, Any]) -> str:
    """Name the blog a token payload was granted for, for error messages."""

    blog = payload.get("blog_url") or payload.get("blog_id")
    return str(blog) if blog else "an unknown blog"


def build_authorize_url(config: Config, *, redirect_uri: str, state: str) -> str:
    """Build the authorization URL for the configured scope.

    `stats` requests a least-privilege single-site token and names the blog;
    `global` requests one token covering every site the account can access,
    so no blog is named.
    """

    if not config.client_id:
        raise AuthError("OAuth login requires WPCOM_CLIENT_ID.")
    query: dict[str, str] = {
        "client_id": config.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": config.oauth_scope,
        "state": state,
    }
    if config.oauth_scope != "global":
        if not config.site:
            raise AuthError("OAuth login requires WPCOM_SITE for a stats token.")
        query["blog"] = config.site
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


def can_read_stats(payload: Mapping[str, Any], site: str) -> bool:
    """Ask WordPress.com whether a token can read a site's stats.

    A mapped custom domain makes the token's `blog_url` report the internal
    ``*.wordpress.com`` address, so a textual comparison can reject a correct
    grant. The API resolves domain aliases itself; its answer is the truth.
    """

    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        return False
    try:
        response = requests.get(
            STATS_PROBE_URL.format(site=quote(site, safe="")),
            params={"period": "day", "num": "1"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
    except requests.RequestException as error:
        raise AuthError(f"Could not verify stats access for {site}: {error}") from error
    return response.status_code == 200


def exchange_code(config: Config, *, code: str, redirect_uri: str) -> dict[str, Any]:
    """Exchange an authorization code for a token."""

    if not config.client_id or not config.client_secret:
        raise AuthError("OAuth login requires WPCOM_CLIENT_ID and WPCOM_CLIENT_SECRET.")
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        detail = ""
        if error.response is not None:
            detail = f" ({error.response.status_code}: {error.response.text[:200]})"
        raise AuthError(f"Token exchange failed{detail}") from error

    payload = response.json()
    if not isinstance(payload, dict):
        raise AuthError("WordPress.com returned a non-object token response.")
    return payload


def _code_from_redirect(redirect_url: str, expected_state: str) -> str:
    query = parse_qs(urlparse(redirect_url.strip()).query)
    if "error" in query:
        raise AuthError(f"WordPress.com denied login: {query['error'][0]}")
    state = query.get("state", [None])[0]
    if state != expected_state:
        raise AuthError("OAuth state did not match; refusing the callback.")
    code = query.get("code", [None])[0]
    if not code:
        raise AuthError("The pasted redirect URL does not contain an OAuth code.")
    return code


class _CallbackServer(HTTPServer):
    redirect_url: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    server: _CallbackServer

    def do_GET(self) -> None:
        host = self.headers.get("Host", "localhost")
        self.server.redirect_url = f"http://{host}{self.path}"
        body = b"Login received. You can close this tab and return to jsp.\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def login(config: Config, *, manual: bool) -> Path:
    """Run OAuth login and return the token path."""

    state = secrets.token_urlsafe(24)

    if manual:
        redirect_uri = config.redirect_uri
        authorize_url = build_authorize_url(
            config, redirect_uri=redirect_uri, state=state
        )
        print("Open this URL in a browser:\n")
        print(authorize_url)
        print("\nAfter approval, paste the complete redirected URL.")
        redirect_url = input("> ").strip()
    else:
        server = _CallbackServer(("localhost", 0), _CallbackHandler)
        server.timeout = 300
        port = server.server_address[1]
        redirect_uri = f"http://localhost:{port}/callback"
        authorize_url = build_authorize_url(
            config, redirect_uri=redirect_uri, state=state
        )
        print(f"Opening {authorize_url}")
        if not webbrowser.open(authorize_url):
            print("The browser did not open; copy the URL above into a browser.")
        server.handle_request()
        server.server_close()
        if not server.redirect_url:
            raise AuthError("Timed out waiting for the OAuth callback.")
        redirect_url = server.redirect_url

    code = _code_from_redirect(redirect_url, state)
    payload = exchange_code(config, code=code, redirect_uri=redirect_uri)
    if config.oauth_scope != "global" and config.site:
        if not token_matches_site(payload, config.site) and not can_read_stats(
            payload, config.site
        ):
            raise AuthError(
                f"The granted token (blog: {granted_blog(payload)}) cannot read "
                f"stats for {config.site}, so it was not saved. Select "
                f"{config.site} on the authorization screen, or confirm your "
                "account can view its stats."
            )
        payload = {**payload, "verified_site": config.site}
    save_token(payload, config.token_path)
    return config.token_path
