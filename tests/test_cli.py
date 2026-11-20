from __future__ import annotations

import io
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import responses
from PIL import Image

import sop.cli
from sop.cache import SnapshotCache
from sop.cli import run
from sop.config import ConfigError, load_config
from sop.models import StatsSnapshot
from sop.service import cache_key


def test_a_command_loads_configuration_once(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("WPCOM_SITE", "example.com")
    monkeypatch.delenv("SOP_SOURCE", raising=False)
    loads = 0
    real_load_config = sop.cli.load_config

    def counting_load_config(*args: object, **kwargs: object) -> object:
        nonlocal loads
        loads += 1
        return real_load_config(*args, **kwargs)

    monkeypatch.setattr(sop.cli, "load_config", counting_load_config)
    monkeypatch.setattr(
        sop.cli,
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
    monkeypatch.setenv("SOP_SOURCE", "url")
    monkeypatch.setenv("SOP_SOURCE_URL", "http://stats.local")
    monkeypatch.setattr(
        sop.cli,
        "build_service",
        lambda config: SimpleNamespace(get_snapshot=lambda max_age: snapshot),
    )

    assert run(["fetch"]) == 0


def test_flags_override_configuration_and_config_fills_the_rest(
    monkeypatch: pytest.MonkeyPatch, snapshot: object, tmp_path: Path
) -> None:
    """One rule covers all three cases: flag wins, config fills, absence fails."""
    monkeypatch.setenv("WPCOM_SITE", "example.com")
    monkeypatch.delenv("SOP_SOURCE", raising=False)
    monkeypatch.setattr(
        sop.cli,
        "build_service",
        lambda config: SimpleNamespace(get_snapshot=lambda max_age: snapshot),
    )
    calls: list[tuple[str, str]] = []

    def recording_render(snap: object, profile: object, *, view: str) -> object:
        calls.append((profile.name, view))
        return Image.new("RGB", (4, 4))

    monkeypatch.setattr(sop.cli, "render", recording_render)
    output = str(tmp_path / "out.png")

    monkeypatch.setenv("SOP_VIEW", "stats")
    monkeypatch.setenv("SOP_PANEL", "trmnl")
    assert run(["render", "--view", "commerce", "-o", output]) == 0
    assert calls[-1] == ("trmnl", "commerce"), "flag beats SOP_VIEW, SOP_PANEL fills in"

    assert run(["render", "--panel", "waveshare-2in13", "-o", output]) == 0
    assert calls[-1] == ("waveshare-2in13", "stats"), "flag beats SOP_PANEL"

    monkeypatch.delenv("SOP_PANEL")
    with pytest.raises(ConfigError, match="Missing SOP_PANEL"):
        run(["render", "-o", output])


def test_a_store_less_site_is_told_what_to_set(
    monkeypatch: pytest.MonkeyPatch, snapshot: object, tmp_path: Path
) -> None:
    """The renderer cannot name a setting; the CLI knows one and should."""
    from dataclasses import replace

    monkeypatch.setenv("WPCOM_SITE", "example.com")
    monkeypatch.delenv("SOP_SOURCE", raising=False)
    monkeypatch.setenv("SOP_PANEL", "trmnl")
    storeless = replace(snapshot, commerce=None)
    monkeypatch.setattr(
        sop.cli,
        "build_service",
        lambda config: SimpleNamespace(get_snapshot=lambda max_age: storeless),
    )

    with pytest.raises(ConfigError, match="SOP_COMMERCE"):
        run(["render", "--view", "commerce", "-o", str(tmp_path / "o.png")])


def test_push_checks_every_setting_before_reading_a_token(
    monkeypatch: pytest.MonkeyPatch, snapshot: object
) -> None:
    """A push that could not show correctly stops before any request, and the
    message names the setting. The webhook URL is never echoed."""
    monkeypatch.setenv("WPCOM_SITE", "example.com")
    monkeypatch.delenv("SOP_SOURCE", raising=False)
    monkeypatch.delenv("SOP_PANEL", raising=False)
    monkeypatch.delenv("SOP_VIEW", raising=False)
    monkeypatch.delenv("SOP_TRMNL_WEBHOOK_URL", raising=False)
    builds = 0

    def counting_build(config: object) -> object:
        nonlocal builds
        builds += 1
        return SimpleNamespace(get_snapshot=lambda max_age: snapshot)

    monkeypatch.setattr(sop.cli, "build_service", counting_build)

    for name, value, message in (
        (None, None, "Missing SOP_TRMNL_WEBHOOK_URL"),
        ("SOP_TRMNL_WEBHOOK_URL", "http://trmnl.test/0123abcd", "https://"),
        ("SOP_TRMNL_WEBHOOK_URL", "HTTPS://trmnl.test/0123abcd", "Missing SOP_PANEL"),
        ("SOP_PANEL", "waveshare-4in26", "not a TRMNL model"),
        ("SOP_PANEL", "trmnl-x", None),
        ("SOP_VIEW", "comerce", "SOP_VIEW is 'comerce'"),
    ):
        if name is not None:
            monkeypatch.setenv(name, value)
        if message is None:
            continue
        with pytest.raises(ConfigError, match=message) as caught:
            run(["push"])
        assert "0123abcd" not in str(caught.value)
        assert "SOP_COMMERCE" not in str(caught.value)
    assert builds == 0
    assert "--panel" in _push_error(monkeypatch, "SOP_PANEL", "waveshare-4in26")


def _push_error(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> str:
    monkeypatch.setenv(name, value)
    monkeypatch.delenv("SOP_VIEW", raising=False)
    with pytest.raises(ConfigError) as caught:
        run(["push"])
    return str(caught.value)


def test_push_uploads_the_frame_for_the_trmnl_model(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`sop push` renders the configured TRMNL model fresh and uploads it in
    that model's own PNG format."""
    webhook = "https://trmnl.com/api/plugin_settings/0123abcd-test/image"
    monkeypatch.setenv("WPCOM_SITE", "example.com")
    monkeypatch.delenv("SOP_SOURCE", raising=False)
    monkeypatch.delenv("SOP_VIEW", raising=False)
    monkeypatch.setenv("SOP_TRMNL_WEBHOOK_URL", webhook)
    monkeypatch.setenv("SOP_PANEL", "trmnl-x")
    ages: list[float] = []

    def get_snapshot(max_age: float) -> object:
        ages.append(max_age)
        return snapshot

    monkeypatch.setattr(
        sop.cli,
        "build_service",
        lambda config: SimpleNamespace(get_snapshot=get_snapshot),
    )
    uploads: list[tuple[tuple[int, int], int, int, str]] = []

    def recording_push(png: bytes, url: str) -> None:
        size = Image.open(io.BytesIO(png)).size
        uploads.append((size, png[24], png[25], url))

    monkeypatch.setattr(sop.cli, "push_png", recording_push)

    assert run(["push"]) == 0, "SOP_PANEL picks the model"
    assert run(["push", "--panel", "trmnl-bwry"]) == 0, "the flag beats SOP_PANEL"
    assert run(["push", "--panel", "trmnl"]) == 0

    assert uploads == [
        ((1872, 1404), 4, 3, webhook),
        ((800, 480), 2, 3, webhook),
        ((800, 480), 1, 0, webhook),
    ]
    assert ages == [0, 0, 0], "a push always asks for the latest numbers"
    output = capsys.readouterr().out
    assert "trmnl-bwry" in output
    assert "numbers from 2026-07-27 12:34 UTC" in output
    assert "0123abcd" not in output


def test_a_bad_trmnl_setting_never_stops_other_commands(
    monkeypatch: pytest.MonkeyPatch, snapshot: object
) -> None:
    monkeypatch.setenv("WPCOM_SITE", "example.com")
    monkeypatch.delenv("SOP_SOURCE", raising=False)
    monkeypatch.setenv("SOP_TRMNL_WEBHOOK_URL", "http://not-https.test")
    monkeypatch.setattr(
        sop.cli,
        "build_service",
        lambda config: SimpleNamespace(get_snapshot=lambda max_age: snapshot),
    )

    assert run(["fetch"]) == 0


def test_render_writes_the_panels_own_png_format(
    monkeypatch: pytest.MonkeyPatch, snapshot: object, tmp_path: Path
) -> None:
    monkeypatch.setenv("WPCOM_SITE", "example.com")
    monkeypatch.delenv("SOP_SOURCE", raising=False)
    monkeypatch.setattr(
        sop.cli,
        "build_service",
        lambda config: SimpleNamespace(get_snapshot=lambda max_age: snapshot),
    )
    output = tmp_path / "out.png"

    assert run(["render", "--panel", "trmnl-x", "-o", str(output)]) == 0

    data = output.read_bytes()
    assert (data[24], data[25]) == (4, 3), "4-bit palette PNG, as push sends"


@responses.activate
def test_push_end_to_end_says_why_numbers_are_old_and_never_leaks_the_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    snapshot: StatsSnapshot,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Real cache, render, encoder, and HTTP code; only the network is faked.
    The stats source is down, so the last snapshot is pushed with a warning
    a cron log would keep. A redirect from TRMNL then fails the run."""
    webhook = "https://trmnl.com/api/plugin_settings/0123abcd-test/image"
    monkeypatch.setattr(sys, "argv", ["sop", "push"])
    monkeypatch.setenv("SOP_SOURCE", "url")
    monkeypatch.setenv("SOP_SOURCE_URL", "https://stats.example")
    monkeypatch.setenv("SOP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SOP_PANEL", "trmnl-bwry")
    monkeypatch.delenv("SOP_VIEW", raising=False)
    monkeypatch.setenv("SOP_TRMNL_WEBHOOK_URL", webhook)
    SnapshotCache(tmp_path, key=cache_key(load_config())).save(snapshot)
    responses.get("https://stats.example/v1/stats.json", status=500)
    responses.post(webhook, json={"data": {"message": "ok"}})

    with caplog.at_level(logging.WARNING), pytest.raises(SystemExit) as done:
        sop.cli.main()

    assert done.value.code == 0
    uploaded = responses.calls[-1].request.body
    assert (uploaded[24], uploaded[25]) == (2, 3)
    assert "numbers from 2026-07-27 12:34 UTC" in capsys.readouterr().out
    assert "Could not fetch fresh stats" in caplog.text

    responses.replace(
        responses.POST, webhook, status=302, headers={"Location": "/login"}
    )
    with pytest.raises(SystemExit) as failed:
        sop.cli.main()

    assert failed.value.code == 1
    streams = capsys.readouterr()
    assert "redirect" in streams.err
    assert "0123abcd" not in streams.err + streams.out + caplog.text
