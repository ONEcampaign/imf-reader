# imf-reader

Accessing IMF economic data programmatically shouldn't require building web scrapers from scratch. Many IMF datasets—like the World Economic Outlook (WEO) macroeconomic indicators and Special Drawing Rights (SDR) data—lack official APIs or have limited programmatic access. This means researchers, economists, and data engineers face a choice: manually download spreadsheets or write custom scraping code that breaks whenever the IMF updates their website.

**imf-reader** solves this problem. It provides a simple, reliable Python interface to IMF data that would otherwise require manual downloads or fragile web scraping. The package handles the complexity of fetching data from IMF web services, parsing different data formats, and presenting everything as clean pandas DataFrames ready for analysis.

Whether you're building economic forecasting models, tracking international reserves, or analyzing macroeconomic trends across countries, imf-reader gives you programmatic access to IMF data with just a few lines of code.

## Key Features

### World Economic Outlook (WEO) Data
Access comprehensive macroeconomic indicators and forecasts for ~200 countries:

```python
from imf_reader import weo

# Fetch the latest WEO release
df = weo.fetch_data()

# Get GDP data for specific countries
gdp = df[df['CONCEPT_CODE'] == 'NGDP_D']
```

Returns data with 531,000+ observations covering GDP, inflation, unemployment, government finances, and 40+ other indicators.

### Special Drawing Rights (SDR) Data
Track international reserve assets with monthly frequency:

```python
from imf_reader import sdr

# Get latest SDR allocations and holdings
allocations = sdr.fetch_allocations_holdings()

# Fetch SDR interest rates
interest_rates = sdr.fetch_interest_rates()

# Get SDR exchange rates
exchange_rates = sdr.fetch_exchange_rates()
```

Access allocations for 190+ member countries, plus historical interest rates back to 1969 and daily exchange rates since 1981.

### Smart Features

- **Automatic version handling**: Fetches the latest WEO release and falls back gracefully if it's not yet available
- **Built-in caching**: Reduces redundant requests with LRU cache for faster repeated access
- **Clean data structures**: All data returned as pandas DataFrames with consistent column names
- **Error handling**: Clear exceptions and informative logging when data isn't available

## Quick Start

Install with uv:

```bash
uv pip install imf-reader
```

Fetch your first dataset:

```python
from imf_reader import weo, sdr

# Get World Economic Outlook data
weo_data = weo.fetch_data()

# Get SDR allocations
sdr_data = sdr.fetch_allocations_holdings()
```

## What's Next?

- **[Getting Started](getting-started.md)**: Installation and first examples
- **[WEO Data](weo-data.md)**: Access macroeconomic indicators and forecasts
- **[SDR Allocations](sdr-allocations.md)**: Track international reserve allocations
- **[SDR Rates](sdr-rates.md)**: Work with interest and exchange rates
- **[Advanced Usage](advanced-usage.md)**: Caching, error handling, and best practices

## Requirements

- Python 3.10 or higher
- pandas, requests, beautifulsoup4 (installed automatically)

## Important Note

This package uses web scraping for datasets without official APIs. While we strive to maintain compatibility, changes to IMF website structure may temporarily affect functionality. The package includes automatic version fallback for WEO data to improve reliability.

## License

MIT License - see the [GitHub repository](https://github.com/ONEcampaign/imf-reader) for details.
