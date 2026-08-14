# imf-reader

**One pandas interface for IMF World Economic Outlook and Special Drawing Rights data.**

The IMF publishes the World Economic Outlook (WEO) database through an SDMX API for recent
releases and through a discontinued bulk archive for everything before it, with a vocabulary
change between the two. It publishes Special Drawing Rights (SDR) data through no API at all,
only web pages meant for browsers. `imf-reader` puts both behind one pandas-shaped interface.

The package fetches, translates, and caches the data so an analysis script can call one function
and get back a typed DataFrame, regardless of which IMF system the numbers live in.

- Fetches WEO releases from April 2019 onward, drawing from the SDMX API or the bulk archive
  depending on the release requested
- Joins both WEO sources onto one vocabulary, so columns and codes match across the April 2025
  split
- Parses SDR holdings, allocations, exchange rates, and interest rates from IMF web pages
- Caches results to disk, so already-cached data keeps working through a broken upstream
- Returns typed pandas DataFrames throughout

## Quick example

```python
from imf_reader import weo

df = weo.fetch_data()
print(df.head(3))
```

**Output:**

```
  UNIT_CODE CONCEPT_CODE REF_AREA_CODE  REF_AREA_IMF_CODE FREQ_CODE  LASTACTUALDATE  SCALE_CODE NOTES  TIME_PERIOD  OBS_VALUE UNIT_LABEL                                           CONCEPT_LABEL                     REF_AREA_LABEL FREQ_LABEL SCALE_LABEL COUNTRY_UPDATE_DATE
0       USD          BCA           ABW                314         A            2024  1000000000  <NA>         1999  -0.435363  US dollar  Current account balance (credit less debit), US dollar  Aruba, Kingdom of the Netherlands     Annual    Billions          2025-09-19
1       USD          BCA           ABW                314         A            2024  1000000000  <NA>         2000   0.212542  US dollar  Current account balance (credit less debit), US dollar  Aruba, Kingdom of the Netherlands     Annual    Billions          2025-09-19
2       USD          BCA           ABW                314         A            2024  1000000000  <NA>         2001   0.310076  US dollar  Current account balance (credit less debit), US dollar  Aruba, Kingdom of the Netherlands     Annual    Billions          2025-09-19
```

## Next steps

- [Why imf-reader](why-imf-reader.md) - the rationale behind the package and how it compares to
  the alternatives
- [Getting started](getting-started.md) - install the package and run a WEO and an SDR query
- [World Economic Outlook](weo.md) - the full WEO reference, including filtering and coverage
