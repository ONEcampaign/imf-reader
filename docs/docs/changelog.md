# Changelog

The full version history lives in [`CHANGELOG.md`](https://github.com/ONEcampaign/imf-reader/blob/main/CHANGELOG.md) in the repository, generated from [Conventional Commits](https://www.conventionalcommits.org/) on every release.

`imf-reader` follows [semantic versioning](https://semver.org/). A major version bump means breaking changes, a minor version adds functionality without breaking existing calls, and a patch version fixes bugs.

## What's changing in 3.0

Two things change when 3.0 ships:

- The deprecated `weo.clear_cache()`, `weo.api.clear_cache()`, and `sdr.clear_cache()` helpers are removed. Use `cache.clear_cache(scope=...)`, see [Caching](caching.md).
- The `REF_AREA_IMF_CODE` column is removed from WEO frames.

## Next steps

- [Caching](caching.md) - the replacement for the deprecated `clear_cache()` helpers
- [World Economic Outlook](weo.md) - the `REF_AREA_IMF_CODE` column and what replaces it
