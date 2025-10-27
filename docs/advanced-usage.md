# Advanced Usage

This guide covers advanced topics including cache management, error handling, performance optimization, and integration patterns for production use.

## Cache Management

All imf-reader functions use LRU (Least Recently Used) caching to avoid redundant requests to IMF servers. Understanding how caching works helps you optimize performance and troubleshoot data freshness issues.

### How Caching Works

When you call a function like `weo.fetch_data()` or `sdr.fetch_allocations_holdings()`:

1. The function checks if data for these exact parameters is already cached in memory
2. If cached, it returns the data immediately (< 1ms)
3. If not cached, it fetches from the IMF website (10-30 seconds for WEO, 1-5 seconds for SDR)
4. The fetched data is stored in cache for future calls

**Important**: The cache is in-memory only. It clears when your Python process terminates.

### Cache Behavior Example

```python
from imf_reader import weo
import time

# First call: downloads and caches
start = time.time()
df1 = weo.fetch_data()
print(f"First call: {time.time() - start:.2f} seconds")  # ~15-30 seconds

# Second call: returns from cache
start = time.time()
df2 = weo.fetch_data()
print(f"Second call: {time.time() - start:.2f} seconds")  # ~0.01 seconds

# Same reference - literally the same object
print(f"Same data: {df1 is df2}")  # True
```

**Output:**
```
First call: 18.45 seconds
Second call: 0.01 seconds
Same data: True
```

### Clearing WEO Cache

If you need to force a fresh fetch (e.g., if you know new data was just published):

```python
from imf_reader import weo

# Clear the cache
weo.clear_cache()

# Next fetch will download fresh data
df = weo.fetch_data()
```

### Clearing SDR Cache

SDR functions share a common cache:

```python
from imf_reader import sdr

# Clear all SDR caches
sdr.clear_cache()

# Next calls will fetch fresh data
allocations = sdr.fetch_allocations_holdings()
rates = sdr.fetch_interest_rates()
exchange = sdr.fetch_exchange_rates()
```

### When to Clear Cache

Clear the cache when:

- **New data published**: IMF just released a new WEO or updated SDR data
- **Data looks stale**: You suspect you're seeing old data
- **Memory concerns**: You're processing many different data versions and want to free memory
- **Testing**: You want to verify behavior with fresh fetches

**Don't** clear cache:

- Between normal operations with the same data
- In tight loops (you'll hammer IMF servers unnecessarily)
- Just because "it seems safer" (caching is intentional and beneficial)

### Cache Scope

Each function has its own cache:

```python
from imf_reader import weo, sdr

# These caches are independent
df1 = weo.fetch_data()  # Cached separately
df2 = sdr.fetch_allocations_holdings()  # Different cache

# Clearing one doesn't affect the other
weo.clear_cache()  # Only clears WEO cache
sdr.clear_cache()  # Only clears SDR cache
```

## Error Handling

imf-reader provides specific exceptions to help you handle errors gracefully.

### Common Exceptions

```python
from imf_reader.config import NoDataError
from imf_reader import weo

try:
    # Try to fetch data that doesn't exist
    df = weo.fetch_data(version=("April", 2030))
except NoDataError as e:
    print(f"Data not available: {e}")
except TypeError as e:
    print(f"Invalid parameters: {e}")
```

### Exception Types

| Exception | When It Occurs | How to Handle |
|-----------|----------------|---------------|
| `NoDataError` | Requested version/date doesn't exist | Check if data is published, use fallback version |
| `TypeError` | Invalid parameter format | Check parameter types (month must be string, year must be int) |
| `ConnectionError` | Network issues | Retry with backoff, check internet connection |
| `UnexpectedFileError` | IMF changed data format | Report issue, use older version |

### Handling Missing Data

```python
from imf_reader import weo
from imf_reader.config import NoDataError
import logging

def fetch_weo_with_fallback(preferred_version=None):
    """Fetch WEO data with automatic fallback."""
    try:
        if preferred_version:
            return weo.fetch_data(version=preferred_version)
        else:
            return weo.fetch_data()
    except NoDataError as e:
        logging.warning(f"Preferred data not available: {e}")
        # Fall back to latest available
        return weo.fetch_data()

# Usage
df = fetch_weo_with_fallback(version=("October", 2025))
```

### Network Error Handling

```python
from imf_reader import sdr
import time

def fetch_with_retry(func, max_retries=3, delay=5):
    """Fetch data with exponential backoff retry."""
    for attempt in range(max_retries):
        try:
            return func()
        except ConnectionError as e:
            if attempt == max_retries - 1:
                raise
            wait_time = delay * (2 ** attempt)
            print(f"Connection failed, retrying in {wait_time}s...")
            time.sleep(wait_time)

# Usage
df = fetch_with_retry(lambda: sdr.fetch_allocations_holdings())
```

### Logging

imf-reader includes built-in logging. Enable it to see what's happening:

```python
import logging
from imf_reader import weo

# Enable INFO-level logging
logging.basicConfig(level=logging.INFO)

# Now you'll see messages like:
# INFO: No data found for expected latest version: October 2025. Rolling back version...
# INFO: Data fetched successfully for version: April 2025

df = weo.fetch_data()
```

Set to `logging.DEBUG` for even more detail:

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

## Performance Optimization

### Minimize Redundant Fetches

Cache is your friend. Design your code to fetch once and reuse:

```python
from imf_reader import weo

# Good: Fetch once, use many times
df = weo.fetch_data()

us_data = df[df['REF_AREA_LABEL'] == 'United States']
china_data = df[df['REF_AREA_LABEL'] == 'China']
gdp_data = df[df['CONCEPT_CODE'] == 'NGDPD']

# Bad: Multiple fetches (but still cached, so not terrible)
us_data = weo.fetch_data()[weo.fetch_data()['REF_AREA_LABEL'] == 'United States']
```

### Parallel Fetching

If you need multiple independent datasets, fetch them in parallel:

```python
from imf_reader import weo, sdr
from concurrent.futures import ThreadPoolExecutor
import time

def fetch_all_data():
    """Fetch multiple datasets in parallel."""
    with ThreadPoolExecutor(max_workers=3) as executor:
        # Submit all fetch operations
        weo_future = executor.submit(weo.fetch_data)
        alloc_future = executor.submit(sdr.fetch_allocations_holdings)
        rates_future = executor.submit(sdr.fetch_interest_rates)

        # Wait for all to complete
        weo_data = weo_future.result()
        alloc_data = alloc_future.result()
        rates_data = rates_future.result()

    return weo_data, alloc_data, rates_data

start = time.time()
weo_df, alloc_df, rates_df = fetch_all_data()
print(f"Fetched all data in {time.time() - start:.2f} seconds")
```

Parallel fetching can reduce total time from 30+ seconds to under 20 seconds for cold cache.

### Memory Considerations

WEO data can be large (500,000+ rows). If memory is a concern:

```python
from imf_reader import weo

# Fetch full dataset
df = weo.fetch_data()

# Immediately filter to what you need
us_gdp = df[
    (df['REF_AREA_LABEL'] == 'United States') &
    (df['CONCEPT_CODE'] == 'NGDPD')
].copy()

# Delete the large DataFrame to free memory
del df

# Work with the smaller filtered data
print(us_gdp.head())
```

### Persistent Caching (Advanced)

For production systems that need persistent caching across restarts, implement your own cache layer:

```python
from imf_reader import weo
import pickle
from pathlib import Path
from datetime import datetime, timedelta

class PersistentWEOCache:
    def __init__(self, cache_dir='.cache'):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

    def get_cache_path(self, version):
        month, year = version or ('latest', 0)
        return self.cache_dir / f'weo_{year}_{month}.pkl'

    def fetch_cached(self, version=None, max_age_days=7):
        """Fetch with persistent file cache."""
        cache_path = self.get_cache_path(version)

        # Check if cache exists and is fresh
        if cache_path.exists():
            cache_age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
            if cache_age < timedelta(days=max_age_days):
                print(f"Loading from cache: {cache_path}")
                with open(cache_path, 'rb') as f:
                    return pickle.load(f)

        # Fetch fresh data
        print("Fetching fresh data...")
        df = weo.fetch_data(version=version)

        # Save to cache
        with open(cache_path, 'wb') as f:
            pickle.dump(df, f)

        return df

# Usage
cache = PersistentWEOCache()
df = cache.fetch_cached()  # Uses file cache across program restarts
```

## Integration Patterns

### Scheduled Data Updates

For automated systems that need fresh data:

```python
from imf_reader import weo, sdr
from datetime import datetime
import schedule
import time

def update_economic_data():
    """Fetch latest IMF data and update your database."""
    print(f"Updating data at {datetime.now()}")

    # Clear caches to ensure fresh data
    weo.clear_cache()
    sdr.clear_cache()

    # Fetch latest data
    weo_data = weo.fetch_data()
    sdr_data = sdr.fetch_allocations_holdings()

    # Your custom logic here: save to database, trigger analysis, etc.
    print(f"Updated: WEO {weo_data.shape[0]} rows, SDR {sdr_data.shape[0]} rows")

# Schedule updates
schedule.every().monday.at("09:00").do(update_economic_data)  # Weekly on Monday
schedule.every().day.at("08:00").do(update_economic_data)  # Daily at 8 AM

# Run scheduled tasks
while True:
    schedule.run_pending()
    time.sleep(60)
```

### Data Pipeline Integration

Integrate with pandas-based data pipelines:

```python
from imf_reader import weo
import pandas as pd

def load_weo_gdp(countries, start_year=2010):
    """Load GDP data for analysis pipeline."""
    # Fetch data
    df = weo.fetch_data()

    # Filter and transform
    gdp = df[
        (df['CONCEPT_CODE'] == 'NGDPD') &
        (df['REF_AREA_LABEL'].isin(countries)) &
        (df['TIME_PERIOD'].astype(int) >= start_year)
    ][['REF_AREA_LABEL', 'TIME_PERIOD', 'OBS_VALUE']].copy()

    # Clean and reshape
    gdp['TIME_PERIOD'] = gdp['TIME_PERIOD'].astype(int)
    gdp['OBS_VALUE'] = pd.to_numeric(gdp['OBS_VALUE'])
    gdp = gdp.rename(columns={
        'REF_AREA_LABEL': 'country',
        'TIME_PERIOD': 'year',
        'OBS_VALUE': 'gdp_usd_billions'
    })

    return gdp.sort_values(['country', 'year'])

# Use in your pipeline
countries = ['United States', 'China', 'Germany']
gdp_data = load_weo_gdp(countries, start_year=2015)
```

### API Wrapper

Wrap imf-reader for your application's specific needs:

```python
from imf_reader import weo, sdr
from typing import Optional, List
import pandas as pd

class IMFDataClient:
    """High-level client for IMF data access."""

    def get_gdp_series(self, country: str, start_year: int = 2000) -> pd.DataFrame:
        """Get GDP time series for a country."""
        df = weo.fetch_data()
        return df[
            (df['CONCEPT_CODE'] == 'NGDPD') &
            (df['REF_AREA_LABEL'] == country) &
            (df['TIME_PERIOD'].astype(int) >= start_year)
        ][['TIME_PERIOD', 'OBS_VALUE']]

    def get_sdr_holdings_usd(self, country: str) -> float:
        """Get current SDR holdings in USD."""
        # Get holdings
        alloc = sdr.fetch_allocations_holdings()
        holdings_sdr = float(alloc[
            (alloc['entity'] == country) &
            (alloc['indicator'] == 'holdings')
        ]['value'].values[0])

        # Get exchange rate
        rates = sdr.fetch_exchange_rates()
        usd_per_sdr = rates.iloc[-1]['exchange_rate']

        return holdings_sdr * usd_per_sdr

    def clear_all_caches(self):
        """Clear all caches."""
        weo.clear_cache()
        sdr.clear_cache()

# Usage
client = IMFDataClient()
us_gdp = client.get_gdp_series('United States', start_year=2015)
kenya_sdr_usd = client.get_sdr_holdings_usd('Kenya')
```

## Important Limitations

### Web Scraping Fragility

imf-reader uses web scraping for data without official APIs. This means:

- **IMF website changes can break functionality**: If the IMF changes their HTML structure or data formats, the package may fail until updated
- **No SLA or guarantees**: The IMF can change their website at any time
- **Updates required**: Keep the package updated to get fixes for website changes

**Mitigation**:
- Pin package versions in production for stability
- Monitor for errors and have fallback data sources
- Subscribe to package updates on GitHub

### Data Publication Schedules

- **WEO**: Published twice yearly (April and October), usually mid-month
- **SDR allocations**: Published monthly, typically 2-4 weeks after month-end
- **SDR rates**: Published on business days only

If you request data before it's published, you'll get errors or stale data. Always check latest available dates first.

### Rate Limits

Be respectful of IMF servers:

- Cache is your friend—use it
- Don't hammer the API in tight loops
- Consider persistent caching for production
- Implement retry logic with exponential backoff

## Troubleshooting

### "No data found" Errors

**Problem**: `NoDataError: No data found for expected latest version`

**Solutions**:
- The data may not be published yet (check IMF release calendar)
- Let the automatic fallback work (don't specify version)
- Try a previous version explicitly

### Stale Data

**Problem**: Data looks old even though you just fetched it

**Solutions**:
```python
from imf_reader import weo, sdr

# Clear caches
weo.clear_cache()
sdr.clear_cache()

# Fetch again
df = weo.fetch_data()
```

### Import Errors

**Problem**: `ModuleNotFoundError: No module named 'imf_reader'`

**Solutions**:
```bash
# Reinstall the package
uv pip install --upgrade imf-reader

# Or if using pip
pip install --upgrade imf-reader
```

### Slow Performance

**Problem**: Every fetch takes 20+ seconds

**Causes**:
- First fetch after clearing cache (expected)
- Not using cache properly (fetching same data multiple times)
- Network issues

**Solutions**:
- Verify cache is working (second fetch should be instant)
- Fetch once, filter many times
- Check your network connection

## Next Steps

- **[WEO Data](weo-data.md)**: Deep dive into working with WEO data
- **[SDR Allocations](sdr-allocations.md)**: Analyze SDR holdings
- **[Contributing](contributing.md)**: Help improve imf-reader
