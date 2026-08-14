# Why imf-reader

## The problem

The World Economic Outlook (WEO) database lives in two places with two different shapes. The
IMF's SDMX API serves releases from April 2025 onward. Everything from April 2019 through April
2025 exists only in a bulk SDMX archive, which the IMF discontinued after the April 2025
release. The two systems use different area codes and different column layouts for the same
indicators. A script written against one breaks against the other.

A WEO time series spanning 2019 to today draws on both systems, the bulk archive for the early
years and the API for the recent ones, each with its own area-code and unit-code vocabulary.
Something has to reconcile them before the series is usable.

The daily SDR valuation and the weekly interest rate have no API at all; the IMF publishes only
HTML pages built for a browser. Allocations and holdings do exist on the IMF's API at monthly
frequency, but this package parses them from HTML too. All four Special Drawing Rights (SDR)
series, holdings, allocations, exchange rates, and interest rates, are parsed from HTML. Page
structure, class names, and table layout change whenever the IMF redesigns the site.

Both surfaces are volatile. The bulk archive already contains two corrupted releases, April 2021
and October 2023, that fail a CRC-32 check on every re-download. The IMF's codelists have changed
between releases, and per-series metadata such as the last actual date and revision notes lives
behind a separate request that can fail on its own, independently of the main data fetch.

## What this package does about it

For WEO, `imf-reader` translates both sources onto one vocabulary at the April 2025 join.
`REF_AREA_CODE` is ISO3 or a `G`-prefixed aggregate on both paths, and `UNIT_CODE` and the label
columns follow the API's own codelists on both paths too. A query spanning 2019-2025 uses the
same column names and the same codes throughout, with no branch for which system served which
year.

Every fetch is cached to disk. If the IMF's SDR pages are unreachable or the API returns an
error, already-cached data keeps working. Requesting the latest release when the IMF has not
published it yet triggers a bounded rollback. `fetch_data()` walks the published releases
newest-first and tries up to three of them, logging each attempt as a warning. Requesting a
specific release always resolves to that release or raises. If the API can't serve it,
`fetch_data` falls back to the bulk archive for that same release before raising. The two corrupt bulk
releases behave differently. Fetching one raises `cache.BulkPayloadCorruptError`, flagged
`is_retryable=False` so a retry loop can skip it.

All output is typed pandas, with nullable `Int64`, `Float64`, and `string` dtypes throughout,
ready for filtering and arithmetic without a casting step.

## Alternatives

**[weo-reader](https://github.com/epogrebnyak/weo-reader)** is the established package for WEO
specifically. It predates `imf-reader` and carries deeper WEO-specific tooling. For advanced WEO
work, such as unit conversion or working exclusively with the most recent release, weo-reader is
worth using directly. Its scope is WEO only.

**Downloading files by hand from imf.org** works for a one-off release. It gives full control
over exactly which file and format you get, with no dependency on this package's parsing or
caching logic. It suits a single release fetched by a person. Automating it across many releases
means writing and maintaining that script yourself.

## Limitations

- SDR parsing depends on the current structure of IMF web pages. A redesign of those pages can
  break `sdr.fetch_*` until the parser is updated.
- The bulk WEO archive ends at April 2025, the release after which the IMF discontinued it. Two
  of its releases, April 2021 and October 2023, are permanently corrupt and cannot be fetched by
  any means.
- `NOTES`, `LASTACTUALDATE`, and `COUNTRY_UPDATE_DATE` on API-era releases come from a separate
  per-series metadata request. If that request fails, all three columns come back null for that
  call. See [WEO coverage and known issues](weo-coverage.md) for the full column reference.
- WEO frequency is annual, one release each in April and October. There is no quarterly or
  monthly WEO data to fetch.

## When to use it

- A pipeline or notebook needs WEO indicators spanning both the API era and the bulk-archive era
  in one call.
- SDR holdings, allocations, exchange rates, or interest rates need to arrive through one function
  call, with the package owning the HTML parsing.
- The same fetch runs repeatedly and has to survive a slow or unavailable IMF endpoint.
- Typed pandas output (nullable `Int64`, `Float64`, and `string` dtypes) is needed without a
  separate casting step.

## Next steps

- [Getting started](getting-started.md) - install the package and run a WEO and an SDR query
- [World Economic Outlook](weo.md) - filtering, indicators, and the full WEO reference
- [Special Drawing Rights](sdr.md) - fetch holdings, allocations, exchange rates, and interest
  rates
