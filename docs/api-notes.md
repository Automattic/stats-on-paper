# API notes

This is a working log. It records what was checked, how, and what still needs a
real token. Do not smooth over unknowns here.

## 2026-07-27 — verification environment

The initial checkout had no `WPCOM_CLIENT_ID`, `WPCOM_CLIENT_SECRET`,
`WPCOM_SITE`, token file, or `.env`. Authenticated `curl` calls therefore could
not be made without inventing credentials. The fixtures in this revision are
clearly marked contract fixtures: their shapes come from current public
documentation and the checked-out WordPress.com/Calypso source, while their
values are synthetic. Replace them with scrubbed captures before calling the
API integration empirically verified.

Run these after `jsp login --manual`; they print neither the token nor the
Authorization header:

```console
export JSP_TOKEN="$(python -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".config/jsp/token.json").read_text())["access_token"])')"
curl --fail-with-body --silent \
  -H "Authorization: Bearer $JSP_TOKEN" \
  "https://public-api.wordpress.com/rest/v1.1/sites/$WPCOM_SITE?fields=ID,name,URL"
curl --fail-with-body --silent \
  -H "Authorization: Bearer $JSP_TOKEN" \
  "https://public-api.wordpress.com/rest/v1.1/sites/$WPCOM_SITE/stats/summary?period=day&num=1&date=2026-07-27"
curl --fail-with-body --silent \
  -H "Authorization: Bearer $JSP_TOKEN" \
  "https://public-api.wordpress.com/rest/v1.1/sites/$WPCOM_SITE/stats/visits?unit=day&quantity=30&stat_fields=views%2Cvisitors"
curl --fail-with-body --silent \
  -H "Authorization: Bearer $JSP_TOKEN" \
  "https://public-api.wordpress.com/rest/v1.1/sites/$WPCOM_SITE/stats"
```

Before saving a response under `tests/fixtures/`, replace the site ID, domain,
URL, and any post/referrer data. Add `_fixture.capture_date` and keep the
endpoint, query, and site kind (`wordpress.com` or `jetpack`) beside it.

## OAuth

- Authorization endpoint:
  `https://public-api.wordpress.com/oauth2/authorize`.
- Token endpoint: `https://public-api.wordpress.com/oauth2/token`.
- Current official documentation lists `stats` as the narrow scope for site
  statistics. `jsp` requests only `stats` and supplies `blog`, producing a
  single-blog token rather than a global token.
- Current documentation's authorization-code token example contains
  `access_token`, `blog_id`, `blog_url`, and `token_type`. It shows no
  `expires_in` or `refresh_token`. That is documentation evidence, not an
  empirical claim that code-flow tokens never expire. The implicit flow is
  separately documented as expiring; `jsp` does not use it.
- The same documentation says `redirect_uri` must match the registered value
  exactly. That conflicts with a different ephemeral localhost port on every
  automatic login. `jsp login` implements the requested ephemeral callback,
  but it remains unverified. `jsp login --manual` uses the stable
  `WPCOM_REDIRECT_URI` and is the recommended path until a registered
  application confirms the localhost-port behavior.

## Site information

Request:

```text
GET /rest/v1.1/sites/{site}?fields=ID,name,URL
```

The public endpoint reference documents `ID` (integer), `name` (string), and
`URL` (string). The current client does not yet send `fields`; it accepts the
larger response and reads only those three keys.

## Daily summary

Request:

```text
GET /rest/v1.1/sites/{site}/stats/summary
    ?period=day&num=1&date=YYYY-MM-DD
```

The endpoint reference documents root-level `date`, `period`, `views`,
`visitors`, `likes`, `reblogs`, `comments`, and `followers`. `jsp` makes one
request for today and one for yesterday instead of assuming how `num=2` groups
periods. Missing numeric fields are treated as a response-shape error rather
than as zero.

## Visits series

Request:

```text
GET /rest/v1.1/sites/{site}/stats/visits
    ?unit=day&quantity=30&stat_fields=views,visitors
```

The older public endpoint page displays `/rest/v1/`, while current Calypso
requests API version `1.1`. The checked-out Calypso normalizer and tests show:

```json
{
  "fields": ["period", "views", "visitors"],
  "data": [["2026-07-27", 42, 27]],
  "unit": "day"
}
```

This version uses `v1.1`; the first authenticated capture must confirm the
version and whether day periods ever use the legacy `YYYYWMMWDD` spelling.

## All-time totals

Request:

```text
GET /rest/v1.1/sites/{site}/stats
```

The public reference only calls `stats` and `visits` arrays and does not
document their nested keys. The parser deliberately returns `all_time: null`
for an unknown shape. No plausible field names have been added. Capture this
response before expanding `parse_all_time`.

## WooCommerce counter

Optional request when `JSP_COMMERCE=true`:

```text
GET /wpcom/v2/sites/{site}/stats/orders
    ?unit=day&quantity=1&date=YYYY-MM-DD&stat_fields=orders
```

The checked-out WordPress.com endpoint implementation returns `fields` and
`data` arrays, with `period` always retained and `orders` included when
requested. It returns a service error for a non-Jetpack site or one without
synced WooCommerce tables. Those unsupported/store-less responses omit the
counter. A 401/403 still fails loudly.

## Unknowns to capture

- Rate-limit headers and practical limits.
- Whether the authorization-code token expires or has a refresh token.
- Day-boundary behavior around a DST change and whether `date` plus the site's
  default offset is enough.
- Fields absent versus explicitly zero on a new or quiet site.
- WordPress.com-hosted versus Jetpack-connected response differences.
- The exact all-time `stats` shape.
- Store-less WooCommerce status and body.

## Panel drivers

Pimoroni publishes `inky` as a platform-independent wheel, so
`pip install "jetpack-stats-on-paper[inky]"` is usable.

Waveshare's official `waveshare_epd.epd4in26` source is currently distributed
inside its Git repository, not as a compatible prebuilt PyPI wheel. The
third-party `waveshare-epaper` wheel does not list `epd4in26`. Adding a Git
dependency would violate this project's wheel-only installation rule.
Consequently the stable `[waveshare]` extra exists but is empty for now, and
the driver emits a precise error instead of silently installing an
incompatible package. This must be resolved before calling hardware support
done.

