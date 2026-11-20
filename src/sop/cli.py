"""The ``sop`` command-line interface."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from datetime import UTC
from pathlib import Path

from sop.auth import login
from sop.config import Config, ConfigError, load_config, require
from sop.http_service import create_app
from sop.panels.base import open_panel
from sop.render import render
from sop.render.layout import VIEWS, UnsupportedView
from sop.render.output import encode_png
from sop.render.palette import PROFILES, get_profile
from sop.service import build_service
from sop.trmnl import TRMNL_PANELS, push_png

LOGGER = logging.getLogger("sop")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sop", description="Put your site's stats on e-ink."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login", help="Authorize WordPress.com.")
    login_parser.add_argument(
        "--manual",
        action="store_true",
        help="Paste the final redirect URL instead of starting a callback server.",
    )

    subparsers.add_parser("fetch", help="Print the public snapshot JSON.")

    render_parser = subparsers.add_parser(
        "render", help="Render a native-size panel PNG without hardware."
    )
    render_parser.add_argument("--panel", choices=tuple(PROFILES))
    render_parser.add_argument("--view", choices=tuple(VIEWS))
    render_parser.add_argument("-o", "--output", type=Path, default=Path("out.png"))

    display_parser = subparsers.add_parser(
        "display", help="Render and show the image on a local panel."
    )
    display_parser.add_argument("--panel", choices=tuple(PROFILES))
    display_parser.add_argument("--view", choices=tuple(VIEWS))

    push_parser = subparsers.add_parser(
        "push", help="Render the latest stats and send them to a TRMNL."
    )
    push_parser.add_argument("--panel", choices=tuple(TRMNL_PANELS))
    push_parser.add_argument("--view", choices=tuple(VIEWS))

    serve_parser = subparsers.add_parser("serve", help="Serve JSON and PNG endpoints.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=5000)

    return parser


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()

    if args.command == "login":
        require(config, "client_id", "client_secret", "site")
        token_path = login(config, manual=args.manual)
        print(f"Token saved to {token_path}")
        return 0

    panel: str | None = None
    view = config.view
    if args.command in {"render", "display", "push"}:
        # Everything these commands need from the configuration is checked
        # before a token is read or a request is made. Flags override
        # configuration; the parser is built before the config is loaded, so
        # neither can be an argparse default.
        panel = args.panel or config.panel
        view = args.view or config.view
        if args.command == "push":
            _check_push_settings(config, panel)
        elif panel is None:
            require(config, "panel")
        if view not in VIEWS:
            raise ConfigError(
                f"SOP_VIEW is {view!r}. Choose one of: {', '.join(VIEWS)}."
            )

    if config.source == "direct":
        require(config, "site")
    service = build_service(config)

    if args.command == "fetch":
        snapshot = service.get_snapshot(max_age=0)
        print(json.dumps(snapshot.to_public_json(), indent=2))
        return 0

    if args.command in {"render", "display", "push"}:
        assert panel is not None
        profile = get_profile(panel)
        # A push is what changes the screen, so it always asks for the latest
        # numbers.
        max_age = 0 if args.command == "push" else config.poll_interval_seconds
        snapshot = service.get_snapshot(max_age=max_age)
        try:
            image = render(snapshot, profile, view=view)
        except UnsupportedView as error:
            # The view's name was checked above, so this is a snapshot without
            # the orders the commerce view draws. The renderer sits below the
            # configuration seam and cannot name a variable; here we can.
            raise ConfigError(
                f"{error} Set SOP_COMMERCE=true on the process that fetches."
            ) from error
    else:
        image = None

    if args.command == "render":
        assert image is not None
        args.output.write_bytes(encode_png(image, profile))
        print(args.output)
        return 0

    if args.command == "push":
        assert image is not None and config.trmnl_webhook_url is not None
        png = encode_png(image, profile)
        push_png(png, config.trmnl_webhook_url)
        fetched = snapshot.fetched_at.astimezone(UTC)
        print(
            f"Sent the {panel} screen for {snapshot.site.name} to TRMNL: numbers "
            f"from {fetched:%Y-%m-%d %H:%M} UTC, {len(png):,} bytes."
        )
        return 0

    if args.command == "display":
        assert image is not None
        panel_device = open_panel(str(panel))
        try:
            panel_device.show(image)
            panel_device.sleep()
        except Exception:
            LOGGER.exception(
                "Panel refresh failed; leaving the previous e-ink frame untouched."
            )
            return 1
        return 0

    if args.command == "serve":
        if not config.serve_token and args.host not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ConfigError(
                "SOP_SERVE_TOKEN is unset, so sop serve will only bind to "
                "localhost. Set it before using --host on a network interface."
            )
        app = create_app(
            service,
            bearer_token=config.serve_token,
            cache_max_age=config.poll_interval_seconds,
            default_view=config.view,
        )
        app.run(host=args.host, port=args.port)
        return 0

    raise AssertionError(f"Unhandled command {args.command}")


def _check_push_settings(config: Config, panel: str | None) -> None:
    """Refuse a push that could not show correctly, before any request.

    TRMNL shows an uploaded picture as it is, so the panel must be one drawn
    for a TRMNL screen; nothing downstream would resize or recolour it.
    """

    require(config, "trmnl_webhook_url")
    url = config.trmnl_webhook_url or ""
    if not url.lower().startswith("https://"):
        # The URL is the plugin's only credential, so it is not echoed.
        raise ConfigError(
            "SOP_TRMNL_WEBHOOK_URL must start with https://. Copy the whole "
            "Webhook URL from the Webhook Image plugin's settings."
        )
    if panel not in TRMNL_PANELS:
        models = ", ".join(f"{name} ({label})" for name, label in TRMNL_PANELS.items())
        found = (
            f"SOP_PANEL is {panel}, which is not a TRMNL model."
            if panel
            else "Missing SOP_PANEL."
        )
        raise ConfigError(
            f"{found} `sop push` draws for your TRMNL model; set SOP_PANEL in .env "
            f"or pass --panel: {models}."
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    # urllib3 names the full request URL in some warnings, and a TRMNL webhook
    # URL is a credential that cron would copy into its log.
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    try:
        status = run()
    except (ConfigError, RuntimeError, ValueError) as error:
        print(f"sop: error: {error}", file=sys.stderr)
        status = 1
    raise SystemExit(status)


if __name__ == "__main__":
    main()
