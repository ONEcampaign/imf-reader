# imf-reader documentation

This directory holds the MkDocs documentation for imf-reader.

## Building locally

Install dependencies from the project root:

```bash
uv sync --group docs
```

Serve locally:

```bash
cd docs
uv run mkdocs serve
```

Visit http://127.0.0.1:8000

A bare local `mkdocs serve` renders without the Material theme and its markdown
extensions, so admonitions (`!!! note`, etc.) appear as literal `!!!` text. They become
callouts on developmentfinance.org, whose build converts them to GitHub alerts.

## Structure

- `mkdocs.yml` - MkDocs configuration, read by the developmentfinance.org build as the nav for these pages
- `docs/` - all markdown content

## Publishing

The pages are published at https://developmentfinance.org/docs/tools/imf-reader. The
`DevelopmentFinanceObservatory/docs` build lists this repo in `sources.yaml` as `imf-reader`,
with the path `tools/imf-reader`. It reads `docs/mkdocs.yml` as the nav for these pages and
raises on a nav entry it cannot resolve to a file. It converts `!!!` admonitions to GitHub
alerts and expects the body indented 4 spaces.

A change merged to `main` here appears on developmentfinance.org after the Development
Finance Observatory corpus rebuild, which runs daily at 06:00 UTC and on a push to its `dev`
branch, and after the website moves its docs pin.
