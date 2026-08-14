# Changelog

## v2.1.0 (2026-08-14)

- **Raised the `pyarrow` floor to `pyarrow>=16.0`.** pyarrow 14 was built against numpy 1.x and
  cannot import alongside numpy 2 at all, which made every parquet cache write fail silently and
  turned the disk cache into a no-op. The `pandas` floor stays at `pandas>=2.2.2`: the package uses
  no pandas 3 API, and pandas 2.2.2 was checked against the live IMF API to return the same frame
  as pandas 3.0.5, with the same 16 columns in the same order, the same dtypes and the same values.
- The `dependency floors (lowest-direct)` CI job tested the newest resolution rather than the
  declared minimums, so the floors were never a tested claim. `uv run` re-resolves from the
  lockfile, so the step after `uv sync --resolution lowest-direct` reinstalled the newest versions
  before running the suite. It now runs `uv run --no-sync`.
- Fixed a latent crash in `utils._raise_connection_error`, which read `.status_code` off
  `HTTPError.response` without checking it for `None`.
- `weo.gen_latest_version()` now takes a single UTC reading of the clock instead of two local ones.
  The old form could pair a year with the next year's month if the two calls straddled midnight on
  31 December, and its answer depended on the caller's timezone.
- Security: refreshed the lockfile, clearing advisories in `soupsieve` (2.8.3 → 2.9.2),
  `urllib3` (2.6.3 → 2.7.0) and `idna` (3.13 → 3.18).
- The package now ships a `py.typed` marker, so downstream type checkers see its annotations
  instead of silently ignoring them.
- Removed the Codecov integration.
- The documentation site moved from Sphinx to MkDocs and was rewritten, and now covers WEO release
  coverage, the SDR argument-order trap, and the caching layer. It is published at
  <https://docs.one.org/tools/imf-reader/>.

### Corrected data

- `weo.fetch_data()` and `weo.fetch_data(("October", 2025))` both returned the same underlying
  data — the April 2026 release, labelled as October 2025. Version resolution keyed off a
  dataflow's `lastUpdatedAt` structure annotation, which is inverted on the IMF's live WEO
  dataflows, instead of reading `PUBLICATION_DATE` from the data itself.
  `fetch_data(("October", 2025))` now returns the actual October 2025 release, served from a
  separate `WEO_2025_OCT_VINTAGE` dataflow the IMF publishes for it: 354,240 rows (previously
  361,733), `TIME_PERIOD` reaching 2030 (previously 2031), and 35.1% of overlapping observations
  differ from what was previously returned by more than rounding — e.g. world real GDP growth for
  2025 is now 3.163, what the IMF actually published for the October 2025 WEO, not 3.441.
  `weo.get_weo_versions()` gains `("April", 2026)`, and `fetch_data()` with no argument now
  correctly resolves to it.
- If you're on an editable or git install, run `imf_reader.cache.clear_cache()` after upgrading.
  The cache directory is scoped by installed version; an editable/git install stays inside the same
  version segment across this change, so a cache entry written before this fix can otherwise keep
  serving the mislabelled data. If you have an extract saved to disk and labelled "October 2025",
  re-pull it — it may hold the April 2026 release under the wrong label. See
  [Caching](https://docs.one.org/tools/imf-reader/caching/) for detail.

### New and repaired columns

- `LASTACTUALDATE` and `NOTES`, previously always null on every API-served release (April 2025
  onward), are now populated. `LASTACTUALDATE` comes from a per-series metadata sidecar's
  `LATEST_ACTUAL_ANNUAL_DATA` field; fiscal-year forms such as `FY2023/24` are collapsed to their
  leading year, `2023` (about 10.7% of series) — this discards the fiscal-year distinction rather
  than encoding it, and there's no way back from `LASTACTUALDATE` alone (see "Known gotchas"
  below). `NOTES` comes from the same sidecar's `METHODOLOGY_NOTES` field, which is different free
  text from the bulk archive's `NOTES` column.
- A new column, `COUNTRY_UPDATE_DATE` (`datetime64[us]`), carries the date each country's data was
  last revised. It's populated on API-served releases and always null on bulk-archive releases (the
  bulk archive's XML carries no per-country revision date). It's appended after `SCALE_LABEL`, so
  the first 15 columns, and any positional access to them, are unaffected.
- If the metadata sidecar request fails, all three columns fall back to null for that call and a
  warning is logged, rather than failing the fetch.

### Known gotchas

- **`LASTACTUALDATE`'s fiscal-year mapping is lossy and one-way.** `FY2023/24` becomes `2023`,
  and the fiscal-year distinction is gone — not encoded, not recoverable from this column. Don't
  read `2023` as "reported as of calendar year 2023"; the leading-year convention only
  approximates that. If the fiscal-year boundary matters, read
  `START_END_MONTHS_OF_REPORTING_YEAR` from the IMF API directly — this package does not expose
  it.
- **`NOTES` silently mixes two vocabularies across the April 2025 boundary, with no column to tell
  them apart.** Before April 2025 it's the bulk archive's `NOTES`; from April 2025 it's the API's
  `METHODOLOGY_NOTES` — different free text, describing different things. None of the 16 columns
  marks the boundary. We're deliberately not adding a provenance column for this release. If you
  concatenate releases and do text search, deduplication, or NLP over `NOTES`, split on the
  release version you requested (or `weo.fetch_data.last_version_fetched`) first, rather than
  treating `NOTES` as one corpus.

### Other behaviour changes

- `fetch_data(version)` called with an explicit version now raises if the API can't serve it,
  instead of silently falling back and returning a different release under the requested label.
  The automatic roll-back (serving a previous release when the latest one has no data yet) now only
  happens for `fetch_data()` called with no version. It walks the actually-published version list
  from `get_weo_versions()` instead of guessing a previous release from the calendar, is capped at
  3 attempts, and logs each attempt at `warning` instead of `info`.
- Cache entries are now written atomically, so a partially-written entry can no longer poison the
  cache. A cache entry that fails to read is now treated as a miss and removed, rather than failing
  every subsequent call until a manual `clear_cache()`.
- Bulk-archive observations published as `--` (below display precision, not zero) continue to be
  dropped rather than written as `0.0` or flagged with a status column; the count dropped is now
  logged at `debug`.
- A dataflow catalogue that responds successfully but carries no usable WEO dataflow now raises
  `DataflowDiscoveryError`. Previously that response produced an empty version mapping, which was
  cached for an hour, and `fetch_data()` resolved "latest" against the bulk archive instead and
  returned April 2025 under that label. An explicit version still falls back to the bulk archive,
  which serves the requested release under its own correct label, and logs a warning saying so.
- Series metadata and observations are cached independently. A failed sidecar request used to be
  written into the 7-day observations cache, so `LASTACTUALDATE`, `NOTES` and `COUNTRY_UPDATE_DATE`
  stayed null for a week and the warning fired only on the first call. The join now happens outside
  that cache, so a failed sidecar costs only the call that hit it.
- Removing an unreadable cache entry no longer fails the call. On a read-only or shared cache
  directory the removal raised `PermissionError` out of the cache layer, so a recoverable cache
  miss became a hard error. The failure is logged and the live fetch proceeds.
- `sdr.fetch_latest_allocations_holdings_date()` raises `ValueError` naming the page and the layout
  it expected when the IMF changes that page. It previously indexed into the fifth table and the
  second row unguarded, so a layout change surfaced as a bare `IndexError` that named neither.
- Labelling the four legacy-only aggregates no longer emits a pandas `FutureWarning` on pandas 2,
  which mattered to anyone running with warnings as errors.

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
