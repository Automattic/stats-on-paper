# Jetpack Stats on Paper

Put a WordPress.com or Jetpack site's stats on an 800×480 e-ink display.

> **Status:** The tutorial post is not published yet, and the API may change.

<!-- Hero photo placeholder: add the finished three-panel photograph here. -->

## Hardware tiers

| Tier | Panel | Host | Status |
| --- | --- | --- | --- |
| Mono | Waveshare 4.26" mono HAT | Raspberry Pi | Driver included |
| Colour | Pimoroni Inky Impression 7.3" (Spectra 6) | Raspberry Pi | Driver included |
| Hosted | TRMNL | TRMNL | JSON polling included |

## Quickstart

```console
jsp fetch
jsp render --panel waveshare-4in26 -o out.png
jsp display --panel waveshare-4in26
jsp serve
```

Copy `.env.example` to `.env`, fill in the WordPress.com application and site
settings, then run `jsp login --manual` before the commands above. Hardware is
only required for `jsp display`.

## Exit ramps

You can stop after `jsp fetch` if you only need portable JSON, or after
`jsp render` if a PNG is the final output. Neither path requires buying a
panel.

The exact WordPress.com requests and current verification gaps are recorded in
[`docs/api-notes.md`](docs/api-notes.md).

Licensed under GPL-2.0-or-later.

