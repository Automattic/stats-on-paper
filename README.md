# Stats on Paper

Put your WordPress.com or Jetpack site's stats on an e-ink display.

![Sample dashboard rendered for an 800×480 Spectra 6 panel](assets/previews/impression-7in3.png)

After a one-time `sop login --manual`, four commands do the work. Each is
useful on its own, so you can stop wherever you like:

- `sop fetch` prints your stats as JSON;
- `sop render` turns that JSON into a PNG at the panel's exact size;
- `sop display` pushes the PNG to a panel plugged into this machine;
- `sop serve` publishes the JSON and the PNG over HTTP for a TRMNL or another
  device to poll.

You need a panel only for `display`. Everything else runs on a laptop.

> **Status:** early release. Fetching, rendering, and serving are tested. The
> Inky and Waveshare drivers exist but have not yet been run against a physical
> panel from this repository.

## What you need

- Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).
- A WordPress.com account that can see the site's stats. Jetpack-connected
  sites count.
- One of the panels in the table below, if you want to drive one.

## Install

```console
git clone https://github.com/Automattic/stats-on-paper.git
cd stats-on-paper
uv sync --locked
cp .env.example .env
```

## Connect your site

Stats come from the WordPress.com REST API, which needs a free OAuth app.

1. Open the [WordPress.com Applications Manager](https://developer.wordpress.com/apps/)
   and create an application. Name and description are up to you. Set the
   redirect URL to exactly `http://localhost/callback`.
2. In `.env`, fill in `WPCOM_CLIENT_ID`, `WPCOM_CLIENT_SECRET`, and
   `WPCOM_SITE` (your site's domain or numeric ID).
3. Authorize once:

   ```console
   uv run sop login --manual
   ```

   `sop` prints a URL. Open it and approve access for your site. The browser
   then lands on `http://localhost/callback?code=...` and reports that it
   cannot connect. That is expected: nothing is listening there. Copy the whole
   URL from the address bar and paste it at the `>` prompt in the terminal.

When it works, the command prints `Token saved to` and the file's path (by
default `~/.config/sop/token.json`). The token is stored with private file
permissions and grants stats access to that one site only.

For one login that covers several sites, set `WPCOM_SCOPE=global` before
logging in. You can then change `WPCOM_SITE` without logging in again.

## Render a picture

```console
uv run sop fetch
uv run sop render --panel impression-7in3 -o out.png
```

Open `out.png`. That is pixel for pixel what the panel would show. The first
command is optional; `render` fetches on its own.

| Profile | Size | Colors | Driver |
| --- | --- | --- | --- |
| `waveshare-2in13` | 250×122 | black/white | render only |
| `waveshare-2in13-four-color` | 250×122 | black/white/red/yellow | render only |
| `impression-4in0` | 600×400 | Spectra 6 | Inky, untested on hardware |
| `waveshare-4in26` | 800×480 | black/white | Waveshare, driver not on PyPI |
| `waveshare-4in26-four-color` | 800×480 | black/white/red/yellow | render only |
| `impression-7in3` | 800×480 | Spectra 6 | Inky, untested on hardware |
| `waveshare-10in3` | 1872×1404 | 4-level grayscale | render only |
| `trmnl` | 800×480 | black/white | the TRMNL polls `sop serve` |

"Render only" means you get a correct image for that panel, but this
repository does not ship a driver for it.

![Compact 250×122 layout](assets/previews/waveshare-2in13.png)

There are two screens. `stats` (the default) shows today's views and visitors
over a daily chart. `commerce` shows today's orders and views over a daily
orders chart. On panels of 600×400 and up, `stats` also shows views per
visitor and `commerce` also shows yesterday's orders. `commerce` needs
`SOP_COMMERCE=true` and a WooCommerce store.

```console
uv run sop render --view commerce --panel impression-7in3 -o orders.png
```

## Show it on a panel

```console
uv sync --extra inky
uv run sop display --panel impression-7in3
```

The first line installs the Inky driver, which covers the two `impression-*`
profiles. Run both lines on the machine the panel is wired to. `display`
works with `waveshare-4in26` only if you have installed Waveshare's
`waveshare_epd` package yourself. Otherwise stick with `render` for that panel.

That machine needs its own `.env` and token, so repeat the login there. Or
point it at a laptop running `sop serve --host 0.0.0.0`: set `SOP_SOURCE=url`,
`SOP_SOURCE_URL`, and the same `SOP_SERVE_TOKEN` in the panel machine's `.env`.

Set `SOP_PANEL` in `.env` to skip the flag. Run it from cron or a systemd
timer. The stats are daily totals, so once an hour is plenty.

## Serve it to a TRMNL or another device

```console
uv run sop serve
```

This publishes `GET /v1/stats.json` and `GET /v1/screen.png?panel=<profile>`
at `http://127.0.0.1:5000`. Leave `panel` off to get `trmnl`, and add
`&view=commerce` for the orders screen. `--host` and `--port` change the
address. Set `SOP_SERVE_TOKEN` to require a bearer token. Without one the
server refuses to listen on anything but localhost. It is Flask's development
server, so put an HTTPS proxy in front of it before pointing anything on the
internet at it.

For a TRMNL, see [`trmnl/README.md`](trmnl/README.md). It has the private
plugin settings and four ready-made layouts.

## Settings

Everything is read from `.env`, and `.env.example` documents every variable.
The ones you are most likely to touch:

| Variable | What it does | Default |
| --- | --- | --- |
| `SOP_PANEL` | Which panel `render` and `display` target | none |
| `SOP_VIEW` | `stats` or `commerce` | `stats` |
| `SOP_TZ` | Your site's timezone, so "today" rolls over when the site's day does | `UTC` |
| `SOP_SERIES_DAYS` | How many daily points to fetch | `30` |
| `SOP_POLL_INTERVAL_SECONDS` | How long a fetched snapshot is reused | `3600` |
| `SOP_COMMERCE` | Also fetch WooCommerce orders | `false` |
| `SOP_TOKEN_PATH` | Where the login token lives, for one token per site | `~/.config/sop/token.json` |

## If something goes wrong

| You see | Try this |
| --- | --- |
| `The granted token ... cannot read stats for ...` | On the authorization screen, pick the site named in `WPCOM_SITE`, or log in with `WPCOM_SCOPE=global`. |
| `No token found at ...` | Run `uv run sop login --manual`, or point `SOP_TOKEN_PATH` at the token you meant. |
| `Panel '...' is render-only and has no local driver` | Use `render` for the PNG, or a TRMNL through `serve`. |
| `This snapshot has no commerce data` | Set `SOP_COMMERCE=true` where `fetch` runs, then run `uv run sop fetch` once to replace the cached snapshot. |
| The footer says `Refresh delayed` (on 250×122 panels, just the age, starting at `2 hr old`) | The last successful fetch was over two hours ago. Delete `~/.cache/sop/snapshot.json`, then `uv run sop fetch` shows the real error. |

Anything else: [open an issue](https://github.com/Automattic/stats-on-paper/issues).

## More

- [CHANGELOG.md](CHANGELOG.md) for what changed in each release.
- [ARCHITECTURE.md](ARCHITECTURE.md) for how the pieces fit and why.
- [CONTRIBUTING.md](CONTRIBUTING.md) to set up for development.
- [SECURITY.md](SECURITY.md) to report a security problem.

Licensed under GPL-2.0-or-later. The bundled fonts and product marks have their
own notes in [COPYRIGHT.md](COPYRIGHT.md).
