# Stats on a TRMNL

`sop push` draws your stats for your TRMNL model and uploads the picture to
TRMNL's **Webhook Image** plugin. The device shows the same layout, chart, and
Jetpack or Parse.ly branding as every other panel this project supports.
Nothing on your network has to be reachable from the internet, and the device
needs no code from this repository.

> **Status:** the pictures match each model's published size and inks, and
> TRMNL's upload API has been followed to the letter, but no TRMNL has shown
> one yet. Tell us how it goes in an
> [issue](https://github.com/Automattic/stats-on-paper/issues).

![The stats screen as the four-colour TRMNL OG shows it](../assets/previews/trmnl-bwry.png)

## What you need

1. **Stats on Paper, installed and logged in.** Follow "Install" and "Connect
   your site" in the [main README](../README.md). You are ready when
   `uv run sop fetch` prints your numbers.
2. **A TRMNL**, any model in the table below.
3. **A computer that is on most of the day.** The screen only changes when
   that computer sends a new picture. A Mac, a Linux machine, or a Raspberry
   Pi all work.
4. **On a Mac, the `stats-on-paper` folder outside Documents, Desktop, and
   Downloads.** macOS does not let scheduled jobs read those folders, and step
   4 would fail without telling you. If you cloned it there, move the folder
   to your home folder, then run `uv sync --locked` inside it.

| Your TRMNL | `SOP_PANEL` | Picture |
| --- | --- | --- |
| TRMNL OG, black and white | `trmnl` | 800×480, black and white |
| TRMNL OG, black, white, red, and yellow | `trmnl-bwry` | 800×480, four colours |
| TRMNL X | `trmnl-x` | 1872×1404, sixteen greys |

## 1. Add the Webhook Image plugin

In TRMNL, go to **Plugins**, open **Webhook Image**, and choose **Add to my
plugins**. Give it a name, such as `Stats on Paper`, and save.

The plugin's settings now show a **Webhook URL**. Keep it to yourself: anyone
who has it can change what your TRMNL shows.

## 2. Connect `sop` to the plugin

Open `.env` in the `stats-on-paper` folder. Find these three lines and fill
them in. If one is not there, add it at the end of the file.

```ini
SOP_TRMNL_WEBHOOK_URL=https://trmnl.com/api/plugin_settings/.../image
SOP_PANEL=trmnl-bwry
SOP_TZ=Europe/Madrid
```

- `SOP_TRMNL_WEBHOOK_URL` is the whole Webhook URL from step 1.
- `SOP_PANEL` is your model, from the table above. TRMNL shows the picture
  exactly as it is sent, so it has to match your device.
- `SOP_TZ` is your site's timezone, so "today" starts when your site's day
  does. The list of names is on
  [Wikipedia](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones).

Then send your stats once:

```console
uv run sop push
```

It prints something like
`Sent the trmnl-bwry screen for example.com to TRMNL: numbers from 2026-11-20 13:59 UTC, 3,380 bytes.`

## 3. See it on the screen

TRMNL puts a new plugin on your device's playlist. Your TRMNL shows the
picture the next time it wakes and reaches this plugin, which depends on the
refresh rate set for the device in TRMNL. Show it as a full-screen item, not
inside a mashup, where TRMNL would have to shrink it.

## 4. Keep it up to date

The numbers are daily totals, so a new picture once an hour is plenty. On a
Mac or Linux machine, run this once, from the `stats-on-paper` folder:

```console
(crontab -l 2>/dev/null | grep -v '# stats-on-paper'; echo "17 * * * * '$PWD/.venv/bin/sop' push >> '$PWD/push.log' 2>&1 # stats-on-paper") | crontab -
```

From then on, your computer sends a new picture at 17 minutes past every hour
while it is awake. Running the line again replaces the schedule rather than
adding a second one. If the folder's path contains an apostrophe (`'`) or a
percent sign (`%`), move the folder first; the schedule cannot run from there.

Check the first scheduled run: after 17 minutes past the hour, open
`push.log` in the `stats-on-paper` folder. Its last line should begin with
`Sent the` and give a time from the last hour. Every run adds a line, so the
file also shows when anything went wrong.

To stop the schedule:

```console
crontab -l | grep -v '# stats-on-paper' | crontab -
```

## What the screen shows

Today's views, visitors, and views per visitor over a chart of the last 30
days. The TRMNL X adds a row with yesterday's views, today's likes and
comments, and either today's orders (with `SOP_COMMERCE=true`) or the busiest
day in the chart. The footer says `Updated 13:59 UTC · 20 Nov`, when `sop`
fetched those numbers.

If your computer is off or asleep, TRMNL keeps showing the last picture, and
that time tells you how old it is.

If `sop` cannot reach WordPress.com for more than two hours, it sends the last
numbers it has and the footer says `Refresh delayed · 13:59 UTC · 20 Nov`
instead, still with the time those numbers were fetched. On the four-colour OG
that warning is red. `push.log` says why: each run that used older numbers
adds a line starting `WARNING: Could not fetch fresh stats`.

To show orders instead, set `SOP_VIEW=commerce` (it needs
`SOP_COMMERCE=true`), or run `uv run sop push --view commerce`.

## If something goes wrong

`sop push` says what went wrong and what to change. The messages you are
most likely to see:

| Message | What to do |
| --- | --- |
| `Missing SOP_TRMNL_WEBHOOK_URL` or `Missing SOP_PANEL` | Do step 2. |
| `SOP_TRMNL_WEBHOOK_URL must start with https://` | Copy the whole Webhook URL again, including `https://`. |
| `TRMNL does not recognise that address`, `TRMNL answered with a redirect`, or `not a usable address` | Copy the Webhook URL again from the Webhook Image plugin's settings. |
| `SOP_PANEL is ..., which is not a TRMNL model` | Set `SOP_PANEL` to `trmnl`, `trmnl-bwry`, or `trmnl-x`. |
| `TRMNL accepts a push about 12 times an hour` | Something is running `sop push` too often. Once an hour is enough. |
| `Could not reach TRMNL` or `TRMNL refused the upload (403)` | Wait for the next run. If it keeps happening, check this computer's internet connection. |
| `WARNING: Could not fetch fresh stats` | `sop` sent the last numbers it had. Run `uv run sop fetch` to see the problem with WordPress.com. |
| `No token found at ...` | Run `uv run sop login --manual` from the main README. |

If the screen looks wrong, for example cut off or in the wrong colours, check
that `SOP_PANEL` matches your TRMNL. To look at the exact picture `sop push`
sends, run `uv run sop render -o out.png` and open `out.png`.

## Polling with Liquid templates

The `.liquid` files here are a separate, simpler design that TRMNL draws on
its own servers from `sop serve`'s JSON. They are for people who already run
`sop serve` behind HTTPS on a public address. Create a private plugin (this
needs the Developer edition) with the Polling strategy, set the polling URL to
`https://your-host/v1/stats.json`, and add the header
`Authorization=Bearer YOUR_SOP_SERVE_TOKEN` (capital B). Paste each file into
the markup box with the same name: `shared.liquid` into Shared, `full.liquid`
into Full, and so on.

TRMNL wraps each layout in its own `view` element and applies the screen's
size, bit depth, and colour classes itself, so the markup uses only framework
classes. The chart fills whatever height the numbers leave (`stretch-y` in a
`layout--col`), and the delayed warning is `text--red` with `1bit:`, `2bit:`,
and `4bit:` overrides to black.

`tests/test_trmnl_templates.py` renders every layout against the real payload
with a strict Liquid engine, and checks two rules from TRMNL's recipe linter:
no `view--*` wrapper in the markup, and no more than six inline style
declarations in all. The only TRMNL-supplied filter the templates use is
`number_with_delimiter`; the test registers exactly that one, so reaching for
a second fails the test until it is registered there and named here.
