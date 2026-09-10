# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

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

[0.1.0]: https://github.com/Automattic/stats-on-paper/releases/tag/v0.1.0
