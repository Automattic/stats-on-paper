from __future__ import annotations

import pytest

from jsp.config import ConfigError, load_config


def test_missing_config_names_variable_and_example(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.delenv("WPCOM_SITE", raising=False)
    monkeypatch.delenv("JSP_SOURCE", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ConfigError) as caught:
        load_config(required=("site",))

    assert "Missing WPCOM_SITE" in str(caught.value)
    assert ".env.example" in str(caught.value)


def test_url_source_requires_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JSP_SOURCE", "url")
    monkeypatch.delenv("JSP_SOURCE_URL", raising=False)

    with pytest.raises(ConfigError, match="Missing JSP_SOURCE_URL"):
        load_config()


def test_invalid_series_days_is_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JSP_SERIES_DAYS", "many")

    with pytest.raises(ConfigError, match="JSP_SERIES_DAYS must be a whole number"):
        load_config()
