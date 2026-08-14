# World Economic Outlook

The World Economic Outlook (WEO) is the IMF's database of macroeconomic projections and estimates, released every April and October. The `weo` module fetches a release as a single pandas DataFrame.

## Fetch the latest release

```python
from imf_reader import weo

df = weo.fetch_data()
df.shape
```

**Output:**

```
(361733, 16)
```

```python
df.head(3)
```

**Output:**

```
  UNIT_CODE CONCEPT_CODE REF_AREA_CODE  REF_AREA_IMF_CODE FREQ_CODE  LASTACTUALDATE  SCALE_CODE NOTES  TIME_PERIOD  OBS_VALUE UNIT_LABEL                                           CONCEPT_LABEL                     REF_AREA_LABEL FREQ_LABEL SCALE_LABEL COUNTRY_UPDATE_DATE
0       USD          BCA           ABW                314         A            2024  1000000000  <NA>         1999  -0.435363  US dollar  Current account balance (credit less debit), US dollar  Aruba, Kingdom of the Netherlands     Annual    Billions          2025-09-19
1       USD          BCA           ABW                314         A            2024  1000000000  <NA>         2000   0.212542  US dollar  Current account balance (credit less debit), US dollar  Aruba, Kingdom of the Netherlands     Annual    Billions          2025-09-19
2       USD          BCA           ABW                314         A            2024  1000000000  <NA>         2001   0.310076  US dollar  Current account balance (credit less debit), US dollar  Aruba, Kingdom of the Netherlands     Annual    Billions          2025-09-19
```

## Fetch a specific release

```python
from imf_reader import weo

df = weo.fetch_data(("April", 2024))
```

The `version` argument is a `(month, year)` tuple, month first. The month must be `"April"` or `"October"`, matching the IMF's twice-yearly release schedule. An invalid version raises `NoDataError`. See [Errors](#errors) below for where to import it from and what else `fetch_data` can raise.

## List available releases

```python
from imf_reader import weo

weo.get_weo_versions()
```

**Output:**

```
[('April', 2026), ('October', 2025), ('April', 2025), ('October', 2024), ('April', 2024), ('April', 2023), ('October', 2022), ('April', 2022), ('October', 2021), ('October', 2020), ('April', 2020), ('October', 2019), ('April', 2019)]
```

`('April', 2021)` and `('October', 2023)` are absent. Both are corrupt in the IMF's own published archive, so this package can't serve them. See [WEO coverage and known issues](weo-coverage.md) for what that means and how it surfaces.

## Know which release you got

`weo.fetch_data.last_version_fetched` is a function attribute, set after each successful call, holding the version tuple that was returned.

```python
from imf_reader import weo

df = weo.fetch_data()
weo.fetch_data.last_version_fetched
```

**Output:**

```
('April', 2026)
```

!!! warning "Heads up"

    If the release you asked for has no data yet, `fetch_data()` rolls back: for `version=None`
    ("latest"), it walks `get_weo_versions()` newest-first and tries up to 3 older releases,
    logging each attempt at WARNING. An explicit version (e.g. `fetch_data(("October", 2025))`)
    never rolls back to a different release. If the API can't serve it, `fetch_data` falls back
    to the bulk archive for that same version first (logging a warning), and only raises if the
    archive can't serve it either. The version you asked for and the version you got can differ
    only for `version=None`. Check `last_version_fetched` when the exact release matters.

## Filter the frame

`fetch_data()` returns data in long format: one row per area, concept, and year.

```python
from imf_reader import weo

df = weo.fetch_data()
growth = df[
    (df.REF_AREA_CODE == "NGA")
    & (df.CONCEPT_CODE == "NGDP_RPCH")
    & (df.TIME_PERIOD.between(2020, 2024))
]
print(growth[["REF_AREA_LABEL", "TIME_PERIOD", "OBS_VALUE", "UNIT_LABEL"]].to_string(index=False))
```

**Output:**

```
REF_AREA_LABEL  TIME_PERIOD  OBS_VALUE UNIT_LABEL
       Nigeria         2020  -6.368898    Percent
       Nigeria         2021   1.109253    Percent
       Nigeria         2022   4.318829    Percent
       Nigeria         2023   3.315904    Percent
       Nigeria         2024   4.071067    Percent
```

## Find an indicator code

`CONCEPT_CODE` and `CONCEPT_LABEL` pair up one to one, so deriving the code list from a fetched frame finds the code for any indicator by name.

```python
from imf_reader import weo

df = weo.fetch_data()
concepts = df[["CONCEPT_CODE", "CONCEPT_LABEL"]].drop_duplicates()
print(concepts.head().to_string(index=False))
```

**Output:**

```
CONCEPT_CODE                                                                      CONCEPT_LABEL
         BCA                             Current account balance (credit less debit), US dollar
   BCA_NGDPD                        Current account balance (credit less debit), Percent of GDP
         GGR                                     Revenue, General government, Domestic currency
    GGR_NGDP                                        Revenue, General government, Percent of GDP
         GGX                                 Expenditure, General government, Domestic currency
```

The April 2026 release covers 145 concepts across 210 areas, with `TIME_PERIOD` spanning 1980 to 2031.

## Columns

The 16 columns below are identical in name, order, and meaning on both source paths (the API and the bulk archive).

| Column                | dtype          | What it holds                                                                                                                                                                                                                                                                                                                                                                                   |
| --------------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `UNIT_CODE`           | string         | Unit code, e.g. `USD`                                                                                                                                                                                                                                                                                                                                                                           |
| `CONCEPT_CODE`        | string         | Indicator code, e.g. `NGDP_RPCH`                                                                                                                                                                                                                                                                                                                                                                |
| `REF_AREA_CODE`       | string         | ISO3 (`NGA`) or `G`-prefixed aggregate (`G001`)                                                                                                                                                                                                                                                                                                                                                 |
| `REF_AREA_IMF_CODE`   | Int64          | Legacy numeric IMF area code. Null where none exists. Removed in 3.0                                                                                                                                                                                                                                                                                                                            |
| `FREQ_CODE`           | string         | Frequency code, e.g. `A`                                                                                                                                                                                                                                                                                                                                                                        |
| `LASTACTUALDATE`      | Int64          | Last year of actual (non-forecast) data. From `LATEST_ACTUAL_ANNUAL_DATA` on the API path (fiscal-year forms like `FY2023/24` are collapsed to their leading year, `2023`, a one-way, lossy mapping that discards the fiscal-year distinction. Read `START_END_MONTHS_OF_REPORTING_YEAR` from the IMF API directly for that detail), the XML series attribute of the same name on the bulk path |
| `SCALE_CODE`          | Int64          | Multiplier, e.g. `1000000000`                                                                                                                                                                                                                                                                                                                                                                   |
| `NOTES`               | string         | Observation notes. From `METHODOLOGY_NOTES` on the API path, the XML series attribute of the same name on the bulk path, different free text between the two paths with no column marking which one a given row came from. Split on the release version you requested if that matters                                                                                                           |
| `TIME_PERIOD`         | Int64          | Year                                                                                                                                                                                                                                                                                                                                                                                            |
| `OBS_VALUE`           | Float64        | The value, expressed in `SCALE_CODE` units                                                                                                                                                                                                                                                                                                                                                      |
| `UNIT_LABEL`          | string         | e.g. `US dollar`                                                                                                                                                                                                                                                                                                                                                                                |
| `CONCEPT_LABEL`       | string         | e.g. `Current account balance (credit less debit), US dollar`                                                                                                                                                                                                                                                                                                                                   |
| `REF_AREA_LABEL`      | string         | e.g. `Nigeria`                                                                                                                                                                                                                                                                                                                                                                                  |
| `FREQ_LABEL`          | string         | e.g. `Annual`                                                                                                                                                                                                                                                                                                                                                                                   |
| `SCALE_LABEL`         | string         | `Units`, `Millions`, or `Billions`                                                                                                                                                                                                                                                                                                                                                              |
| `COUNTRY_UPDATE_DATE` | datetime64[us] | Date the country's data was last revised. From the API path's metadata sidecar. Always null on the bulk path (no per-country revision date in the XML)                                                                                                                                                                                                                                          |

See [WEO coverage and known issues](weo-coverage.md) for where these columns have gaps or quirks.

## Series metadata

`weo.fetch_series_metadata(version=None)` fetches the IMF's series-level metadata sidecar, one row per series, covering methodology, classification, and reporting-convention detail that `fetch_data()` doesn't carry. `imf_reader.weo.api.get_series_metadata(version=None)` is the same call at the api layer.

```python
from imf_reader import weo

meta = weo.fetch_series_metadata()
meta.shape
```

**Output:**

```
(8200, 41)
```

Only three columns are guaranteed present release to release, `REF_AREA_CODE`, `CONCEPT_CODE`, and `FREQ_CODE`, the join keys below. The rest of the column set is release-dependent by design, since it follows whatever attribute set the IMF's DSD carries for that release, and that attribute set moves between releases.

Every column, including columns that look numeric such as `BASE_YEAR` and `DECIMALS_DISPLAYED`, is typed `string`. Native type inference for these columns changes from one release to the next. In `BASE_YEAR`, most values are a plain year like `2013`, while some carry a fiscal-year form like `FY2003/04` that native inference would either choke on or silently misread.

Values arrive as the IMF publishes them. A cell whose literal content is `N/A` stays the string `N/A`, distinct from an empty cell, which is null. 19 cells across `METHODOLOGY_NOTES` and `BASIS_OF_PROJECTIONS` take that form in the April 2026 release. `fetch_data()`'s `NOTES` column reads both forms as null, since null is the right value for "no note" there.

### Merge onto observations

`weo.fetch_data_with_metadata(version=None)` returns `fetch_data()`'s observations left-merged with `fetch_series_metadata()`'s columns on `REF_AREA_CODE`, `CONCEPT_CODE`, and `FREQ_CODE`, one call for both:

```python
from imf_reader import weo

df = weo.fetch_data_with_metadata()
df.shape
```

**Output:**

```
(361733, 54)
```

Two independent `version=None` calls, one to `fetch_data()` and one to `fetch_series_metadata()`, can resolve to different releases if a new one is published between them, merging one release's metadata onto another release's observations with nothing to signal the mismatch. `fetch_data_with_metadata()` resolves both halves to the release its own observations call served, and pins them to that release's dataflow version. Doing the merge by hand needs the same pin, using `fetch_data.last_version_fetched`:

```python
from imf_reader import weo

df = weo.fetch_data()
meta = weo.fetch_series_metadata(weo.fetch_data.last_version_fetched)
merged = df.merge(meta, on=["REF_AREA_CODE", "CONCEPT_CODE", "FREQ_CODE"], how="left")
```

Series metadata exists only for releases the API itself serves, April 2025 onward, with no bulk-archive fallback. A version the API can't serve raises `VersionNotAvailableError`. A frame of null columns would assert that the IMF publishes no methodology for these series, when this source carries no series metadata at all. See [WEO coverage and known issues](weo-coverage.md#series-metadata-is-api-only).

### Excluded and always-null columns

Three sidecar columns are left off `fetch_series_metadata()`'s output. `COUNTRY_UPDATE_DATE` is excluded because `fetch_data()` already publishes it. `UNIT` and `SCALE` are excluded because they duplicate `UNIT_CODE` and `SCALE_CODE`. The sidecar's `SCALE` carries the bare exponent (e.g. `9`), while `fetch_data()`'s `SCALE_CODE` carries the multiplier that exponent converts to (`1000000000`). Mixing the two up silently changes a value's magnitude by a power of ten.

Four columns are present but null across every one of the 8,200 series in the April 2026 release, `FUNCTIONAL_CAT`, `COICOP_1999`, `TRANSFORMATION`, and `REPORTING_PERIOD_TYPE`.

### Columns holding more than one value

A handful of columns hold multiple `;`-delimited values in one cell (their raw header carries a trailing `[]` marker from the IMF's CSV writer, which `fetch_series_metadata()` strips). Spacing around the delimiter isn't consistent. `TOPIC` holds values like `F32;F32_CA` with no space after the semicolon, while `FISCAL_SECTOR_GENERAL_GOVERNMENT_COMPOSITION` holds values like `Central Government; Local Government; Social Security Funds` with one. Split on `;` and strip whitespace from each piece to get a clean list:

```python
meta["TOPIC"].str.split(";").apply(lambda values: [v.strip() for v in values])
```

### Series metadata columns

| Column                                                     | What it holds                                                                                                                                                                  |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `REF_AREA_CODE`                                            | Join key. ISO3 or `G`-prefixed aggregate, matching `fetch_data()`'s column of the same name                                                                                    |
| `CONCEPT_CODE`                                             | Join key. Indicator code, matching `fetch_data()`'s column of the same name                                                                                                    |
| `FREQ_CODE`                                                | Join key. Frequency code, matching `fetch_data()`'s column of the same name                                                                                                    |
| `DECIMALS_DISPLAYED`                                       | Number of decimal places the IMF displays for the series                                                                                                                       |
| `FUNCTIONAL_CAT`                                           | Functional classification category. Null across all 8,200 series in the April 2026 release                                                                                     |
| `INT_ACC_ITEM`                                             | Balance of payments item code (BPM6), e.g. `CAB` for current account balance                                                                                                   |
| `NA_STO`                                                   | National accounts stock or transaction code (SNA), e.g. `B1GQ` for GDP                                                                                                         |
| `GFS_STO`                                                  | Government Finance Statistics stock or transaction code                                                                                                                        |
| `COICOP_1999`                                              | Classification of Individual Consumption by Purpose (1999). Null across all 8,200 series in the April 2026 release                                                             |
| `TRADE_FLOW`                                               | Trade flow direction, e.g. `XG` for exports of goods                                                                                                                           |
| `COMMODITY`                                                | Commodity code for a commodity-price series                                                                                                                                    |
| `SOC_CONCEPTS`                                             | Social statistics concept code, e.g. `POP` for population                                                                                                                      |
| `SECTOR`                                                   | Institutional sector code (SNA), e.g. `S13` for general government                                                                                                             |
| `ACCOUNTING_ENTRY`                                         | Accounting entry type, e.g. `N` for net                                                                                                                                        |
| `INDEX_TYPE`                                               | Index type, e.g. `CPI`                                                                                                                                                         |
| `PRICES`                                                   | Price basis, e.g. `V` for value or `Q` for volume                                                                                                                              |
| `STATISTICAL_MEASURES`                                     | Statistical measure applied, e.g. `RT` for rate of change                                                                                                                      |
| `EXRATE`                                                   | Exchange rate type used to convert the series, e.g. `XDC_PU`                                                                                                                   |
| `TRANSFORMATION`                                           | Data transformation applied to the series. Null across all 8,200 series in the April 2026 release                                                                              |
| `REPORTING_PERIOD_TYPE`                                    | Reporting period type. Null across all 8,200 series in the April 2026 release                                                                                                  |
| `OVERLAP`                                                  | Overlap indicator between historical and projected data, e.g. `OL`                                                                                                             |
| `TOPIC`                                                    | Subject area code(s), `;`-delimited, e.g. `F32;F32_CA`                                                                                                                         |
| `METHODOLOGY`                                              | Name of the statistical manual the series follows, e.g. `Balance of Payments and International Investment Position Manual, sixth edition (BPM6)`                               |
| `METHODOLOGY_NOTES`                                        | Free-text methodology note. The same field `fetch_data()`'s `NOTES` column reads on API-served releases                                                                        |
| `KEY_INDICATOR`                                            | `true` where the IMF flags the series as one of its key indicators, otherwise null                                                                                             |
| `SERIES_NAME`                                              | Human-readable series name                                                                                                                                                     |
| `LATEST_ACTUAL_ANNUAL_DATA`                                | Last year of actual (non-forecast) data, preserving fiscal-year forms such as `FY2023/24`. The field `fetch_data()`'s `LASTACTUALDATE` reads and collapses to its leading year |
| `HISTORICAL_DATA_SOURCE`                                   | National institution supplying historical data, e.g. `Central Bank`                                                                                                            |
| `BASE_YEAR`                                                | Base year for index or volume calculations, e.g. `2013`. Occasionally a fiscal-year form such as `FY2003/04`                                                                   |
| `START_END_MONTHS_OF_REPORTING_YEAR`                       | Start and end months of the fiscal reporting year, e.g. `January/December`                                                                                                     |
| `CHAIN_WEIGHTED`                                           | Whether the series uses chain-weighted volume measures, e.g. `Yes, from 2000`                                                                                                  |
| `BASIS_OF_PROJECTIONS`                                     | Basis the IMF projects the series on, e.g. `Government budget and projected nominal GDP`                                                                                       |
| `VALUATION`                                                | Valuation basis, e.g. `Cash` or `Accrual`                                                                                                                                      |
| `PRICES_SECTOR_HARMONIZED_PRICES`                          | Whether the sector uses harmonised prices, `Yes` or `No`                                                                                                                       |
| `LABOR_SECTOR_EMPLOYMENT_TYPE`                             | Employment definition used for a labour-sector series, e.g. `Harmonized ILO definition`                                                                                        |
| `FISCAL_SECTOR_GENERAL_GOVERNMENT_COMPOSITION`             | Subsectors composing "general government" for this series, `;`-delimited, e.g. `Central Government; Local Government; Social Security Funds`                                   |
| `FISCAL_SECTOR_VALUATION_OF_DEBT`                          | Valuation basis for government debt, e.g. `Nominal value`                                                                                                                      |
| `FISCAL_SECTOR_INSTRUMENTS_INCLUDED_IN_GROSS_AND_NET_DEBT` | Debt instruments included in gross and net debt figures, `;`-delimited                                                                                                         |
| `TRADE_SECTOR_OIL_COVERAGE`                                | Oil product coverage for a trade-sector series, `;`-delimited                                                                                                                  |
| `PRIMARY_DOMESTIC_CURRENCY`                                | The area's primary domestic currency, e.g. `Aruban Florin`                                                                                                                     |
| `KEYWORDS`                                                 | Free-text search keywords, `;`-delimited                                                                                                                                       |

Many of the coded columns above hold a short code rather than a label, and that code is meant to be looked up, not read on its own. The lookup is the same IMF codelist API this package's own label columns are built from. A coded column's values key into a codelist named `CL_<column name>` under `https://api.imf.org/external/sdmx/3.0/structure/codelist/IMF/`. `SECTOR`, for instance, looks up against `https://api.imf.org/external/sdmx/3.0/structure/codelist/IMF/CL_SECTOR`.

## Errors

All three are importable from `imf_reader.config`:

```python
from imf_reader.config import DataflowDiscoveryError, NoDataError, VersionNotAvailableError
```

- `NoDataError`, the base exception for "no WEO data could be resolved". Raised directly for an
  invalid `version` argument, and is the parent class of the two below, so catching it covers
  every case.
- `VersionNotAvailableError(NoDataError)`, raised when the requested version isn't served by the
  API. The bulk archive may still have it.
- `DataflowDiscoveryError(NoDataError)`, raised when the IMF's dataflow catalogue responds but
  carries no usable WEO dataflow, so no release, including "latest", can be resolved from it.

All three import from `imf_reader.config`. `imf_reader.cache` re-exports `BulkPayloadCorruptError`
alone.

## Clearing the cache

`weo.clear_cache()` works but is deprecated: it emits a `DeprecationWarning` and is removed in 3.0. Use `cache.clear_cache(scope="weo")` instead. See [Caching](caching.md) for the full cache model.

## Next steps

- [WEO coverage and known issues](weo-coverage.md) - the permanent quirks in the underlying data and how this package handles them
- [Caching](caching.md) - how WEO releases and version mappings are cached, and how to clear or relocate the cache
- [Special Drawing Rights](sdr.md) - the other IMF dataset this package reads, with its own date-order convention
