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
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from jsp.config import Config

AUTHORIZE_URL = "https://public-api.wordpress.com/oauth2/authorize"
TOKEN_URL = "https://public-api.wordpress.com/oauth2/token"
OAUTH_SCOPE = "stats"


class AuthError(RuntimeError):
    """Login or token storage failed."""


def load_access_token(path: Path) -> str:
    """Read the access token from the private token file."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise AuthError(
            f"No token found at {path}. Run `jsp login --manual` first."
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise AuthError(f"Could not read token file {path}: {error}") from error

    token = payload.get("access_token") if isinstance(payload, dict) else None
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


def build_authorize_url(config: Config, *, redirect_uri: str, state: str) -> str:
    """Build the least-privilege, single-site authorization URL."""

    if not config.client_id or not config.site:
        raise AuthError("OAuth login requires WPCOM_CLIENT_ID and WPCOM_SITE.")
    query = urlencode(
        {
            "client_id": config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "blog": config.site,
            "scope": OAUTH_SCOPE,
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


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
    save_token(payload, config.token_path)
    return config.token_path
