# Architecture

Stats on Paper turns a site's daily stats into a picture an e-ink panel can
show. This document records how the code is arranged and the decisions behind
it, so that a change in one place does not quietly undo a guarantee made in
another.

## The seam

Everything hangs off one data type, `StatsSnapshot`:

```text
WordPress.com API, or another `sop serve`
                 |
                 v
     SnapshotService + snapshot cache
                 |
                 v
           StatsSnapshot
           /            \
          v              v
   pure renderer     public JSON  (GET /v1/stats.json, TRMNL, another sop)
          |
          v
         PNG          (GET /v1/screen.png, sop render)
          |
          v
   optional panel driver  (sop display)
```

The renderer sits below the seam. It never reads environment variables, calls
the network, picks a panel, or touches the cache. That is what lets the whole
picture be tested on a laptop with no credentials and no hardware, and why the
same snapshot draws identically whether it came from the API, the cache, or a
remote server.

## Code map

| Path | Responsibility | Invariant |
| --- | --- | --- |
| `src/sop/models.py` | Frozen snapshot dataclasses; schema-1 serialisation and parsing | Counts are never negative, a day appears once per series, and `commerce.orders` equals the last day of `commerce.series`. |
| `src/sop/client.py` | Thin WordPress.com calls and retry classification | 401 and 403 fail at once. Timeouts, connection errors, and 5xx retry three times. |
| `src/sop/service.py` | API-to-model parsing, source selection, cache policy | API quirks stop here. An authentication error never hides behind cached data. |
| `src/sop/cache.py` | `~/.cache/sop/snapshot.json` | Written to a temp file, fsynced, then atomically replaced. The cache holds the snapshot, not a rendered frame. |
| `src/sop/auth.py` | WordPress.com OAuth and `~/.config/sop/token.json` | Directory `0700`, file `0600`, only allow-listed fields persisted. A token is saved only if it can read the configured site. |
| `src/sop/config.py` | `.env` and environment parsing | The renderer never imports it. Values are validated once, and errors name the variable to set. |
| `src/sop/render/layout.py` | The compact and large layouts for every view | `render(snapshot, profile, view=, now=)` is pure. `VIEWS` maps a name to its two bodies. |
| `src/sop/render/chart.py` | Shared chart frame, paired and single-series bars, legend, sparkline | Zero baseline, one pixel minimum for any positive count, series windowed rather than overdrawn. |
| `src/sop/render/palette.py` | Panel sizes, physical palettes, output modes, layout inks | `PanelProfile.kind` is the single source of truth for ink policy and quantisation. A profile proves rendering, not a driver. |
| `src/sop/render/output.py` | RGB canvas to panel palette | Output never contains a colour the panel cannot show. |
| `src/sop/render/assets.py` | Bundled fonts and provider marks | Loaded once and cached. Font files are the only disk I/O in a render. |
| `src/sop/render/text.py`, `format.py` | Measuring, fitting, and formatting | Geometry and strings only, no drawing decisions. |
| `src/sop/panels/` | Optional device adapters | Importing `sop` never needs GPIO or a vendor library. A failed refresh leaves the previous frame on the panel. |
| `src/sop/http_service.py` | `/v1/stats.json` and `/v1/screen.png` | A non-loopback bind without `SOP_SERVE_TOKEN` is refused by the CLI. |
| `src/sop/cli.py` | `login`, `fetch`, `render`, `display`, `serve` | Each command is useful alone. Only `display` needs hardware. |
| `trmnl/` | Liquid layouts for a TRMNL private plugin | Every variable a template reads is proved to exist in `to_public_json()` by `tests/test_trmnl_templates.py`. |
| `tests/fixtures/render-hashes.json` | One hash per view and profile | The guard for refactors. Re-record only for an intended visual change, in its own commit. |

## The snapshot

Schema 1 carries: `schema`, `site` (`id`, `name`, `url`), a UTC `fetched_at`,
`today` and `yesterday` totals (`views`, `visitors`, `likes`, `comments`), a
sorted daily `series` of views and visitors, optional `all_time` totals,
optional `commerce` (today's `orders` plus a daily `series`), and the provider
`source`.

`to_public_json()` adds `age_seconds` at serialisation time and keeps `schema`
as the first key. The payload stays at the root level on purpose: TRMNL reads
root keys as template variables, and a second `sop serve` reads the same
document back with `snapshot_from_public_json()`.

`fetched_at` is the time the fetch started, not a provider timestamp. It is
what the "Updated 12:34 UTC" footer and the two-hour "Refresh delayed" warning
are computed from, so a stale snapshot served after a failure must keep its
original value.

The parser is strict where a wrong value would draw a lie (negative counts,
repeated dates, a schema it does not know, `commerce.orders` disagreeing with
the series) and tolerant elsewhere (extra keys, any `source` string). An
unknown source renders with neutral branding.

## WordPress.com

| Purpose | Request |
| --- | --- |
| Today and yesterday | `GET /rest/v1.1/sites/{site}/stats/summary?period=day&num=1&date=YYYY-MM-DD`, once per day |
| Daily trend | `GET /rest/v1/sites/{site}/stats/visits?unit=day&quantity=N&stat_fields=views,visitors` |
| All time | `GET /rest/v1.1/sites/{site}/stats` |
| Orders (optional) | `GET /wpcom/v2/sites/{site}/stats/orders?unit=day&quantity=N&date=YYYY-MM-DD&stat_fields=orders` |

Things learned against the live API that the code depends on:

- The visits endpoint must stay on API v1. Version 1.1 rejects tokens that
  carry only the `stats` scope.
- `GET /sites/{site}` needs the `sites` scope, which a `stats` token does not
  have. Site identity comes from the token response instead (`blog_id`,
  `blog_url`), falling back to the configured domain for mapped domains.
- The authorisation screen can grant a different blog than the one requested.
  `sop login` checks the granted blog textually, then functionally by probing
  the stats summary endpoint, and refuses to save a token that cannot read the
  configured site. It records `verified_site` in the token file so later runs
  stay offline.
- A `global` scope token has `blog_id: 0` and `blog_url: null`, and reads any
  site the account can see. `site.id` is then `null` in the JSON.
- The all-time response has no `likes` key in practice, so `all_time` is
  `None` and nothing renders it.
- The orders endpoint fails for sites without a store. That failure is
  contained: the snapshot is still fresh, with `commerce` absent.

"Today" is computed in `SOP_TZ`, because a site's day rolls over when the
site's day does, while `fetched_at` stays UTC.

## Refresh and caching

`SnapshotService.get_snapshot(max_age)` returns the cached snapshot if it is
younger than `max_age`, otherwise fetches. `fetch` asks for zero age; `render`,
`display`, and the HTTP routes use `SOP_POLL_INTERVAL_SECONDS`, an hour by
default. The figures are daily totals, so there is nothing to gain from
polling faster. The twenty-odd seconds an e-ink panel takes to redraw is a
physical refresh duration, not a polling cadence.

When a fetch fails and a cached snapshot exists, the cached one is returned
with its timestamp untouched, so the panel shows an honest age. The one
exception is authentication: a 401 or 403 always surfaces, because the
operator has to know the token is dead. A cache file the current build cannot
parse is logged and treated as absent; the next successful fetch replaces it.

There is no scheduler in the code. A cron job, systemd timer, or a TRMNL
polling the server supplies the cadence.

## Serving

`sop serve` exposes the JSON and a PNG for any profile and view. With
`SOP_SERVE_TOKEN` set, both routes require an exact `Authorization: Bearer`
header, compared in constant time. Responses are `private`, carry `max-age`,
and send a SHA-256 ETag, so a client can skip an identical frame with
`If-None-Match`. The JSON ETag changes as `age_seconds` ticks, so it is not a
snapshot-content tag.

`SOP_SOURCE=url` points one instance at another's `/v1/stats.json` and reuses
`SOP_SERVE_TOKEN` as the outbound credential. That is fine for one hop between
two machines you own. It is Flask's development server; put an HTTPS proxy in
front of it before anything outside localhost can reach it.

## Rendering

| Profile | Canvas | Palette | Driver |
| --- | ---: | --- | --- |
| `waveshare-2in13` | 250×122 | black/white | none |
| `waveshare-2in13-four-color` | 250×122 | black/white/red/yellow | none |
| `impression-4in0` | 600×400 | Spectra 6 | Inky adapter, untested on hardware |
| `waveshare-4in26` | 800×480 | black/white | adapter present, vendor driver not on PyPI |
| `waveshare-4in26-four-color` | 800×480 | black/white/red/yellow | none |
| `impression-7in3` | 800×480 | Spectra 6 | Inky adapter, untested on hardware |
| `waveshare-10in3` | 1872×1404 | four grey levels | none |
| `trmnl` | 800×480 | black/white | TRMNL polls the server |

Layouts: panels 160 pixels tall or less get the compact layout (one hero
number, a sparkline, one secondary number). Larger panels get three aligned
headline numbers over a grouped bar chart of views and visitors, and the
1872×1404 panel adds a detail rail computed only over the days the chart
actually drew.

Charts tell the truth about counts. The axis starts at zero, because a
floating baseline turns an ordinary week into a collapse and a recovery. A
positive count always draws at least one pixel. A series longer than the plot
is windowed to the most recent days that fit, and the caption names exactly
that window. Views are solid bars and visitors are striped bars, so a one-bit
panel can still tell them apart, and a legend names both.

Colour is never the only cue. Mono uses black. Four-colour panels use yellow
for structure and reserve red for the delayed-refresh warning. Spectra panels
use the provider's green for views and blue for visitors. An unknown provider
gets neutral ink rather than Jetpack's green.

On the sparse palettes, anti-aliasing is a correctness problem: a grey pixel
sits nearer red than black. Text there is drawn aliased and the logo's edge
alpha is snapped, so quantisation is a single nearest-colour pass with no
repair loop. Text is laid out with Pillow's basic engine rather than libraqm,
which not every Pillow wheel bundles, so a frame is byte-identical on every
interpreter and platform. `output.pixel_values` bridges Pillow 11's
`getdata()` and Pillow 12.1's `get_flattened_data()`; keep both paths.

Palette index order on the Inky panels is unverified. The code emits P-mode
indices in black, white, red, yellow, blue, green order and assumes the driver
consumes them as such.

## Hardware status

Nothing in this repository has driven a physical panel yet. The Inky adapter
exists, but the `inky` extra pulls a source-only `spidev` and NumPy, which
breaks the project's rule that everything installs from wheels on both
`armv7l` and `aarch64`. The Waveshare 4.26" driver is not published on PyPI at
all. Both adapters raise a clear error naming the next step. Treat `sop
display` as experimental until this section changes.

## Guardrails

- Never invent an endpoint field or coerce an unknown response into zero.
  Failing loudly beats publishing a plausible lie.
- Never rewrite `fetched_at` when serving cached data after a failure.
- Never hide a 401 or 403 behind the cache.
- Never let the renderer read configuration, the network, or hardware.
- Never make importing `sop` require GPIO or a vendor driver.
- Never clear an e-ink panel as part of error handling.
- Never claim a render profile as hardware support.
- Never log or commit tokens, client secrets, raw API responses, or real
  site data in fixtures.
- Keep `schema` the first key and the payload at the root level.
- Keep the fonts, raster logos, and `py.typed` in the wheel.

## Decisions not to reopen

- The repository is public, the default branch is `main`.
- Base runtime dependencies are Flask, Pillow, python-dotenv, and requests.
  No pandas, Matplotlib, browser renderer, or validation framework.
- Everything, extras included, must install from prebuilt wheels on `armv7l`
  and `aarch64`.
- No `omni-epd`: it is git-only, lacks the Waveshare 4.26", and the `Panel`
  protocol already is the abstraction it would provide.
- The default poll interval is an hour. Views are `stats` and `commerce`; the
  variable is `SOP_VIEW`, not "mode", which already means PIL output mode.
- `commerce.orders` stays on the wire beside `commerce.series`, because an
  older reader requires it and an older writer sends only it.
- TRMNL marketplace recipes must run without a third-party server or user
  authentication, and this project needs both. The deliverable is a private
  plugin template each person points at their own `sop serve`.
- Parse.ly is recognised in a snapshot and gets its own mark, but there is no
  Parse.ly fetch path. A future adapter needs a capability-aware contract,
  not Jetpack's likes and comments wearing a Parse.ly logo.
