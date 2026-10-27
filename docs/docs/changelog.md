---
description: Where to find the imf-reader version history, how its version numbers work, and what the 3.0 release removes.
---

# Changelog

The full version history lives in [`CHANGELOG.md`](https://github.com/ONEcampaign/imf-reader/blob/main/CHANGELOG.md) in the repository, generated from [Conventional Commits](https://www.conventionalcommits.org/) on every release.

`imf-reader` follows [semantic versioning](https://semver.org/). A major version bump means breaking changes, a minor version adds functionality without breaking existing calls, and a patch version fixes bugs.

## What's changing in 3.0

Three things change when 3.0 ships:

- The deprecated `weo.clear_cache()`, `weo.api.clear_cache()`, and `sdr.clear_cache()` helpers are removed. Use `cache.clear_cache(scope=...)`, see [Caching](caching.md).
- The `REF_AREA_IMF_CODE` column is removed from WEO frames.
- `imf_reader.config.logger` is removed. WEO and SDR modules log under their own names, such as `imf_reader.weo.api`, so configuring the `imf_reader.config` logger by name stops affecting their messages. Configure the `imf_reader` logger instead, see [See progress messages](getting-started.md#see-progress-messages).

## Next steps

- [Caching](caching.md) - the replacement for the deprecated `clear_cache()` helpers
- [World Economic Outlook](weo.md) - the `REF_AREA_IMF_CODE` column and what replaces it
