# SDR Allocations and Holdings

Special Drawing Rights (SDRs) are international reserve assets created by the IMF. They're not currency, but IMF member countries can exchange them for freely usable currencies in times of need. SDR allocations and holdings data shows how much each member has been allocated and how much they currently hold.

This guide shows you how to access and analyze SDR allocation and holdings data, which is published monthly by the IMF.

## What Are SDRs?

SDRs were created in 1969 to supplement member countries' official reserves. The IMF allocates SDRs to members proportional to their IMF quota shares. Countries can:

- Hold SDRs as part of their international reserves
- Exchange SDRs with other members for freely usable currencies
- Use SDRs for transactions with the IMF

Learn more about SDRs at the [IMF SDR Factsheet](https://www.imf.org/en/About/Factsheets/Sheets/2023/special-drawing-rights-sdr).

## Basic Usage

### Fetch Latest Data

Get the most recent SDR allocations and holdings data:

```python
from imf_reader import sdr

# Fetch latest data
df = sdr.fetch_allocations_holdings()

print(f"Data shape: {df.shape}")
print(f"Columns: {list(df.columns)}")
print(df.head())
```

**Output:**
```
Data shape: (400, 4)
Columns: ['entity', 'indicator', 'value', 'date']

                             entity indicator       value       date
0  Afghanistan, Islamic Republic of  holdings   316518004 2025-09-30
1                           Albania  holdings   207206606 2025-09-30
2                           Algeria  holdings  3173988531 2025-09-30
3                           Andorra  holdings    93656756 2025-09-30
4                            Angola  holdings   263961157 2025-09-30
```

The data includes both holdings and allocations for each member. Values are in SDR units.

### Understanding the Data Structure

| Column | Description | Example Values |
|--------|-------------|----------------|
| `entity` | Country or organization name | `'Kenya'`, `'United States'` |
| `indicator` | Type of data | `'holdings'`, `'allocations'` |
| `value` | Amount in SDR units | `202710875`, `779896551` |
| `date` | As-of date (end of month) | `2025-09-30` |

Each entity typically has two rows: one for holdings and one for allocations.

## Checking Latest Available Date

Before fetching data, you might want to check what's the latest month available:

```python
from imf_reader import sdr

# Get latest available date as (year, month) tuple
latest_date = sdr.fetch_latest_allocations_holdings_date()
print(f"Latest data available: {latest_date}")
```

**Output:**
```
Latest data available: (2025, 9)
```

This tells you the latest data is for September 2025. SDR data is published with approximately a one-month lag.

## Analyzing by Country

### Single Country Data

Get data for a specific country:

```python
from imf_reader import sdr

df = sdr.fetch_allocations_holdings()

# Filter for Kenya
kenya_data = df[df['entity'] == 'Kenya']
print(kenya_data)
```

**Output:**
```
    entity    indicator      value       date
86   Kenya     holdings  202710875 2025-09-30
286  Kenya  allocations  779896551 2025-09-30
```

Kenya holds about 203 million SDRs out of its 780 million SDR allocation.

### Calculate Usage Ratio

See what percentage of allocation each country is holding:

```python
from imf_reader import sdr
import pandas as pd

df = sdr.fetch_allocations_holdings()

# Pivot to get holdings and allocations side by side
df_pivot = df.pivot(index='entity', columns='indicator', values='value').reset_index()
df_pivot.columns.name = None

# Calculate usage (holding as % of allocation)
df_pivot['usage_ratio'] = (df_pivot['holdings'] / df_pivot['allocations'] * 100).round(2)

# Sort by usage ratio
df_pivot = df_pivot.sort_values('usage_ratio')

print("Countries with lowest usage ratios (sold/used most SDRs):")
print(df_pivot[['entity', 'holdings', 'allocations', 'usage_ratio']].head(10))
```

Countries with low usage ratios have exchanged their SDRs for other currencies.

### Top SDR Holders

Find countries with the largest SDR holdings:

```python
from imf_reader import sdr

df = sdr.fetch_allocations_holdings()

# Filter for holdings only
holdings = df[df['indicator'] == 'holdings'].copy()

# Convert to numeric for sorting
holdings['value'] = holdings['value'].astype(float)

# Get top 10
top10 = holdings.nlargest(10, 'value')[['entity', 'value']]
top10['value_billions'] = (top10['value'] / 1e9).round(2)

print(top10[['entity', 'value_billions']])
```

**Output:**
```
            entity  value_billions
             Total          660.84
     United States          127.45
             Japan           44.42
             China           40.93
           Germany           39.76
    United Kingdom           29.88
            France           27.58
             Italy           21.56
Russian Federation           17.60
            Canada           17.03
```

The United States holds the most SDRs at about 127 billion, followed by major economies like Japan and China.

## Historical Data

### Fetch Specific Month

Get data for a particular month and year:

```python
from imf_reader import sdr

# Fetch April 2025 data
# Format: (year, month) as integers
df_april = sdr.fetch_allocations_holdings((2025, 4))

print(f"Data shape: {df_april.shape}")
print(df_april.head())
```

**Output:**
```
Data shape: (400, 4)

                             entity indicator       value       date
0  Afghanistan, Islamic Republic of  holdings   321940679 2025-04-30
1                           Albania  holdings   202275737 2025-04-30
2                           Algeria  holdings  3223676330 2025-04-30
3                           Andorra  holdings    93680048 2025-04-30
4                            Angola  holdings   331766753 2025-04-30
```

### Track Changes Over Time

Compare holdings across multiple months:

```python
from imf_reader import sdr
import pandas as pd

# Fetch multiple months
dates = [(2025, 1), (2025, 4), (2025, 9)]
dfs = []

for date in dates:
    df = sdr.fetch_allocations_holdings(date)
    df = df[df['indicator'] == 'holdings']
    df['month'] = f"{date[0]}-{date[1]:02d}"
    dfs.append(df)

# Combine
all_data = pd.concat(dfs)

# Pivot for easier comparison
comparison = all_data.pivot(index='entity', columns='month', values='value')

# Look at specific countries
countries = ['United States', 'China', 'Kenya']
print(comparison.loc[countries])

# Calculate change from Jan to Sep
comparison['change'] = comparison['2025-09'] - comparison['2025-01']
comparison['pct_change'] = (comparison['change'] / comparison['2025-01'] * 100).round(2)

print("\nCountries with largest changes:")
print(comparison.nlargest(5, 'pct_change')[['2025-01', '2025-09', 'pct_change']])
```

This shows which countries have increased or decreased their SDR holdings over the period.

## Working with Allocations

### Compare Allocations vs Holdings

See which countries hold more or less than their allocation:

```python
from imf_reader import sdr

df = sdr.fetch_allocations_holdings()

# Reshape data
df_wide = df.pivot(index=['entity', 'date'], columns='indicator', values='value').reset_index()

# Calculate difference
df_wide['difference'] = df_wide['holdings'] - df_wide['allocations']
df_wide['difference_billions'] = (df_wide['difference'] / 1e9).round(2)

# Sort by difference
df_wide = df_wide.sort_values('difference')

print("Countries that have used/sold SDRs (negative difference):")
print(df_wide[['entity', 'difference_billions']].head(10))

print("\nCountries holding more than allocation (positive difference):")
print(df_wide[['entity', 'difference_billions']].tail(10))
```

- **Negative difference**: Country has used/sold SDRs
- **Positive difference**: Country has acquired additional SDRs from others

### Filter by Region or Group

While the data doesn't include region tags, you can create your own filters:

```python
from imf_reader import sdr

df = sdr.fetch_allocations_holdings()

# Define country groups
g7_countries = ['United States', 'Japan', 'Germany', 'United Kingdom',
                'France', 'Italy', 'Canada']

# Filter for G7
g7_data = df[
    (df['entity'].isin(g7_countries)) &
    (df['indicator'] == 'holdings')
]

# Calculate total G7 holdings
total_g7 = g7_data['value'].astype(float).sum()
print(f"Total G7 SDR holdings: {total_g7/1e9:.2f} billion SDRs")

# Show individual countries
g7_data = g7_data.sort_values('value', ascending=False)
print(g7_data[['entity', 'value']])
```

## Data Quality Notes

### Missing Values

Some entities might have missing or zero values in certain months. Always check for and handle these appropriately:

```python
from imf_reader import sdr
import pandas as pd

df = sdr.fetch_allocations_holdings()

# Convert to numeric, which will turn invalid values to NaN
df['value'] = pd.to_numeric(df['value'], errors='coerce')

# Check for missing values
missing = df[df['value'].isna()]
if not missing.empty:
    print(f"Found {len(missing)} rows with missing values")
    print(missing)
```

### Data Frequency

SDR allocations and holdings are published monthly, typically with a one-month lag. If you request data for the current month, you may get an error or stale data. Always check `fetch_latest_allocations_holdings_date()` first if you need the absolute latest data.

## Practical Use Cases

### Monitor Reserve Asset Changes

Track how countries use SDRs as reserves:

```python
from imf_reader import sdr

# Get current data
df_current = sdr.fetch_allocations_holdings()
holdings_current = df_current[df_current['indicator'] == 'holdings']

# Get data from 6 months ago
latest = sdr.fetch_latest_allocations_holdings_date()
past_date = (latest[0], latest[1] - 6)  # 6 months earlier

df_past = sdr.fetch_allocations_holdings(past_date)
holdings_past = df_past[df_past['indicator'] == 'holdings']

# Compare
comparison = holdings_current.merge(
    holdings_past,
    on='entity',
    suffixes=('_current', '_past')
)

comparison['value_current'] = pd.to_numeric(comparison['value_current'])
comparison['value_past'] = pd.to_numeric(comparison['value_past'])
comparison['change'] = comparison['value_current'] - comparison['value_past']

# Show biggest changes
print("Largest increases in holdings:")
print(comparison.nlargest(10, 'change')[['entity', 'change']])
```

### Export for Reporting

Save data for use in other tools:

```python
from imf_reader import sdr

df = sdr.fetch_allocations_holdings()

# Export to CSV
df.to_csv('sdr_allocations_holdings.csv', index=False)

# Export to Excel
df.to_excel('sdr_allocations_holdings.xlsx', index=False)
```

## Performance and Caching

Like other imf-reader functions, `fetch_allocations_holdings()` uses caching. The first call for a specific date downloads data from the IMF website, but subsequent calls return instantly from cache:

```python
from imf_reader import sdr
import time

# First call: fetches from web
start = time.time()
df1 = sdr.fetch_allocations_holdings()
print(f"First call: {time.time() - start:.2f} seconds")

# Second call: returns from cache
start = time.time()
df2 = sdr.fetch_allocations_holdings()
print(f"Second call: {time.time() - start:.2f} seconds")
```

To clear the cache if you need fresh data, see the [Advanced Usage](advanced-usage.md#cache-management) section.

## Next Steps

- **[SDR Rates](sdr-rates.md)**: Access SDR interest and exchange rates
- **[WEO Data](weo-data.md)**: Work with macroeconomic indicators
- **[Advanced Usage](advanced-usage.md)**: Cache management and error handling
