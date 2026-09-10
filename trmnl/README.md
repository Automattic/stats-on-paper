# Jetpack Stats on a TRMNL

TRMNL renders these templates on its own servers from JSON your `jsp serve`
publishes, so the device needs no hardware work and no code from this
repository. This is the zero-soldering path in the tutorial.

## What you need

1. **A reachable `jsp serve`.** TRMNL's servers fetch the URL, so it must be
   public and HTTPS. Put a real proxy in front of `jsp serve`; it is Flask's
   development server. Set `JSP_SERVE_TOKEN` — without it the app refuses to
   bind to anything but localhost.
2. **TRMNL Developer Edition**, which is what unlocks private plugins. It is
   reached by adding the developer add-on to an existing device, by choosing
   the Developer edition when you buy one, or under a BYOD licence.

## Set up the private plugin

In TRMNL: **Plugins → Private Plugin → Create**.

| Field | Value |
| --- | --- |
| Strategy | `Polling` |
| Polling URL | `https://your-host/v1/stats.json` |
| Polling Header | `Authorization=Bearer YOUR_JSP_SERVE_TOKEN` |
| Refresh rate | 15 minutes or longer |

The header value is compared exactly, so the lowercase `bearer` in TRMNL's own
example returns 401. Capital B.

The figures are daily. Polling faster than 15 minutes costs battery and shows
you the same numbers; hourly is a reasonable choice.

Paste `tests/fixtures/sample-stats.json` into the plugin editor as sample data
to preview the layouts before pointing it at your own site.

## The templates

Paste `shared.liquid` into the plugin's **Shared** box; TRMNL prepends it to
every view before rendering, which is what lets `full` and `half_horizontal`
call `{% render "chart", series: series %}`. Then copy each remaining file into
its matching markup box.

| File | TRMNL box |
| --- | --- |
| `shared.liquid` | Shared |
| `full.liquid` | Full |
| `half_horizontal.liquid` | Half horizontal |
| `half_vertical.liquid` | Half vertical |
| `quadrant.liquid` | Quadrant |

They read the JSON's root keys directly (`today`, `series`, `site`, `source`,
and `commerce` when your site has a store). The daily chart is inline-styled
flexbox built from `series`, with no chart library and no JavaScript: TRMNL's
framework ships layout and typography classes but nothing for charts, so the
bars carry their own styling.

The only TRMNL-supplied filter these templates use is `number_with_delimiter`,
which puts the thousands separator in `1,842`. `tests/test_trmnl_templates.py`
registers exactly that one, and Liquid raises on any filter it has not been
given, so reaching for a second TRMNL filter fails the test until it is
registered there and named here.

## The commerce screen

There is no second template family for orders. Point a TRMNL image plugin at
`/v1/screen.png?panel=trmnl&view=commerce`, which serves the same 800×480
frame the e-ink panels draw.

## Publishing this as a recipe

Not eligible, and not planned. TRMNL's marketplace recipes are meant to run
without a third-party server or user authentication; this one needs both — your
own host and your own token. Share the template files instead: each person
points a private plugin at their own `jsp serve`.
