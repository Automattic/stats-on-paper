from __future__ import annotations

import json
import stat
from pathlib import Path

from sop.auth import (
    build_authorize_url,
    load_access_token,
    save_token,
    token_matches_site,
)
from sop.config import Config


def _config(scope: str) -> Config:
    return Config(
        client_id="146320",
        client_secret="secret",
        site="example.com",
        oauth_scope="global" if scope == "global" else "stats",
        redirect_uri="http://localhost/callback",
        token_path=Path("/nonexistent/token.json"),
        cache_dir=Path("/nonexistent"),
        series_days=30,
        poll_interval_seconds=600,
        timezone="Europe/Madrid",
        source="direct",
        source_url=None,
        serve_token=None,
        commerce=False,
        view="stats",
        panel=None,
    )


def test_global_scope_authorize_url_omits_blog() -> None:
    url = build_authorize_url(
        _config("global"), redirect_uri="http://localhost/callback", state="s1"
    )
    assert "scope=global" in url
    assert "blog=" not in url

    single = build_authorize_url(
        _config("stats"), redirect_uri="http://localhost/callback", state="s1"
    )
    assert "scope=stats" in single
    assert "blog=example.com" in single


def test_token_file_is_private(tmp_path: object) -> None:
    path = tmp_path / "config" / "token.json"
    save_token(
        {
            "access_token": "test-token",
            "token_type": "bearer",
            "unexpected": "not stored",
        },
        path,
    )

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    payload = json.loads(path.read_text())
    assert payload == {
        "access_token": "test-token",
        "token_type": "bearer",
    }
    assert load_access_token(path) == "test-token"


def test_token_matches_site_by_domain_or_id_only() -> None:
    payload = {"blog_id": "9288856", "blog_url": "https://granted.example.com"}

    assert token_matches_site(payload, "granted.example.com")
    assert token_matches_site(payload, "9288856")
    assert not token_matches_site(payload, "requested.example.com")
