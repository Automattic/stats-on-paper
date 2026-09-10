from __future__ import annotations

from pathlib import Path

import pytest

from sop.config import ConfigError, load_config, require


def test_missing_config_names_the_variable_and_the_example(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """Commands load once and then state what they need; both paths name
    the variable to set and point at .env.example."""
    monkeypatch.delenv("WPCOM_SITE", raising=False)
    monkeypatch.delenv("SOP_SOURCE", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ConfigError) as caught:
        load_config(required=("site",))
    assert "Missing WPCOM_SITE" in str(caught.value)
    assert ".env.example" in str(caught.value)

    config = load_config()
    with pytest.raises(ConfigError, match="Missing WPCOM_SITE"):
        require(config, "site")

    monkeypatch.setenv("WPCOM_SITE", "example.com")
    require(load_config(), "site")


def test_url_source_requires_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOP_SOURCE", "url")
    monkeypatch.delenv("SOP_SOURCE_URL", raising=False)

    with pytest.raises(ConfigError, match="Missing SOP_SOURCE_URL"):
        load_config()


def test_token_path_is_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOP_TOKEN_PATH", "~/tokens/example.com.json")

    assert load_config().token_path == Path.home() / "tokens" / "example.com.json"


def test_invalid_values_are_named(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value, message in (
        ("WPCOM_SCOPE", "everything", "WPCOM_SCOPE must be 'stats' or 'global'"),
        ("SOP_SERIES_DAYS", "many", "SOP_SERIES_DAYS must be a whole number"),
        ("SOP_TZ", "Mars/Olympus", "SOP_TZ names an unknown timezone"),
    ):
        monkeypatch.setenv(name, value)
        with pytest.raises(ConfigError, match=message):
            load_config()
        monkeypatch.delenv(name)
