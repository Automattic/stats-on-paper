"""The ``sop`` command-line interface."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from sop.auth import login
from sop.config import ConfigError, load_config, require
from sop.http_service import create_app
from sop.panels.base import open_panel
from sop.render import render
from sop.render.layout import VIEWS, UnsupportedView
from sop.render.palette import PROFILES, get_profile
from sop.service import build_service

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

    if config.source == "direct":
        require(config, "site")
    service = build_service(config)

    if args.command == "fetch":
        snapshot = service.get_snapshot(max_age=0)
        print(json.dumps(snapshot.to_public_json(), indent=2))
        return 0

    if args.command in {"render", "display"}:
        # Flags override configuration; the parser is built before the config
        # is loaded, so neither can be an argparse default.
        panel = args.panel or config.panel
        if panel is None:
            require(config, "panel")
        view = args.view or config.view
        snapshot = service.get_snapshot(max_age=config.poll_interval_seconds)
        try:
            image = render(snapshot, get_profile(str(panel)), view=view)
        except UnsupportedView as error:
            # The renderer sits below the configuration seam and cannot name a
            # variable; here we can.
            raise ConfigError(
                f"{error} Set SOP_COMMERCE=true on the process that fetches."
            ) from error
    else:
        image = None

    if args.command == "render":
        assert image is not None
        image.save(args.output, format="PNG")
        print(args.output)
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        status = run()
    except (ConfigError, RuntimeError, ValueError) as error:
        print(f"sop: error: {error}", file=sys.stderr)
        status = 1
    raise SystemExit(status)


if __name__ == "__main__":
    main()
