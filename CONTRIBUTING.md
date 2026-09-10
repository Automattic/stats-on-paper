# Contributing

Thanks for looking at Stats on Paper. This page covers how to set up, what
the checks are, and the few conventions that keep the project honest about
what it draws. The design itself is described in [ARCHITECTURE.md](ARCHITECTURE.md).

## Set up

You need Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```console
git clone https://github.com/Automattic/stats-on-paper.git
cd stats-on-paper
uv sync --locked
```

You do not need WordPress.com credentials to work on the code. The tests run
entirely offline and never read your `.env`.

## Run the checks

CI runs exactly these, on Python 3.11 and 3.13:

```console
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv lock --check
uv build
```

`uv run ruff format .` fixes formatting. Everything must pass before a pull
request is merged.

## Tests

- Write the test first, watch it fail, then make it pass.
- Tests are offline by construction: `tests/conftest.py` blocks
  `socket.connect` and stubs out `.env` loading. Do not add live API or
  hardware calls to the suite.
- `tests/fixtures/render-hashes.json` holds one hash per view and profile of
  the sample snapshot. Any change that alters a pixel fails that test, which
  is the point. If the change is intended, re-record in its own commit:

  ```console
  uv run python tests/record_render_hashes.py
  ```

  That also regenerates the preview images the README shows, so the two can
  never drift.
- Prefer a test that states a property ("a positive count always draws at
  least one pixel") over one that pins a coordinate.

## Adding things

**A panel profile.** Add it to `PROFILES` in `src/sop/render/palette.py` with
its native size, physical palette, dither setting, and output mode, then
re-record the render reference. A profile only proves the image is right for
that panel. A driver is separate work under `src/sop/panels/` and must be
imported lazily, so `import sop` never needs GPIO.

**A view.** Add a compact and a large body to `VIEWS` in
`src/sop/render/layout.py`. If the snapshot may not carry the data the view
needs, raise `UnsupportedView` in snapshot terms, and let the CLI translate
that into the setting to change.

**A data field.** Change `models.py` first, keep `schema` as the first key,
and update the sample fixture, the TRMNL templates, and the parser tests
together. An incompatible shape is schema 2, not a tolerant schema 1.

## Dependencies

The base runtime stays at Flask, Pillow, python-dotenv, and requests. The
target machines are Raspberry Pis, so everything, extras included, has to
install from prebuilt wheels on both `armv7l` and `aarch64`. Check that
before proposing a new dependency.

## Documentation

When behaviour changes, update whichever of these it touches in the same pull
request: `README.md`, `.env.example`, `CHANGELOG.md`, `ARCHITECTURE.md`, and
`trmnl/README.md`.

## Commits and pull requests

- Use [Conventional Commits](https://www.conventionalcommits.org/) in the
  imperative mood: `fix: keep the zero rule out of the bars`.
- Keep pull requests small and single-purpose. A visual change should come
  with a before-and-after preview.
- Never commit `.env`, a token file, a real snapshot, or raw API responses
  with real site data. Fixtures use invented sites.

## Security and licence

Report security problems as described in [SECURITY.md](SECURITY.md), not in
the issue tracker. Contributions are licensed under GPL-2.0-or-later, the same
as the project.
