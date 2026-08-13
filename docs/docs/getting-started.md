# Getting started

## Install

Install from PyPI with pip:

```bash
pip install imf-reader
```

Or with uv:

```bash
uv add imf-reader
```

The package is also on conda-forge:

```bash
conda install imf-reader
```

`imf-reader` requires Python 3.12 or later.

## Fetch your first WEO release

`weo.fetch_data()` fetches the latest WEO release:

```python
from imf_reader import weo

df = weo.fetch_data()
print(df.shape)
print(df.head(3))
```

**Output:**

```
(361733, 15)
  UNIT_CODE CONCEPT_CODE REF_AREA_CODE  REF_AREA_IMF_CODE FREQ_CODE  LASTACTUALDATE  SCALE_CODE NOTES  TIME_PERIOD  OBS_VALUE UNIT_LABEL                                           CONCEPT_LABEL                     REF_AREA_LABEL FREQ_LABEL SCALE_LABEL
0       USD          BCA           ABW                314         A            <NA>  1000000000  <NA>         1999  -0.435363  US dollar  Current account balance (credit less debit), US dollar  Aruba, Kingdom of the Netherlands     Annual    Billions
1       USD          BCA           ABW                314         A            <NA>  1000000000  <NA>         2000   0.212542  US dollar  Current account balance (credit less debit), US dollar  Aruba, Kingdom of the Netherlands     Annual    Billions
2       USD          BCA           ABW                314         A            <NA>  1000000000  <NA>         2001   0.310076  US dollar  Current account balance (credit less debit), US dollar  Aruba, Kingdom of the Netherlands     Annual    Billions
```

That's the October 2025 release: 210 areas, 145 concepts, `TIME_PERIOD` spanning 1980-2031
(WEO releases carry projections alongside actuals). The frame is long-format, one row per area,
concept, and year, with typed columns throughout.

## Filter to one indicator

Filter the frame with standard pandas boolean indexing. Here's Nigeria's real GDP growth
(`NGDP_RPCH`) for 2020 through 2024:

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

Every WEO query filters the same three columns: `REF_AREA_CODE` for a country or aggregate,
`CONCEPT_CODE` for an indicator, and `TIME_PERIOD` for a year range.

## Check which release you got

`fetch_data()` without arguments returns the latest release, and records which one it fetched on
the function itself:

```python
from imf_reader import weo

df = weo.fetch_data()
print(weo.fetch_data.last_version_fetched)
```

**Output:**

```
('October', 2025)
```

To see every release available to fetch, call `get_weo_versions()`:

```python
from imf_reader import weo

print(weo.get_weo_versions())
```

**Output:**

```
[('October', 2025), ('April', 2025), ('October', 2024), ('April', 2024), ('April', 2023), ('October', 2022), ('April', 2022), ('October', 2021), ('October', 2020), ('April', 2020), ('October', 2019), ('April', 2019)]
```

`('April', 2021)` and `('October', 2023)` are missing from that list. Both are corrupted in the
IMF's own published archive and cannot be fetched by any means, so `get_weo_versions()` leaves
them out.

## Fetch SDR data

SDR data has no API. `imf-reader` parses it from IMF web pages and returns the same kind of
typed pandas frame as the WEO functions.

```python
from imf_reader import sdr

rates = sdr.fetch_exchange_rates()
holdings = sdr.fetch_allocations_holdings()
```

`fetch_exchange_rates()` returns two columns, `date` and `exchange_rate`, with one row per
period. It defaults to `unit_basis="SDR"`, giving 1 SDR expressed in USD. Pass
`unit_basis="USD"` for 1 USD expressed in SDR.

`fetch_allocations_holdings()` returns four columns: `entity`, `indicator` (`holdings` or
`allocations`), `value`, and `date`. Called with no argument it returns the latest month
available. Pass a specific month as a `(year, month)` tuple.

!!! warning "Heads up"
    SDR and WEO order their date arguments differently. `sdr.fetch_allocations_holdings((2021, 4))` takes `(year, month)` as integers, for April 2021. `weo.fetch_data(("April", 2021))` takes `(month, year)`, with the month as a name. Check which module you're calling before passing a tuple.

## What just happened

1. `weo.fetch_data()` picked whichever source, API or bulk archive, serves the requested release.
2. Filtering happened in pandas, on plain column values.
3. `sdr.fetch_exchange_rates()` and `sdr.fetch_allocations_holdings()` parsed IMF web pages into
   the same kind of frame.
4. Every call cached its result to disk, so running the same snippet again is immediate.

## Next steps

- [World Economic Outlook](weo.md) - the full WEO reference, including indicator lookup and
  known data quirks
- [Special Drawing Rights](sdr.md) - the full SDR reference, including interest rates
- [Caching](caching.md) - cache location, clearing, and disabling
