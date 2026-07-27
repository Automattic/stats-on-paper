"""The ``jsp`` command-line interface."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from jsp.auth import login
from jsp.config import ConfigError, load_config
from jsp.http_service import create_app
from jsp.panels.base import open_panel
from jsp.render import render
from jsp.render.palette import PROFILES, get_profile
from jsp.service import build_service

LOGGER = logging.getLogger("jsp")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jsp", description="Put Jetpack stats on e-ink."
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
        "render", help="Render an 800×480 PNG without hardware."
    )
    render_parser.add_argument("--panel", choices=tuple(PROFILES), required=True)
    render_parser.add_argument("-o", "--output", type=Path, default=Path("out.png"))

    display_parser = subparsers.add_parser(
        "display", help="Render and show the image on a local panel."
    )
    display_parser.add_argument(
        "--panel",
        choices=("waveshare-4in26", "impression-7in3"),
        required=True,
    )

    serve_parser = subparsers.add_parser("serve", help="Serve JSON and PNG endpoints.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=5000)

    return parser


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "login":
        config = load_config(required=("client_id", "client_secret", "site"))
        token_path = login(config, manual=args.manual)
        print(f"Token saved to {token_path}")
        return 0

    required = () if _configured_for_url() else ("site",)
    config = load_config(required=required)
    service = build_service(config)

    if args.command == "fetch":
        snapshot = service.get_snapshot(max_age=0)
        print(json.dumps(snapshot.to_public_json(), indent=2))
        return 0

    if args.command == "render":
        snapshot = service.get_snapshot(max_age=20)
        image = render(snapshot, get_profile(args.panel))
        image.save(args.output, format="PNG")
        print(args.output)
        return 0

    if args.command == "display":
        snapshot = service.get_snapshot(max_age=20)
        image = render(snapshot, get_profile(args.panel))
        panel = open_panel(args.panel)
        try:
            panel.show(image)
            panel.sleep()
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
                "JSP_SERVE_TOKEN is unset, so jsp serve will only bind to "
                "localhost. Set it before using --host on a network interface."
            )
        app = create_app(service, bearer_token=config.serve_token)
        app.run(host=args.host, port=args.port)
        return 0

    raise AssertionError(f"Unhandled command {args.command}")


def _configured_for_url() -> bool:
    # This early load only decides which command-specific value is required.
    return load_config().source == "url"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        status = run()
    except (ConfigError, RuntimeError, ValueError) as error:
        print(f"jsp: error: {error}", file=sys.stderr)
        status = 1
    raise SystemExit(status)


if __name__ == "__main__":
    main()
