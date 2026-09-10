from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import jsp.cli
from jsp.cli import run
from jsp.config import ConfigError


def test_a_command_loads_configuration_once(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("WPCOM_SITE", "example.com")
    monkeypatch.delenv("JSP_SOURCE", raising=False)
    loads = 0
    real_load_config = jsp.cli.load_config

    def counting_load_config(*args: object, **kwargs: object) -> object:
        nonlocal loads
        loads += 1
        return real_load_config(*args, **kwargs)

    monkeypatch.setattr(jsp.cli, "load_config", counting_load_config)
    monkeypatch.setattr(
        jsp.cli,
        "build_service",
        lambda config: SimpleNamespace(get_snapshot=lambda max_age: snapshot),
    )

    assert run(["fetch"]) == 0
    assert loads == 1
    assert capsys.readouterr().out.startswith('{\n  "schema": 1,')


def test_url_source_does_not_demand_a_site(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("WPCOM_SITE", raising=False)
    monkeypatch.setenv("JSP_SOURCE", "url")
    monkeypatch.setenv("JSP_SOURCE_URL", "http://stats.local")
    monkeypatch.setattr(
        jsp.cli,
        "build_service",
        lambda config: SimpleNamespace(get_snapshot=lambda max_age: snapshot),
    )

    assert run(["fetch"]) == 0


def test_flags_override_configuration_and_config_fills_the_rest(
    monkeypatch: pytest.MonkeyPatch, snapshot: object, tmp_path: Path
) -> None:
    """One rule covers all three cases: flag wins, config fills, absence fails."""
    monkeypatch.setenv("WPCOM_SITE", "example.com")
    monkeypatch.delenv("JSP_SOURCE", raising=False)
    monkeypatch.setattr(
        jsp.cli,
        "build_service",
        lambda config: SimpleNamespace(get_snapshot=lambda max_age: snapshot),
    )
    calls: list[tuple[str, str]] = []

    def recording_render(snap: object, profile: object, *, view: str) -> object:
        calls.append((profile.name, view))
        return Image.new("RGB", (4, 4))

    monkeypatch.setattr(jsp.cli, "render", recording_render)
    output = str(tmp_path / "out.png")

    monkeypatch.setenv("JSP_VIEW", "stats")
    monkeypatch.setenv("JSP_PANEL", "trmnl")
    assert run(["render", "--view", "commerce", "-o", output]) == 0
    assert calls[-1] == ("trmnl", "commerce"), "flag beats JSP_VIEW, JSP_PANEL fills in"

    assert run(["render", "--panel", "waveshare-2in13", "-o", output]) == 0
    assert calls[-1] == ("waveshare-2in13", "stats"), "flag beats JSP_PANEL"

    monkeypatch.delenv("JSP_PANEL")
    with pytest.raises(ConfigError, match="Missing JSP_PANEL"):
        run(["render", "-o", output])


def test_a_store_less_site_is_told_what_to_set(
    monkeypatch: pytest.MonkeyPatch, snapshot: object, tmp_path: Path
) -> None:
    """The renderer cannot name a setting; the CLI knows one and should."""
    from dataclasses import replace

    monkeypatch.setenv("WPCOM_SITE", "example.com")
    monkeypatch.delenv("JSP_SOURCE", raising=False)
    monkeypatch.setenv("JSP_PANEL", "trmnl")
    storeless = replace(snapshot, commerce=None)
    monkeypatch.setattr(
        jsp.cli,
        "build_service",
        lambda config: SimpleNamespace(get_snapshot=lambda max_age: storeless),
    )

    with pytest.raises(ConfigError, match="JSP_COMMERCE"):
        run(["render", "--view", "commerce", "-o", str(tmp_path / "o.png")])
