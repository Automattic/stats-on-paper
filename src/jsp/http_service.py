"""Thin Flask routes around the snapshot and renderer core."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from functools import wraps
from io import BytesIO
from typing import Any, TypeVar, cast

from flask import Flask, Response, jsonify, request, send_file
from flask.json.provider import DefaultJSONProvider

from jsp.render import render
from jsp.render.palette import get_profile
from jsp.service import SnapshotService

_F = TypeVar("_F", bound=Callable[..., Any])


def create_app(service: SnapshotService, *, bearer_token: str | None) -> Flask:
    app = Flask(__name__)
    cast(DefaultJSONProvider, app.json).sort_keys = False

    def require_token(function: _F) -> _F:
        @wraps(function)
        def wrapped(*args: object, **kwargs: object) -> Any:
            if bearer_token:
                supplied = request.headers.get("Authorization", "")
                expected = f"Bearer {bearer_token}"
                if not hmac.compare_digest(supplied, expected):
                    return jsonify({"error": "unauthorized"}), 401
            return function(*args, **kwargs)

        return cast(_F, wrapped)

    @app.get("/v1/stats.json")
    @require_token
    def stats_json() -> Response:
        snapshot = service.get_snapshot(max_age=20)
        return jsonify(snapshot.to_public_json())

    @app.get("/v1/screen.png")
    @require_token
    def screen_png() -> Response | tuple[Response, int]:
        panel_name = request.args.get("panel", "trmnl")
        try:
            profile = get_profile(panel_name)
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        snapshot = service.get_snapshot(max_age=20)
        image = render(snapshot, profile)
        output = BytesIO()
        image.save(output, format="PNG")
        output.seek(0)
        return send_file(output, mimetype="image/png", download_name="screen.png")

    return app
