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
extensions, so admonitions (`!!! note`, etc.) appear as literal `!!!` text. The full
rendering happens on docs.one.org, which supplies the theme and extensions.

## Structure

- `mkdocs.yml` - MkDocs configuration, included by the central site via the monorepo plugin
- `docs/` - all markdown content

## Publishing

`ONEcampaign/docs` sparse-clones this repo's `docs/` directory and includes
`docs/mkdocs.yml` through the mkdocs monorepo plugin. It reads whatever is on `main`
here at the time it builds, and it builds on pushes to its own `main`. Changes merged
here appear at https://docs.one.org/tools/imf-reader/ on the next build of that repo.
