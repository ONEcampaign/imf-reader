# Getting Started

This guide walks you through installing imf-reader and running your first examples.

## Installation

### Using uv (recommended)

Install imf-reader using [uv](https://docs.astral.sh/uv/), the fast Python package installer:

```bash
uv pip install imf-reader
```

### Using pip

You can also use pip if you prefer:

```bash
pip install imf-reader
```

### Requirements

- Python 3.10 or higher
- Dependencies (installed automatically): pandas, requests, beautifulsoup4, chardet

## Your First Examples

### Example 1: Fetch Latest WEO Data

The World Economic Outlook (WEO) database contains macroeconomic indicators for ~200 countries. Here's how to fetch the latest release:

```python
from imf_reader import weo

# Fetch the latest WEO data
df = weo.fetch_data()

# Check what we got
print(f"Data shape: {df.shape}")
print(f"\nColumns: {list(df.columns)}")
print(f"\nFirst 3 rows:\n{df.head(3)}")
```

**Output:**
```
Data shape: (531216, 14)

Columns: ['UNIT_CODE', 'CONCEPT_CODE', 'REF_AREA_CODE', 'FREQ_CODE', 'LASTACTUALDATE', 'SCALE_CODE', 'NOTES', 'TIME_PERIOD', 'OBS_VALUE', 'UNIT_LABEL', 'CONCEPT_LABEL', 'REF_AREA_LABEL', 'FREQ_LABEL', 'SCALE_LABEL']

First 3 rows:
  UNIT_CODE CONCEPT_CODE  REF_AREA_CODE  ...  REF_AREA_LABEL  FREQ_LABEL  SCALE_LABEL
0         B       NGDP_D            111  ...   United States      Annual        Units
1         B       NGDP_D            111  ...   United States      Annual        Units
2         B       NGDP_D            111  ...   United States      Annual        Units
```

The data includes over 500,000 observations with indicators like GDP, inflation, unemployment, and more.

### Example 2: Get SDR Allocations

Special Drawing Rights (SDR) are international reserve assets. Here's how to fetch the latest allocations and holdings:

```python
from imf_reader import sdr

# Fetch latest SDR allocations and holdings
df = sdr.fetch_allocations_holdings()

print(f"Data shape: {df.shape}")
print(f"\nFirst 5 countries:\n{df.head()}")
```

**Output:**
```
Data shape: (400, 4)

First 5 countries:
                             entity indicator       value       date
0  Afghanistan, Islamic Republic of  holdings   316518004 2025-09-30
1                           Albania  holdings   207206606 2025-09-30
2                           Algeria  holdings  3173988531 2025-09-30
3                           Andorra  holdings    93656756 2025-09-30
4                            Angola  holdings   263961157 2025-09-30
```

The data shows SDR holdings for each member country as of the latest available date (September 2025 in this example).

### Example 3: Analyze Data with Pandas

Since all data is returned as pandas DataFrames, you can immediately use pandas operations:

```python
from imf_reader import weo

# Fetch WEO data
df = weo.fetch_data()

# Filter for GDP deflator data for the United States
us_gdp = df[
    (df['CONCEPT_CODE'] == 'NGDP_D') &
    (df['REF_AREA_LABEL'] == 'United States')
][['TIME_PERIOD', 'CONCEPT_LABEL', 'OBS_VALUE']]

# Show recent years
print(us_gdp.tail(5))
```

**Output:**
```
  TIME_PERIOD                     CONCEPT_LABEL  OBS_VALUE
46         2025  Gross domestic product, deflator    131.366
47         2026  Gross domestic product, deflator    133.784
48         2027  Gross domestic product, deflator    136.574
49         2028  Gross domestic product, deflator    139.074
50         2029  Gross domestic product, deflator    141.677
```

## Understanding the Data

### WEO Data Structure

WEO data includes these key columns:

- `CONCEPT_CODE`: Indicator code (e.g., 'NGDP_D' for GDP deflator)
- `CONCEPT_LABEL`: Human-readable indicator name
- `REF_AREA_CODE`: Country/region code
- `REF_AREA_LABEL`: Country/region name
- `TIME_PERIOD`: Year of observation
- `OBS_VALUE`: The actual data value

### SDR Data Structure

SDR allocations/holdings include:

- `entity`: Country or organization name
- `indicator`: Either 'holdings' or 'allocations'
- `value`: Amount in SDR units
- `date`: As of date

## What Happens Behind the Scenes?

When you call `weo.fetch_data()`, the package:

1. Checks if data is already cached (to avoid redundant requests)
2. Determines the latest expected WEO version (April or October)
3. Attempts to fetch data from the IMF website
4. Falls back to the previous version if the latest isn't available yet
5. Parses the SDMX (Statistical Data and Metadata eXchange) format
6. Returns a clean pandas DataFrame

The first fetch takes a few seconds. Subsequent calls with the same parameters are instant due to caching.

## Common First-Time Issues

### Data Fetching Takes Time

The first time you fetch WEO data, it downloads and parses a large SDMX file. This typically takes 10-30 seconds. Subsequent calls are cached and return immediately.

### Version Rollback Messages

You might see messages like:
```
INFO: No data found for expected latest version: October 2025. Rolling back version...
INFO: Data fetched successfully for version: April 2025
```

This is normal! The package automatically handles cases where the latest WEO release isn't yet published, falling back to the most recent available version.

## Next Steps

Now that you have the basics, explore specific use cases:

- **[WEO Data](weo-data.md)**: Learn how to work with specific indicators, countries, and time periods
- **[SDR Allocations](sdr-allocations.md)**: Track SDR holdings over time and analyze by country
- **[SDR Rates](sdr-rates.md)**: Access historical interest and exchange rates
- **[Advanced Usage](advanced-usage.md)**: Cache management, error handling, and best practices
