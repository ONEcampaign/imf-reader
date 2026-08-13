# Changelog

## v2.0.1 (2026-08-13)

- Removed the `readerkit<0.2` upper bound. `readerkit` is a sibling package released in step with
  this one, so capping it only served to block installs the moment readerkit's next minor landed.
  The requirement is now `readerkit>=0.1.0`.
- No functional changes. The remainder of this release is tooling: ruff, ty and pre-commit
  configuration matching the rest of the bblocks family, dev dependencies consolidated onto PEP 735
  dependency groups, and refreshed GitHub Actions and build backend versions.

## v2.0.0 (2026-08-12)

- `weo.get_weo_versions()` now reports every WEO release this package can fetch — the API's
  dataflow mapping plus the discontinued bulk SDMX archive (April 2019 through April 2025) —
  instead of only the two versions the API currently exposes. It is now exported from
  `imf_reader.weo`. `get_weo_data(version=None)` is unaffected: it still resolves "latest" against
  the API mapping alone.
- April 2021 and October 2023 are corrupt in the IMF's own published SDMX archive and cannot be
  fetched by any means. `get_weo_versions()` omits them; fetching one raises
  `cache.BulkPayloadCorruptError` with `is_retryable=False` and an explanation. See the README's
  "Coverage and known issues" section.
- The pre-April-2025 historical path (the bulk SDMX archive) is fetchable again. In v1.5.0 the IMF
  put its download page behind bot management and every one of those eleven releases raised
  `ConnectionError`; `fetch_data` can now reach all of them.
- The bulk SDMX path and the API path now return the same identifier vocabulary. `REF_AREA_CODE`
  is ISO3 (e.g. `USA`) or a `G`-prefixed aggregate code (e.g. `G001`) on both paths, where the
  bulk path previously returned the legacy numeric area code. `UNIT_CODE`, `REF_AREA_LABEL`,
  `UNIT_LABEL`, and `CONCEPT_LABEL` now follow the API's vocabulary and codelists on both paths
  too. This is a breaking change for the bulk SDMX path.
- Rows with a null `OBS_VALUE` are now dropped on both paths. Historical row counts fall by
  roughly a third, and about 7 series-level notes are dropped along with the rows that carried
  them.
- `PPPGDP`, `PPPPC`, `PPPEX`, and `NGDPRPPPPC` now have a null `UNIT_CODE`, where the legacy data
  carried `T`, `F`, and `S`. This is deliberate, not a regression: the IMF's own API publishes no
  unit at all for these four PPP / "international dollar" concepts, and `CL_UNIT` has no code for
  "international dollar" to translate to.
- `LE`, `LP`, and `LUR` carry a `UNIT_CODE` (`PE`, `PT`) on releases served from the bulk archive
  (April 2019 to April 2025) and a null one on releases served from the API (April 2025 onward).
  The API publishes no unit for these concepts either, and the bulk archive's unit depends on the
  area as well as the concept, so it cannot be carried forward to areas the API adds later. Code
  that reads `UNIT_CODE` for population, employment, or unemployment should not assume it is
  populated across versions; `CONCEPT_CODE` and `CONCEPT_LABEL` are stable for these series.
- A new `REF_AREA_IMF_CODE` column is added on both paths, carrying the legacy numeric IMF area
  code for each row (null for areas that never had one, e.g. `LIE`). It's a compatibility column
  for code migrating off the numeric area code, and is slated for removal in 3.0.
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
- `weo.clear_cache()`, `weo.api.clear_cache()`, and `sdr.clear_cache()` survive this release. v1.5.0
  announced their removal in 2.0; they still work and still emit a `DeprecationWarning`, and the
  removal moves to 3.0 alongside `REF_AREA_IMF_CODE`.
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
