# Changelog

## v1.6.0 (2026-08-11)

- `imf-reader` now requires Python 3.12 or later. Users on Python 3.10 or 3.11 keep resolving to
  the 1.5.x series.
- The default cache directory moves to a shared `readerkit` root: `~/.cache/readerkit/v1/imf-reader/<version>/`
  on Linux, `~/Library/Caches/readerkit/v1/imf-reader/<version>/` on macOS, and
  `%LOCALAPPDATA%\readerkit\Cache\v1\imf-reader\<version>\` on Windows. Users on Linux who want to
  reclaim disk space from the old directory can run `rm -rf ~/.cache/imf_reader/` after upgrading.
- A new environment variable `BBLOCKS_CACHE_DIR` provides a family-wide fallback cache location,
  used when `IMF_READER_CACHE_DIR` is not set. Useful for pointing several packages at one shared
  cache root.
- HTTP requests now carry a default timeout and retry with backoff on transient failures and
  server errors.
- WEO bulk SDMX downloads now stream to disk and verify the transfer against the response's
  `Content-Length` header.
- The cache directory now uses readerkit's native file lock by default, instead of the
  `SoftFileLock` that `imf-reader` 1.5.0 always used. On a filesystem that rejects native locks,
  such as an NFS mount, readerkit raises `CacheLockUnavailable` and names the fix in the error.
  Set `READERKIT_LOCK_STRATEGY=strict-soft` to restore marker-file locking.
- A failed fetch can now raise `ArtifactWriteError`, `CacheLockTimeout`, `CacheLockUnavailable`,
  `TruncatedDownloadError`, `SessionForkError`, `CacheDirectoryError`, or `RedirectPolicyError`
  from the underlying caching library, in addition to the exceptions `imf-reader` already raised.
- The public `imf_reader.cache` API is otherwise unchanged.

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
