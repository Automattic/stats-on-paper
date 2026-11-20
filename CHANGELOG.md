# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `sop push` renders the screen for your TRMNL model and uploads it to TRMNL's
  Webhook Image plugin (`SOP_TRMNL_WEBHOOK_URL`), so a TRMNL shows the same
  design and branding as every other panel without any server being reachable
  from the internet. Each refusal from TRMNL names the setting or step that
  fixes it.
- `trmnl-bwry` and `trmnl-x` profiles for the four-colour TRMNL OG and the
  TRMNL X.

### Changed

- The TRMNL Liquid templates, for polling a public `sop serve`, print when the
  numbers were fetched, switch to "Refresh delayed" after two hours (red on
  colour screens), and size the chart to the space each layout leaves, so
  they fit every TRMNL model in both orientations. They no longer add TRMNL's
  own `view` wrapper and use framework classes instead of inline styles, as
  TRMNL's recipe linter asks.

### Fixed

- Each site or source URL has its own snapshot cache, so after changing
  `WPCOM_SITE` or `SOP_SOURCE_URL` a failed fetch can no longer show, or push,
  the previous site's numbers. When older numbers are used, the reason is
  logged.
- A "Refresh delayed" footer names the fetch time instead of a relative age,
  which a TRMNL would keep showing long after it stopped being true.
- Grey panels draw ink in true black; on sixteen greys it landed one step
  above.
- `sop render` and `/v1/screen.png` write each panel's PNG at the bit depth its
  palette needs, the same bytes `sop push` uploads.
- A mistyped `SOP_VIEW` is reported before fetching, without the commerce
  hint.

### Security

- Allow Pillow 13 and lock it, with urllib3 2.8.0, Werkzeug 3.1.9, and
  certifi 2026.10.23, so a locked install gets the patched releases. Pillow 13
  renders every view and profile byte for byte the same as Pillow 12.

## [0.1.0] - 2026-09-10

First public release.

### Added

- `sop login`, `sop fetch`, `sop render`, `sop display`, and `sop serve`, each
  usable on its own.
- WordPress.com OAuth login with a least-privilege single-site `stats` scope or
  an account-wide `global` scope, and a functional check that the granted token
  can read the configured site.
- A schema-1 JSON snapshot that is the same on the wire, in the cache, and
  between two `sop serve` instances.
- Native-size renders for eight panel profiles: Waveshare 2.13", 4.26", and
  10.3", Inky Impression 4.0" and 7.3" (Spectra 6), the four-colour variants,
  and TRMNL.
- A `stats` view and a `commerce` view (WooCommerce orders).
- Four TRMNL Liquid layouts that render against the real wire payload.
- ETag-aware HTTP routes for the JSON and the PNG.
- A recorded render reference so refactors cannot change a frame unnoticed.

### Known limitations

- The Inky and Waveshare adapters have not been run against physical panels
  from this repository, and the Waveshare driver is not installable from wheels.
- Parse.ly branding is recognised in a snapshot, but there is no Parse.ly fetch
  path yet.

[Unreleased]: https://github.com/Automattic/stats-on-paper/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Automattic/stats-on-paper/releases/tag/v0.1.0
