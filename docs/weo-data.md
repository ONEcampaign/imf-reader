# Working with WEO Data

The World Economic Outlook (WEO) database provides comprehensive macroeconomic data and forecasts for approximately 200 countries and regions. You'll find over 40 indicators covering GDP, inflation, government finances, unemployment, and more—all published twice yearly by the IMF.

This guide shows you how to access, filter, and analyze WEO data for your research or analysis needs.

## Basic Usage

### Fetch the Latest Release

The simplest way to get WEO data is to call `fetch_data()` without parameters:

```python
from imf_reader import weo

# Fetch the latest available WEO release
df = weo.fetch_data()

print(f"Data shape: {df.shape}")
print(f"Columns: {list(df.columns)}")
```

**Output:**
```
Data shape: (531216, 14)
Columns: ['UNIT_CODE', 'CONCEPT_CODE', 'REF_AREA_CODE', 'FREQ_CODE', 'LASTACTUALDATE', 'SCALE_CODE', 'NOTES', 'TIME_PERIOD', 'OBS_VALUE', 'UNIT_LABEL', 'CONCEPT_LABEL', 'REF_AREA_LABEL', 'FREQ_LABEL', 'SCALE_LABEL']
```

The data includes over 500,000 observations spanning decades of economic data.

### Understanding the Columns

Key columns you'll use most often:

| Column | Description | Example Values |
|--------|-------------|----------------|
| `CONCEPT_CODE` | Indicator code | `'NGDPD'`, `'PCPI'`, `'LUR'` |
| `CONCEPT_LABEL` | Human-readable indicator name | `'Gross domestic product, current prices'` |
| `REF_AREA_CODE` | Country/region numeric code | `111` (USA), `924` (China) |
| `REF_AREA_LABEL` | Country/region name | `'United States'`, `'China'` |
| `TIME_PERIOD` | Year of observation | `'2020'`, `'2025'` |
| `OBS_VALUE` | The actual data value | `21354.125`, `2.3` |
| `SCALE_LABEL` | Units of measurement | `'Billions'`, `'Percent'` |

## Exploring Available Indicators

WEO includes 40+ economic indicators. Here's how to see what's available:

```python
from imf_reader import weo

df = weo.fetch_data()

# Get unique indicators
indicators = df[['CONCEPT_CODE', 'CONCEPT_LABEL']].drop_duplicates()
print(indicators.head(15))
```

**Output:**
```
CONCEPT_CODE                                                       CONCEPT_LABEL
      NGDP_D                                    Gross domestic product, deflator
        PCPI                                  Inflation, average consumer prices
       PCPIE                            Inflation, end of period consumer prices
          LE                                                          Employment
         GGR                                          General government revenue
        GGSB                               General government structural balance
         GGX                                General government total expenditure
      GGXCNL                            General government net lending/borrowing
     GGXONLB                    General government primary net lending/borrowing
      GGXWDG                                       General government gross debt
      GGXWDN                                         General government net debt
        NGDP                              Gross domestic product, current prices
     NGDP_FY Gross domestic product corresponding to fiscal year, current prices
      NGDP_R                             Gross domestic product, constant prices
      NGDPPC                   Gross domestic product per capita, current prices
```

Common indicators you might use:

- **NGDPD**: Gross domestic product (current prices, USD billions)
- **NGDP_R**: Real GDP (constant prices)
- **PCPI**: Inflation (average consumer prices, percent change)
- **LUR**: Unemployment rate (percent of labor force)
- **GGX**: Government total expenditure (percent of GDP)
- **GGXWDG**: Government gross debt (percent of GDP)

## Filtering by Country

### Single Country Data

Get data for a specific country:

```python
from imf_reader import weo

df = weo.fetch_data()

# Filter for United States data
us_data = df[df['REF_AREA_LABEL'] == 'United States']

# Get GDP deflator for recent years
us_gdp = us_data[us_data['CONCEPT_CODE'] == 'NGDP_D'][
    ['TIME_PERIOD', 'CONCEPT_LABEL', 'OBS_VALUE']
]

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

### Multi-Country Comparison

Compare the same indicator across multiple countries:

```python
from imf_reader import weo

df = weo.fetch_data()

# Compare GDP across major economies
countries = ['United States', 'China', 'Germany', 'Japan']
gdp_comparison = df[
    (df['CONCEPT_CODE'] == 'NGDPD') &
    (df['REF_AREA_LABEL'].isin(countries)) &
    (df['TIME_PERIOD'].astype(int) >= 2020)
][['REF_AREA_LABEL', 'TIME_PERIOD', 'OBS_VALUE']].sort_values(['TIME_PERIOD', 'REF_AREA_LABEL'])

print(gdp_comparison.head(12))
```

**Output:**
```
REF_AREA_LABEL  TIME_PERIOD  OBS_VALUE
         China         2020  15103.357
       Germany         2020   3936.989
         Japan         2020   5054.069
 United States         2020  21354.125
         China         2021  18190.803
       Germany         2021   4351.188
         Japan         2021   5039.148
 United States         2021  23681.175
         China         2022  18307.816
       Germany         2022   4166.872
         Japan         2022   4262.146
 United States         2022    26006.9
```

Values are in billions of U.S. dollars.

## Working with Specific Versions

WEO is published twice yearly in April and October. You can fetch specific historical releases:

```python
from imf_reader import weo

# Fetch October 2024 release
df_oct24 = weo.fetch_data(version=("October", 2024))

print(f"Data shape: {df_oct24.shape}")
```

**Output:**
```
Data shape: (520800, 14)
```

The version parameter takes a tuple of `(month, year)` where month must be either `"April"` or `"October"`.

### Comparing Forecasts Across Releases

You can analyze how IMF forecasts change over time by comparing different releases:

```python
from imf_reader import weo

# Fetch two releases
df_oct24 = weo.fetch_data(version=("October", 2024))
df_apr25 = weo.fetch_data(version=("April", 2025))

# Compare GDP forecasts for 2025
def get_gdp_forecast(df, year, country):
    return df[
        (df['CONCEPT_CODE'] == 'NGDPD') &
        (df['REF_AREA_LABEL'] == country) &
        (df['TIME_PERIOD'] == str(year))
    ]['OBS_VALUE'].values[0]

us_gdp_oct = get_gdp_forecast(df_oct24, 2025, 'United States')
us_gdp_apr = get_gdp_forecast(df_apr25, 2025, 'United States')

print(f"US GDP 2025 forecast (Oct 2024): ${us_gdp_oct:.2f}B")
print(f"US GDP 2025 forecast (Apr 2025): ${us_gdp_apr:.2f}B")
print(f"Revision: ${us_gdp_apr - us_gdp_oct:.2f}B")
```

## Time Series Analysis

### Extract Historical Series

Get a complete time series for analysis or visualization:

```python
from imf_reader import weo

df = weo.fetch_data()

# Get inflation time series for Germany
germany_inflation = df[
    (df['CONCEPT_CODE'] == 'PCPI') &
    (df['REF_AREA_LABEL'] == 'Germany')
][['TIME_PERIOD', 'OBS_VALUE']].sort_values('TIME_PERIOD')

# Convert to numeric for analysis
germany_inflation['TIME_PERIOD'] = germany_inflation['TIME_PERIOD'].astype(int)
germany_inflation['OBS_VALUE'] = pd.to_numeric(germany_inflation['OBS_VALUE'])

print(germany_inflation.tail(10))
```

This gives you a clean time series ready for plotting or further analysis.

### Calculate Year-over-Year Changes

```python
from imf_reader import weo
import pandas as pd

df = weo.fetch_data()

# Get GDP data
gdp_data = df[
    (df['CONCEPT_CODE'] == 'NGDPD') &
    (df['REF_AREA_LABEL'] == 'United States')
][['TIME_PERIOD', 'OBS_VALUE']].copy()

# Convert to numeric
gdp_data['TIME_PERIOD'] = gdp_data['TIME_PERIOD'].astype(int)
gdp_data['OBS_VALUE'] = pd.to_numeric(gdp_data['OBS_VALUE'])
gdp_data = gdp_data.sort_values('TIME_PERIOD')

# Calculate year-over-year growth
gdp_data['YoY_Change'] = gdp_data['OBS_VALUE'].pct_change() * 100

print(gdp_data[['TIME_PERIOD', 'OBS_VALUE', 'YoY_Change']].tail(5))
```

## Automatic Version Fallback

When you call `fetch_data()` without specifying a version, the package automatically determines the latest expected release. If that release isn't available yet (e.g., you're fetching in September before the October release), it automatically falls back to the previous version:

```python
from imf_reader import weo

# This will automatically use the most recent available version
df = weo.fetch_data()
```

You'll see informative log messages:
```
INFO: No data found for expected latest version: October 2025. Rolling back version...
INFO: Data fetched successfully for version: April 2025
```

This means the October 2025 WEO hasn't been published yet, so the package returned April 2025 data instead.

## Performance Note

The first time you fetch a specific WEO version, the package downloads and parses the complete SDMX file, which takes 10-30 seconds. Subsequent calls with the same version are cached and return instantly.

```python
from imf_reader import weo
import time

# First call: downloads data
start = time.time()
df1 = weo.fetch_data()
print(f"First call: {time.time() - start:.2f} seconds")

# Second call: returns from cache
start = time.time()
df2 = weo.fetch_data()
print(f"Second call: {time.time() - start:.2f} seconds")
```

Expected output:
```
First call: 15.23 seconds
Second call: 0.01 seconds
```

## Error Handling

### Invalid Version

If you request a version that doesn't exist or has an invalid format:

```python
from imf_reader import weo

try:
    df = weo.fetch_data(version=("September", 2024))  # Invalid month
except TypeError as e:
    print(f"Error: {e}")
```

**Output:**
```
Error: Invalid month. Must be `April` or `October`
```

### Data Not Available

If a specific version hasn't been published:

```python
from imf_reader import weo
from imf_reader.config import NoDataError

try:
    df = weo.fetch_data(version=("April", 2026))  # Future release
except NoDataError as e:
    print(f"Error: {e}")
```

## Next Steps

- **[SDR Allocations](sdr-allocations.md)**: Track Special Drawing Rights allocations and holdings
- **[SDR Rates](sdr-rates.md)**: Access interest and exchange rates
- **[Advanced Usage](advanced-usage.md)**: Cache management and best practices
