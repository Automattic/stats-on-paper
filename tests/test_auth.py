from __future__ import annotations

import json
import stat

import pytest

from jsp.auth import AuthError, load_access_token, save_token


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


def test_missing_token_explains_login(tmp_path: object) -> None:
    with pytest.raises(AuthError, match=r"jsp login --manual"):
        load_access_token(tmp_path / "token.json")
