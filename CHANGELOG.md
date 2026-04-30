# Changelog

## v1.5.0 (2026-04-29)
- The cache now uses OS-appropriate directories, segmented by package version. On Linux the
  default is `~/.cache/imf_reader/<version>/`; on macOS `~/Library/Caches/imf_reader/<version>/`;
  on Windows `%LOCALAPPDATA%\imf_reader\<version>\`. The version segment means upgrading the
  package automatically starts with a clean cache.
- Users on Linux who want to reclaim disk space from the old hardcoded cache can run
  `rm -rf ~/.cache/imf_reader/` after upgrading, or call `cache.set_cache_dir(...)` to keep
  using the previous location.
- A new environment variable `IMF_READER_CACHE_DIR` lets you override the cache location
  without changing code — useful on shared infrastructure or in CI.
- A new unified `imf_reader.cache` API replaces the scattered module-level helpers:
  `clear_cache(scope=...)`, `set_cache_dir`, `reset_cache_dir`, `get_cache_dir`,
  `enable_cache`, and `disable_cache`.
- WEO bulk SDMX downloads are now cached on disk and survive process restarts. A corrupted
  zip is detected automatically and evicted; retrying the same call re-downloads cleanly
  (`cache.BulkPayloadCorruptError` is raised so callers can handle it explicitly).
- SDR data (allocations and holdings, exchange rates, interest rates) now persists across
  process restarts, matching the behaviour WEO users already had.
- `weo.clear_cache()` and `sdr.clear_cache()` continue to work and emit a `DeprecationWarning`
  pointing at `cache.clear_cache()`. They will be removed in v2.0.

## v1.4.1 (2025-12-05)
- The new API implements a different scaling value behaviour. To preserve backwards compatibility, this new version 
aligns with the old behaviour.

## v1.4.0 (2025-12-05)
- The October 2025 release of WEO removed bulk downloads and moved everything towards the SDMX API. This update provides a way to parse new releases from the API instead of relying on the XML files. Note that thew new API response does not include observation-level notes or information on when projections start for each country-indicator.

## v1.3.0 (2025-2-05)
- Made function available to fetch latest holdings and allocations date
- Improved handling of unavailable dates

## v1.2.0 (2024-12-20)
- Add support for fetching Special Drawing Rights (SDR) data

## v1.1.0 (2024-10-11)
- Improved dtype handling for `fetch_data` function
- Improved error handling
- Improved logging

## v1.0.0 (2024-06-06)
- First stable release of `imf-reader` with full functionality for accessing WEO data

## v1.0.0b1 (2024-06-06)
- Beta release of `imf-reader` with full functionality for accessing WEO data

## v0.2.0 (2024-05-17)
- Basic functionality for accessing WEO data for initial testing

## v0.0.1 (2024-05-17)
- First release of `imf-reader`