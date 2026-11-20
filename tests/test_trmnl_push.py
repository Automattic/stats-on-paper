"""Rendering for TRMNL models and uploading to a Webhook Image plugin."""

from __future__ import annotations

import io

import pytest
import requests
import responses
from PIL import Image

from sop.models import StatsSnapshot
from sop.render import render
from sop.render.output import encode_png, pixel_values, quantize
from sop.render.palette import PROFILES
from sop.trmnl import TRMNL_PANELS, PushError, push_png

WEBHOOK = "https://trmnl.com/api/plugin_settings/0123abcd-test/image"

# TRMNL's own numbers for each model: screen size and the largest image it
# accepts from a webhook upload (https://trmnl.com/api/models).
TRMNL_SCREENS = {
    "trmnl": ((800, 480), 90_000),
    "trmnl-bwry": ((800, 480), 90_000),
    "trmnl-x": ((1872, 1404), 750_000),
}


def bwry_ink(red: int, green: int, blue: int) -> str:
    """The colour reduction in TRMNL's B/W/R/Y firmware (GetBWYRPixel), as
    the firmware's simulator in usetrmnl/trmnl-firmware mirrors it."""
    gray = (blue + red + green * 2) >> 2
    if red > blue or green > blue:
        if gray < 90 and red < 80 and green < 80:
            return "black"
        if red - blue > 32 and red - green > red / 2:
            return "red"
        if red - blue > 32 and green - blue > 32:
            return "yellow"
        return "white"
    return "white" if gray >= 100 else "black"


def _png_header(data: bytes) -> tuple[int, int]:
    """Bit depth and colour type from a PNG's IHDR chunk."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return data[24], data[25]


def test_every_trmnl_model_gets_a_frame_of_its_exact_size(
    snapshot: StatsSnapshot,
) -> None:
    """A Webhook Image upload is passed to the device untouched, so a frame
    of the wrong size or weight never reaches the screen intact."""
    assert set(TRMNL_PANELS) == set(TRMNL_SCREENS)

    for name, (size, limit) in TRMNL_SCREENS.items():
        image = render(snapshot, PROFILES[name], now=snapshot.fetched_at)
        png = encode_png(image, PROFILES[name])

        assert image.size == size, name
        assert len(png) < limit, (name, len(png))


def test_bwry_inks_survive_the_firmware_colour_reduction(
    snapshot: StatsSnapshot,
) -> None:
    """The B/W/R/Y OG maps every pixel through its own reduction rather than
    reading palette indices, so each ink must land on the one it means."""
    meant = {
        (255, 255, 255): "white",
        (0, 0, 0): "black",
        (220, 38, 38): "red",
        (245, 196, 0): "yellow",
    }
    assert set(PROFILES["trmnl-bwry"].colors) == set(meant)
    for color, ink in meant.items():
        assert bwry_ink(*color) == ink, color

    image = render(snapshot, PROFILES["trmnl-bwry"], now=snapshot.fetched_at)
    used = set(pixel_values(image.convert("RGB")))
    assert {"black", "white", "yellow"} <= {bwry_ink(*color) for color in used}


@pytest.mark.parametrize(
    ("name", "bit_depth", "color_type"),
    [("trmnl", 1, 0), ("trmnl-bwry", 2, 3), ("trmnl-x", 4, 3)],
)
def test_frames_are_encoded_as_small_palette_pngs(
    snapshot: StatsSnapshot, name: str, bit_depth: int, color_type: int
) -> None:
    """TRMNL's server sends the OG family 1- and 2-bit PNGs; the firmware's
    decoder cannot take full-colour rows that wide. The pixels must survive."""
    profile = PROFILES[name]
    image = render(snapshot, profile, now=snapshot.fetched_at)
    # The depth follows the panel, not the picture: a frame that happens to
    # use only black and white must still be the format the device expects.
    blank = Image.new("RGB", profile.size, (255, 255, 255))
    blank = quantize(blank, profile)

    for frame in (image, blank):
        png = encode_png(frame, profile)

        assert _png_header(png) == (bit_depth, color_type)
        decoded = Image.open(io.BytesIO(png))
        assert pixel_values(decoded.convert("RGB")) == pixel_values(
            frame.convert("RGB")
        )


@responses.activate
def test_the_png_is_uploaded_as_the_raw_request_body() -> None:
    png = b"\x89PNG\r\n\x1a\nnot really"
    responses.post(WEBHOOK, json={"data": {"message": "ok"}})

    push_png(png, WEBHOOK)

    request = responses.calls[0].request
    assert request.headers["Content-Type"] == "image/png"
    assert request.headers["User-Agent"].startswith("stats-on-paper/")
    assert request.body == png


@pytest.mark.parametrize(
    ("status", "headers", "body", "hint"),
    [
        (302, {"Location": "https://trmnl.com/login"}, {}, "Webhook URL"),
        (307, {"Location": "https://elsewhere.test/upload"}, {}, "Webhook URL"),
        (200, {}, {"error": "rejected"}, "did not accept"),
        (401, {}, {}, "Webhook URL"),
        (403, {}, {}, "refused"),
        (404, {}, {}, "Webhook URL"),
        (422, {}, {"error": f"bad image for {WEBHOOK}"}, "too large"),
        (429, {}, {}, "12 times an hour"),
        (503, {}, {}, "may not have arrived"),
    ],
)
@responses.activate
def test_each_refusal_says_what_to_do_next(
    status: int, headers: dict[str, str], body: dict[str, str], hint: str
) -> None:
    """Only TRMNL's documented acknowledgement counts as delivered. A redirect
    is never followed: it would turn the upload into a GET of some page, or
    carry the picture to another host. TRMNL's own text is never repeated,
    because it may quote the URL."""
    responses.post(WEBHOOK, status=status, headers=headers, json=body)

    with pytest.raises(PushError) as caught:
        push_png(b"png", WEBHOOK)

    message = str(caught.value)
    assert str(status) in message
    assert hint in message
    # The webhook URL is the plugin's only credential.
    assert "0123abcd" not in message
    assert len(responses.calls) == 1, "nothing was followed"


@pytest.mark.parametrize(
    ("error", "hint"),
    [
        (
            requests.ConnectionError(
                "Max retries exceeded with url: /api/plugin_settings/0123abcd-test"
            ),
            "next push will try again",
        ),
        (requests.exceptions.InvalidURL("bad /0123abcd-test"), "Copy the whole"),
    ],
)
@responses.activate
def test_a_failed_request_keeps_the_url_out_of_every_trace(
    error: Exception, hint: str
) -> None:
    """requests names the URL it failed on, so neither its message nor the
    chained exception may travel with the error a cron job logs."""
    responses.post(WEBHOOK, body=error)

    with pytest.raises(PushError) as caught:
        push_png(b"png", WEBHOOK)

    assert hint in str(caught.value)
    assert "0123abcd" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
