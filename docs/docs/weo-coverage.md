# WEO coverage and known issues

`imf_reader.weo` reads WEO data from two sources. Both carry permanent limits, and those
limits fall on specific releases and specific columns.

## Two sources, joined at April 2025

The api.imf.org SDMX 3.0 API serves April 2025 onward. A discontinued bulk SDMX zip archive,
published on the IMF website, serves April 2019 through April 2025, thirteen releases in total.
The IMF stopped publishing the bulk archive after April 2025.

April 2025 is the one release available from both sources. The test suite pins their agreement
directly: `test_april_2025_matches_across_both_paths` in `tests/test_weo/test_schema_parity.py`
asserts the two paths produce matching data for that release.

!!! info "Why"

    The two sources use different native schemas. The API serves observations as CSV keyed on its
    own area and unit codes. The bulk archive holds an older SDMX XML layout, keyed on legacy numeric area
    codes and a different unit vocabulary. `imf_reader` translates both onto the API's vocabulary
    before returning a frame, so a query written against `fetch_data()` output works the same
    regardless of which source answered it.

## One vocabulary across the join

`REF_AREA_CODE` is ISO3 (`NGA`) or a `G`-prefixed aggregate (`G001`) on both paths.
Bulk-archive releases start out keyed on legacy numeric area codes, and `imf_reader` maps each
one onto the matching ISO3 or aggregate code before returning the frame. `UNIT_CODE` and every
label column (`REF_AREA_LABEL`, `CONCEPT_LABEL`, `UNIT_LABEL`, `FREQ_LABEL`, `SCALE_LABEL`) are
re-derived from the same IMF codelists the API path reads, on both paths, keeping wording
identical across the two paths. Rows with a null `OBS_VALUE` are dropped on both paths.

Because column names, order, and codes match across the join, frames from different releases
concatenate with `pd.concat` without reindexing.

## The two corrupt releases

April 2021 and October 2023 are corrupt in the IMF's own published bulk archive. The CRC-32 of
the inner XML doesn't match, and re-downloading reproduces identical bytes, a stable SHA-256
matching `Content-Length`. This rules out a transit or caching problem on this package's end.
The corruption is at the IMF's source, and it can't be fetched by any means.

`weo.get_weo_versions()` omits both releases from its result. Requesting either one directly
raises `cache.BulkPayloadCorruptError` with `is_retryable=False`, so retry logic can
distinguish this from an ordinary network failure and stop.

!!! warning "Heads up"

    `fetch_data(("April", 2021))` and `fetch_data(("October", 2023))` always raise
    `cache.BulkPayloadCorruptError`. The corruption is permanent at the IMF's source, so no retry
    or cache clear recovers it.

## Units that are absent or inconsistent

Four PPP concepts have a null `UNIT_CODE` on every release: `PPPGDP`, `PPPPC`, `PPPEX`,
`NGDPRPPPPC`. The IMF's `CL_UNIT` codelist has no code for "international dollar", so there is
no unit to map these four concepts to, on the API or the translated bulk-archive rows.

`LE`, `LP`, and `LUR` carry a `UNIT_CODE` (`PE` or `PT`) on bulk-archive releases and a null
one on API releases. A filter on `UNIT_CODE` for these three concepts matches releases before
April 2025 and misses everything from April 2025 onward. When working across versions for
population, employment, or unemployment, read `CONCEPT_CODE` or `CONCEPT_LABEL` instead.

## Observations published as `--`

In the bulk archive, the IMF marks roughly 1,200 observations per release with the token `--`,
its convention for "zero, or less than half the final digit shown" rather than a true zero. A
deflator or index cell reading `--` one year and a tiny value like `0.002` the next is common; the
`--` is a rounding artefact, not a report of zero. `imf_reader` does not write `0.0` for these
cells and does not add a status column to flag them, because either choice would create a
permanent public column for a discontinued, 0.3%-of-cells archive. Instead, rows carrying `--` in
`OBS_VALUE` are dropped, same as any other null observation, and the count dropped for that reason
is logged at `debug`. The API path has no such cells either: every release from April 2025 onward
simply omits the observation rather than marking it `--`, so the two paths agree once the drop is
applied.

## `LASTACTUALDATE` and `NOTES` come from different fields on each path

`LASTACTUALDATE` and `NOTES` are populated on both paths, but from different underlying fields.
On the bulk archive path, both come from the XML series attributes of the same name. On the API
path, `LASTACTUALDATE` comes from a per-series metadata sidecar's `LATEST_ACTUAL_ANNUAL_DATA`
field, and `NOTES` comes from the same sidecar's `METHODOLOGY_NOTES` field. `METHODOLOGY_NOTES`
and the bulk archive's `NOTES` are different free text describing different things.

`LATEST_ACTUAL_ANNUAL_DATA` is not always a plain year. About 10.7% of populated series carry a
fiscal-year form, `FY2023/24`, and `imf_reader` maps it to `2023`, its leading year. This is a
one-way, lossy mapping: the fiscal-year distinction is discarded, not encoded, and there is no
way to recover it from `LASTACTUALDATE`. If you're reconciling against the IMF's own published
metadata, don't read `2023` as "reported as of calendar year 2023" — the leading-year convention
only approximates that. If the fiscal-year boundary matters to your use case, read
`START_END_MONTHS_OF_REPORTING_YEAR` from the IMF API directly; `imf_reader` does not expose it.
The bulk archive's `LASTACTUALDATE` has no fiscal-year forms at all, so mapping to the leading
year is what keeps `LASTACTUALDATE` comparable across the two paths.

No column in the 16 marks which vocabulary a row's `NOTES` came from. If you concatenate releases
across the April 2025 boundary and run text search, deduplication, or NLP over `NOTES`, you will
silently mix two unrelated vocabularies with no signal to separate them. Split on the release
version you requested (or `weo.fetch_data.last_version_fetched`) before treating `NOTES` as one
corpus.

If the metadata sidecar request fails, `LASTACTUALDATE`, `NOTES`, and `COUNTRY_UPDATE_DATE` (see
[World Economic Outlook](weo.md) for that column) fall back to null for that call, and a warning
is logged. This degrades to less information rather than failing the whole fetch.

## `REF_AREA_IMF_CODE`

`REF_AREA_IMF_CODE` is a compatibility column carrying the legacy numeric IMF area code for
each row. On a bulk-archive release it is the original code the row was published under, before
translation to ISO3. On an API release it is looked up from the same mapping in reverse, and is
null where an area never had a legacy numeric code, for example `LIE`.

The column exists to give code still keyed on the numeric code a one-line migration path onto
`REF_AREA_CODE`. It is removed in 3.0. New code should key on `REF_AREA_CODE` directly.

## Next steps

- [World Economic Outlook](weo.md) - fetch releases, filter the frame, and look up the full column reference
- [Caching](caching.md) - how corrupt-release detection interacts with the disk cache
- [Special Drawing Rights](sdr.md) - the other IMF dataset this package reads
