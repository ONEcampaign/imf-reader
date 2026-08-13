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
(361733, 15)
```

```python
df.head(3)
```

**Output:**

```
  UNIT_CODE CONCEPT_CODE REF_AREA_CODE  REF_AREA_IMF_CODE FREQ_CODE  LASTACTUALDATE  SCALE_CODE NOTES  TIME_PERIOD  OBS_VALUE UNIT_LABEL                                           CONCEPT_LABEL                     REF_AREA_LABEL FREQ_LABEL SCALE_LABEL
0       USD          BCA           ABW                314         A            <NA>  1000000000  <NA>         1999  -0.435363  US dollar  Current account balance (credit less debit), US dollar  Aruba, Kingdom of the Netherlands     Annual    Billions
1       USD          BCA           ABW                314         A            <NA>  1000000000  <NA>         2000   0.212542  US dollar  Current account balance (credit less debit), US dollar  Aruba, Kingdom of the Netherlands     Annual    Billions
2       USD          BCA           ABW                314         A            <NA>  1000000000  <NA>         2001   0.310076  US dollar  Current account balance (credit less debit), US dollar  Aruba, Kingdom of the Netherlands     Annual    Billions
```

## Fetch a specific release

```python
from imf_reader import weo

df = weo.fetch_data(("April", 2024))
```

The `version` argument is a `(month, year)` tuple, month first. The month must be `"April"` or `"October"`, matching the IMF's twice-yearly release schedule. An invalid version raises `NoDataError`.

## List available releases

```python
from imf_reader import weo

weo.get_weo_versions()
```

**Output:**

```
[('October', 2025), ('April', 2025), ('October', 2024), ('April', 2024), ('April', 2023), ('October', 2022), ('April', 2022), ('October', 2021), ('October', 2020), ('April', 2020), ('October', 2019), ('April', 2019)]
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
('October', 2025)
```

!!! warning "Heads up"
    If the release you requested has no data yet, `fetch_data` rolls back to the previous one
    (October rolls back to April of the same year, April rolls back to October of the previous
    year) and logs the rollback at INFO. The version you asked for and the version you got can
    differ. Check `last_version_fetched` when the exact release matters.

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

The October 2025 release covers 145 concepts across 210 areas, with `TIME_PERIOD` spanning 1980 to 2031.

## Columns

The 15 columns below are identical in name, order, and meaning on both source paths (the API and the bulk archive).

| Column              | dtype   | What it holds                                                               |
| ------------------- | ------- | --------------------------------------------------------------------------- |
| `UNIT_CODE`         | string  | Unit code, e.g. `USD`                                                       |
| `CONCEPT_CODE`      | string  | Indicator code, e.g. `NGDP_RPCH`                                            |
| `REF_AREA_CODE`     | string  | ISO3 (`NGA`) or `G`-prefixed aggregate (`G001`)                             |
| `REF_AREA_IMF_CODE` | Int64   | Legacy numeric IMF area code. Null where none exists. Removed in 3.0        |
| `FREQ_CODE`         | string  | Frequency code, e.g. `A`                                                    |
| `LASTACTUALDATE`    | Int64   | Last year of actual (non-forecast) data. Only populated before October 2025 |
| `SCALE_CODE`        | Int64   | Multiplier, e.g. `1000000000`                                               |
| `NOTES`             | string  | Observation notes. Only populated before October 2025                       |
| `TIME_PERIOD`       | Int64   | Year                                                                        |
| `OBS_VALUE`         | Float64 | The value, expressed in `SCALE_CODE` units                                  |
| `UNIT_LABEL`        | string  | e.g. `US dollar`                                                            |
| `CONCEPT_LABEL`     | string  | e.g. `Current account balance (credit less debit), US dollar`               |
| `REF_AREA_LABEL`    | string  | e.g. `Nigeria`                                                              |
| `FREQ_LABEL`        | string  | e.g. `Annual`                                                               |
| `SCALE_LABEL`       | string  | `Units`, `Millions`, or `Billions`                                          |

See [WEO coverage and known issues](weo-coverage.md) for where these columns have gaps or quirks.

## Clearing the cache

`weo.clear_cache()` still works. It is deprecated, emits a `DeprecationWarning`, and is removed in 3.0. Use `cache.clear_cache(scope="weo")` instead. See [Caching](caching.md) for the full cache model.

## Next steps

- [WEO coverage and known issues](weo-coverage.md) - the permanent quirks in the underlying data and how this package handles them
- [Caching](caching.md) - how WEO releases and version mappings are cached, and how to clear or relocate the cache
- [Special Drawing Rights](sdr.md) - the other IMF dataset this package reads, with its own date-order convention
