# Security

Please do not report security problems through GitHub issues.

Automattic runs a bug bounty programme on HackerOne. Report anything you find
in this project there: <https://hackerone.com/automattic>. The programme page
explains what is in scope and how disclosure works.

Things worth knowing when you assess this project:

- The OAuth token is stored in a file with mode `0600` under `~/.config/sop/`.
  Only the fields the app needs are written to it.
- `sop serve` is Flask's development server. Without `SOP_SERVE_TOKEN` set, the
  CLI refuses to bind to anything but localhost, and it is meant to sit behind
  a real HTTPS proxy when exposed further than that.
- The test suite blocks network access, so nothing in `tests/` can leak a token.
