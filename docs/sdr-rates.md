# SDR Interest and Exchange Rates

The IMF publishes two important rate series for SDRs: interest rates (the rate paid on SDR holdings) and exchange rates (the value of SDRs relative to major currencies). These rates are essential for international financial transactions, reserve management, and economic analysis.

This guide shows you how to access and work with both SDR interest and exchange rates.

## SDR Interest Rates

The SDR interest rate is the rate paid to members on their SDR holdings and charged on their SDR allocations. It's calculated weekly as a weighted average of representative interest rates in major currencies (USD, EUR, JPY, GBP, CNY).

### Fetch Interest Rates

Get the complete historical series of SDR interest rates:

```python
from imf_reader import sdr

# Fetch SDR interest rates
df = sdr.fetch_interest_rates()

print(f"Data shape: {df.shape}")
print(f"Columns: {list(df.columns)}")
print("\nFirst 5 rows:")
print(df.head())
```

**Output:**
```
Data shape: (2240, 3)
Columns: ['interest_rate', 'effective_from', 'effective_to']

First 5 rows:
   interest_rate effective_from effective_to
0           1.50     1969-07-28   1974-06-30
1           5.00     1974-07-01   1974-12-31
2           5.00     1975-01-01   1975-07-07
3           3.75     1975-07-08   1975-12-31
4           3.50     1976-01-01   1976-06-30
```

The data includes over 2,200 rate observations going back to 1969 when SDRs were created.

### Understanding Interest Rate Data

| Column | Description | Example Values |
|--------|-------------|----------------|
| `interest_rate` | Annual interest rate (percent) | `1.50`, `5.00`, `2.819` |
| `effective_from` | Start date for this rate | `1969-07-28`, `2025-10-06` |
| `effective_to` | End date for this rate | `1974-06-30`, `2025-10-12` |

Each row represents a rate that was in effect for a specific period. Rates change weekly, so you'll see many short-lived periods in recent data.

### Current and Recent Rates

Get the most recent SDR interest rates:

```python
from imf_reader import sdr

df = sdr.fetch_interest_rates()

# Show the 10 most recent rates
print("Most recent SDR interest rates:")
print(df.tail(10))
```

**Output:**
```
      interest_rate effective_from effective_to
2235          2.819     2025-09-29   2025-10-05
2236          2.810     2025-10-06   2025-10-12
2237          2.798     2025-10-13   2025-10-19
2238          2.779     2025-10-20   2025-10-26
2239          2.758     2025-10-27   2025-11-02
```

The most recent rate (2.758% as of October 27, 2025) is the current SDR interest rate.

### Historical Trends

Analyze how SDR interest rates have changed over time:

```python
from imf_reader import sdr
import pandas as pd

df = sdr.fetch_interest_rates()

# Convert dates to datetime for easier filtering
df['effective_from'] = pd.to_datetime(df['effective_from'])
df['effective_to'] = pd.to_datetime(df['effective_to'])

# Get annual average rates
df['year'] = df['effective_from'].dt.year

# Calculate weighted average by duration of each rate
df['duration_days'] = (df['effective_to'] - df['effective_from']).dt.days

annual_rates = df.groupby('year').apply(
    lambda x: (x['interest_rate'] * x['duration_days']).sum() / x['duration_days'].sum()
).reset_index(name='avg_rate')

print("Annual average SDR interest rates (last 10 years):")
print(annual_rates.tail(10))
```

This shows you how the SDR interest rate has evolved, reflecting changes in global monetary policy.

### Filter by Date Range

Get rates for a specific time period:

```python
from imf_reader import sdr
import pandas as pd

df = sdr.fetch_interest_rates()

# Convert to datetime
df['effective_from'] = pd.to_datetime(df['effective_from'])

# Filter for 2020-2025
recent_rates = df[
    (df['effective_from'] >= '2020-01-01') &
    (df['effective_from'] < '2026-01-01')
]

print(f"Found {len(recent_rates)} rate changes between 2020-2025")
print("\nSummary statistics:")
print(recent_rates['interest_rate'].describe())
```

This helps you analyze rate volatility and trends during specific periods.

## SDR Exchange Rates

The SDR exchange rate determines how much one SDR is worth in terms of major currencies. The IMF publishes daily SDR exchange rates, primarily against the U.S. dollar.

### Fetch Exchange Rates (USD per SDR)

By default, exchange rates show how many U.S. dollars equal one SDR:

```python
from imf_reader import sdr

# Fetch exchange rates (default: USD per SDR)
df = sdr.fetch_exchange_rates()

print(f"Data shape: {df.shape}")
print(f"Columns: {list(df.columns)}")
print("\nLast 10 days:")
print(df.tail(10))
```

**Output:**
```
Data shape: (11435, 2)
Columns: ['date', 'exchange_rate']

Last 10 days:
            date  exchange_rate
11425 2025-10-10        1.36031
11426 2025-10-14        1.35958
11427 2025-10-15        1.36377
11428 2025-10-16        1.36565
11429 2025-10-17        1.36767
11430 2025-10-20        1.36568
11431 2025-10-21        1.36354
11432 2025-10-22        1.36166
11433 2025-10-23        1.36143
11434 2025-10-24        1.36208
```

In October 2025, one SDR equals approximately 1.36 U.S. dollars.

The data includes over 11,000 daily observations going back to 1981.

### Fetch Exchange Rates (SDR per USD)

You can also get the inverse: how many SDRs equal one U.S. dollar:

```python
from imf_reader import sdr

# Fetch exchange rates in SDR per USD
df = sdr.fetch_exchange_rates("USD")

print("SDR per USD (last 10 days):")
print(df.tail(10))
```

**Output:**
```
            date  exchange_rate
11425 2025-10-10       0.735129
11426 2025-10-14       0.735523
11427 2025-10-15       0.733263
11428 2025-10-16       0.732254
11429 2025-10-17       0.731170
11430 2025-10-20       0.732235
11431 2025-10-21       0.733384
11432 2025-10-22       0.734398
11433 2025-10-23       0.734520
11434 2025-10-24       0.734169
```

One U.S. dollar equals approximately 0.73 SDRs.

### Understanding Exchange Rate Data

| Column | Description | Example Values |
|--------|-------------|----------------|
| `date` | Date of the exchange rate | `2025-10-24`, `1981-01-02` |
| `exchange_rate` | Exchange rate value | `1.36208` (USD/SDR) or `0.734169` (SDR/USD) |

The exchange rate is published on business days only—you won't see rates for weekends or holidays.

### Recent Exchange Rate Trends

Plot or analyze recent exchange rate movements:

```python
from imf_reader import sdr
import pandas as pd

df = sdr.fetch_exchange_rates()

# Convert date to datetime
df['date'] = pd.to_datetime(df['date'])

# Get last 30 days
df_recent = df.tail(30)

print("Recent SDR/USD exchange rate statistics:")
print(df_recent['exchange_rate'].describe())

# Calculate daily changes
df_recent['daily_change'] = df_recent['exchange_rate'].diff()
df_recent['pct_change'] = df_recent['exchange_rate'].pct_change() * 100

print("\nDays with largest changes:")
print(df_recent.nlargest(5, 'pct_change')[['date', 'exchange_rate', 'pct_change']])
```

This helps you understand SDR volatility relative to the dollar.

### Historical Exchange Rates

Analyze long-term trends:

```python
from imf_reader import sdr
import pandas as pd

df = sdr.fetch_exchange_rates()

# Convert date to datetime
df['date'] = pd.to_datetime(df['date'])
df['year'] = df['date'].dt.year

# Calculate annual averages
annual_avg = df.groupby('year')['exchange_rate'].mean().reset_index()

print("Annual average USD per SDR (last 10 years):")
print(annual_avg.tail(10))
```

**Example output:**
```
   year  exchange_rate
45   2016       1.383240
46   2017       1.402581
47   2018       1.398068
48   2019       1.377863
49   2020       1.381842
50   2021       1.421956
51   2022       1.334642
52   2023       1.324875
53   2024       1.340256
54   2025       1.358924
```

This shows how the SDR has appreciated or depreciated against the dollar over time.

### Filter by Date Range

Get exchange rates for a specific period:

```python
from imf_reader import sdr
import pandas as pd

df = sdr.fetch_exchange_rates()

# Convert to datetime
df['date'] = pd.to_datetime(df['date'])

# Filter for 2024
rates_2024 = df[(df['date'] >= '2024-01-01') & (df['date'] < '2025-01-01')]

print(f"Found {len(rates_2024)} trading days in 2024")
print(f"High: {rates_2024['exchange_rate'].max():.5f} USD/SDR")
print(f"Low: {rates_2024['exchange_rate'].min():.5f} USD/SDR")
print(f"Average: {rates_2024['exchange_rate'].mean():.5f} USD/SDR")
```

## Converting Between SDR and USD

### Convert SDR Holdings to USD

If you have SDR holdings data and want to know the USD value:

```python
from imf_reader import sdr
import pandas as pd

# Get latest allocations (in SDR units)
allocations = sdr.fetch_allocations_holdings()

# Get latest exchange rate
exchange_rates = sdr.fetch_exchange_rates()
latest_rate = exchange_rates.iloc[-1]['exchange_rate']  # USD per SDR

print(f"Latest exchange rate: {latest_rate:.5f} USD per SDR")

# Convert Kenya's holdings to USD
kenya = allocations[
    (allocations['entity'] == 'Kenya') &
    (allocations['indicator'] == 'holdings')
]

sdr_holdings = float(kenya['value'].values[0])
usd_value = sdr_holdings * latest_rate

print(f"\nKenya SDR holdings: {sdr_holdings:,.0f} SDR")
print(f"USD equivalent: ${usd_value:,.2f}")
```

**Output:**
```
Latest exchange rate: 1.36208 USD per SDR

Kenya SDR holdings: 202,710,875 SDR
USD equivalent: $276,067,951.67
```

### Convert USD Amounts to SDR

If you have USD amounts and need SDR equivalents:

```python
from imf_reader import sdr

# Get latest exchange rate (SDR per USD)
exchange_rates = sdr.fetch_exchange_rates("USD")
latest_rate = exchange_rates.iloc[-1]['exchange_rate']  # SDR per USD

# Convert $100 million to SDR
usd_amount = 100_000_000
sdr_amount = usd_amount * latest_rate

print(f"Exchange rate: {latest_rate:.6f} SDR per USD")
print(f"$100 million = {sdr_amount:,.2f} SDR")
```

## Combining Rates with Allocations

### Calculate Interest Earnings

Estimate interest earned on SDR holdings:

```python
from imf_reader import sdr

# Get latest holdings
allocations = sdr.fetch_allocations_holdings()
us_holdings = allocations[
    (allocations['entity'] == 'United States') &
    (allocations['indicator'] == 'holdings')
]

sdr_amount = float(us_holdings['value'].values[0])

# Get current interest rate
interest_rates = sdr.fetch_interest_rates()
current_rate = interest_rates.iloc[-1]['interest_rate']

# Calculate annual interest
annual_interest = sdr_amount * (current_rate / 100)

print(f"US SDR holdings: {sdr_amount:,.0f} SDR")
print(f"Current interest rate: {current_rate}%")
print(f"Annual interest (approximate): {annual_interest:,.0f} SDR")

# Convert to USD
exchange_rates = sdr.fetch_exchange_rates()
usd_per_sdr = exchange_rates.iloc[-1]['exchange_rate']
interest_usd = annual_interest * usd_per_sdr

print(f"Annual interest in USD: ${interest_usd:,.2f}")
```

This gives you an estimate of the interest income on SDR holdings.

## Data Quality Notes

### Business Days Only

Exchange rates are only published on business days. If you're doing daily analysis, you'll need to handle gaps for weekends and holidays:

```python
from imf_reader import sdr
import pandas as pd

df = sdr.fetch_exchange_rates()
df['date'] = pd.to_datetime(df['date'])

# Forward fill to get weekend values
df = df.set_index('date')
df = df.reindex(pd.date_range(df.index.min(), df.index.max(), freq='D'))
df['exchange_rate'] = df['exchange_rate'].fillna(method='ffill')

print("Now includes weekends with forward-filled rates")
print(df.tail(10))
```

### Interest Rate Periods

Interest rates are set weekly, but the effective periods may vary. Always check both `effective_from` and `effective_to` dates when working with historical rates.

## Performance and Caching

Both `fetch_interest_rates()` and `fetch_exchange_rates()` use caching. The first call downloads data; subsequent calls return instantly:

```python
from imf_reader import sdr
import time

# First call: downloads
start = time.time()
df1 = sdr.fetch_exchange_rates()
print(f"First call: {time.time() - start:.2f} seconds")

# Second call: cached
start = time.time()
df2 = sdr.fetch_exchange_rates()
print(f"Second call: {time.time() - start:.2f} seconds")
```

See [Advanced Usage](advanced-usage.md#cache-management) for cache management details.

## Next Steps

- **[SDR Allocations](sdr-allocations.md)**: Track SDR holdings by country
- **[WEO Data](weo-data.md)**: Access macroeconomic indicators
- **[Advanced Usage](advanced-usage.md)**: Cache management and error handling
