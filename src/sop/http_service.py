"""Thin Flask routes around the snapshot and renderer core."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from functools import wraps
from hashlib import sha256
from io import BytesIO
from typing import Any, TypeVar, cast

from flask import Flask, Response, jsonify, request, send_file
from flask.json.provider import DefaultJSONProvider

from sop.render import render
from sop.render.layout import VIEWS, UnsupportedView
from sop.render.palette import get_profile
from sop.service import SnapshotService

_F = TypeVar("_F", bound=Callable[..., Any])


def create_app(
    service: SnapshotService,
    *,
    bearer_token: str | None,
    cache_max_age: float,
    default_view: str = "stats",
) -> Flask:
    """Serve the snapshot as JSON and as a panel-sized PNG.

    The default view is checked here rather than on every request: a typo in
    the configuration should stop the server starting, not answer 400 forever.
    """

    if default_view not in VIEWS:
        raise UnsupportedView(
            f"Unknown view {default_view!r}. Choose one of: {', '.join(VIEWS)}."
        )
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

    def conditional(response: Response) -> Response:
        response.direct_passthrough = False
        etag = sha256(response.get_data()).hexdigest()
        if request.if_none_match.contains(etag):
            response = Response(status=304)
        response.set_etag(etag)
        response.cache_control.no_cache = None
        response.cache_control.private = True
        response.cache_control.max_age = round(cache_max_age)
        return response

    @app.get("/v1/stats.json")
    @require_token
    def stats_json() -> Response:
        snapshot = service.get_snapshot(max_age=cache_max_age)
        return conditional(jsonify(snapshot.to_public_json()))

    @app.get("/v1/screen.png")
    @require_token
    def screen_png() -> Response | tuple[Response, int]:
        try:
            profile = get_profile(request.args.get("panel", "trmnl"))
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        snapshot = service.get_snapshot(max_age=cache_max_age)
        try:
            image = render(
                snapshot, profile, view=request.args.get("view", default_view)
            )
        except UnsupportedView as error:
            # Only an unusable view name is the caller's fault; a rendering
            # failure is a defect and must stay a 500.
            return jsonify({"error": str(error)}), 400
        output = BytesIO()
        image.save(output, format="PNG")
        output.seek(0)
        response = send_file(
            output,
            mimetype="image/png",
            download_name="screen.png",
        )
        return conditional(response)

    return app
