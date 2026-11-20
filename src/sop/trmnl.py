"""Upload a rendered frame to a TRMNL Webhook Image plugin.

TRMNL passes the image to the device untouched, so the frame must already be
the model's exact size and inks; the renderer makes it, `encode_png` writes
it, and this module only sends it. The webhook URL is the plugin's only
credential and never appears in a message.
"""

from __future__ import annotations

import requests

from sop import __version__

# The render profiles that match a TRMNL model's screen, by model name.
TRMNL_PANELS = {
    "trmnl": "TRMNL OG",
    "trmnl-bwry": "TRMNL OG (B/W/R/Y)",
    "trmnl-x": "TRMNL X",
}

_COPY_AGAIN = (
    "Copy the whole Webhook URL from the Webhook Image plugin's settings into "
    "SOP_TRMNL_WEBHOOK_URL again."
)

# Shown to the person running `sop push`; each names the setting or step that
# fixes the refusal. TRMNL's own response text is never repeated, because it
# may quote the URL.
_REFUSALS = {
    401: f"TRMNL does not recognise that address (401). {_COPY_AGAIN}",
    403: (
        "TRMNL refused the upload (403). If the Webhook URL is right, TRMNL may "
        "be blocking this network for now; the next push will try again."
    ),
    404: f"TRMNL does not recognise that address (404). {_COPY_AGAIN}",
    422: (
        "TRMNL could not use the image (422): it is too large, not a picture, "
        "or damaged. That should not happen with a frame from sop; please open "
        "an issue."
    ),
    429: (
        "TRMNL accepts a push about 12 times an hour (429). Push less often; "
        "once an hour is plenty for daily stats."
    ),
}


class PushError(RuntimeError):
    """TRMNL did not accept the image."""


def push_png(png: bytes, webhook_url: str, *, timeout: float = 20) -> None:
    """Upload a PNG as the request body, the way the plugin's docs show.

    Only a 2xx without an error in its body counts as delivered. A redirect is
    never followed: it would turn the upload into a GET of some page and report
    success, or carry the picture to another host.
    """

    failure: str | None
    try:
        response = requests.post(
            webhook_url,
            data=png,
            headers={
                "Content-Type": "image/png",
                "User-Agent": f"stats-on-paper/{__version__}",
            },
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.exceptions.InvalidURL:
        # Raised outside the handler so the original, which names the URL, is
        # not chained to the error a cron job logs.
        failure = f"SOP_TRMNL_WEBHOOK_URL is not a usable address. {_COPY_AGAIN}"
    except requests.RequestException as error:
        failure = (
            f"Could not reach TRMNL ({type(error).__name__}). The next push will "
            "try again."
        )
    else:
        failure = _refusal(response)
    if failure is not None:
        raise PushError(failure) from None


def _refusal(response: requests.Response) -> str | None:
    """Why TRMNL did not take the image, or None when it did."""

    status = response.status_code
    if 300 <= status < 400:
        return f"TRMNL answered with a redirect ({status}). {_COPY_AGAIN}"
    if status in _REFUSALS:
        return _REFUSALS[status]
    if status >= 400:
        return (
            f"TRMNL answered {status}, so the picture may not have arrived. The "
            "next push will try again."
        )
    if _reports_error(response):
        return f"TRMNL answered {status} but did not accept the image. {_COPY_AGAIN}"
    return None


def _reports_error(response: requests.Response) -> bool:
    """Whether a 2xx body says the upload failed anyway."""

    try:
        payload = response.json()
    except ValueError:
        return False
    return isinstance(payload, dict) and bool(
        payload.get("error") or payload.get("errors")
    )
