[![PyPI](https://img.shields.io/pypi/v/imf-reader.svg)](https://pypi.org/project/imf-reader/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/imf_reader.svg)](https://pypi.org/project/imf_reader/)
[![Documentation Status](https://readthedocs.org/projects/imf-reader/badge/?version=latest)](https://imf-reader.readthedocs.io/en/latest/?badge=latest)
[![codecov](https://codecov.io/gh/ONEcampaign/imf-reader/branch/main/graph/badge.svg?token=YN8S1719NH)](https://codecov.io/gh/ONEcampaign/imf-reader)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

# imf-reader

**Simple Python access to IMF economic data.**

Access the World Economic Outlook (WEO) database and Special Drawing Rights (SDR) data programmatically. Get macroeconomic indicators, forecasts, SDR allocations, interest rates, and exchange rates—all as clean pandas DataFrames.

## Quick Start

Install with uv:

```bash
uv pip install imf-reader
```

Or with pip:

```bash
pip install imf-reader
```

Fetch your first dataset:

```python
from imf_reader import weo, sdr

# Get World Economic Outlook data
weo_data = weo.fetch_data()

# Get SDR allocations
sdr_data = sdr.fetch_allocations_holdings()
```

## What You Can Access

### World Economic Outlook (WEO)
- Macroeconomic indicators for ~200 countries
- GDP, inflation, unemployment, government finances, and 40+ indicators
- Historical data and forecasts
- Published twice yearly (April and October)

### Special Drawing Rights (SDR)
- Monthly allocations and holdings by country
- Historical interest rates (since 1969)
- Daily exchange rates (since 1981)
- SDR/USD and USD/SDR conversions

## Key Features

- **Simple API**: Just a few functions to learn
- **Pandas DataFrames**: Data returned in familiar format
- **Smart caching**: Fast repeated access with LRU cache
- **Automatic version handling**: Falls back gracefully when latest data isn't available
- **Type hints**: Full type annotations for better IDE support

## Documentation

📚 **[Read the full documentation](https://imf-reader.readthedocs.io/)**

- **[Getting Started](https://imf-reader.readthedocs.io/getting-started/)** - Installation and first examples
- **[WEO Data Guide](https://imf-reader.readthedocs.io/weo-data/)** - Access macroeconomic indicators
- **[SDR Data Guide](https://imf-reader.readthedocs.io/sdr-allocations/)** - Track international reserves
- **[Advanced Usage](https://imf-reader.readthedocs.io/advanced-usage/)** - Caching, error handling, and production patterns

## Example Usage

### Fetch and filter WEO data

```python
from imf_reader import weo

# Get the latest WEO release
df = weo.fetch_data()

# Filter for GDP data for specific countries
gdp_data = df[
    (df['CONCEPT_CODE'] == 'NGDPD') &
    (df['REF_AREA_LABEL'].isin(['United States', 'China', 'Germany']))
]

print(gdp_data[['REF_AREA_LABEL', 'TIME_PERIOD', 'OBS_VALUE']])
```

### Get SDR holdings and exchange rates

```python
from imf_reader import sdr

# Get latest SDR allocations and holdings
allocations = sdr.fetch_allocations_holdings()

# Get current SDR exchange rate
exchange_rates = sdr.fetch_exchange_rates()

# Calculate USD value of holdings
usd_per_sdr = exchange_rates.iloc[-1]['exchange_rate']
allocations['usd_value'] = allocations['value'].astype(float) * usd_per_sdr
```

### Fetch specific WEO version

```python
from imf_reader import weo

# Get October 2024 WEO release
df_oct = weo.fetch_data(version=("October", 2024))

# Get April 2025 release
df_apr = weo.fetch_data(version=("April", 2025))
```

## Requirements

- Python 3.10 or higher
- pandas, requests, beautifulsoup4 (installed automatically)

## Important Note

This package uses web scraping for datasets without official APIs. While we strive to maintain compatibility, changes to IMF website structure may temporarily affect functionality. The package includes automatic version fallback for improved reliability.

## Contributing

We welcome contributions! See our [Contributing Guide](https://imf-reader.readthedocs.io/contributing/) for details on:

- Reporting bugs
- Suggesting features
- Contributing code
- Improving documentation

## License

`imf-reader` was initially created by Luca Picci and is maintained by [The ONE Campaign](https://www.one.org/). Licensed under the MIT License.

## Credits

Created with [`cookiecutter`](https://cookiecutter.readthedocs.io/en/latest/) and the `py-pkgs-cookiecutter` [template](https://github.com/py-pkgs/py-pkgs-cookiecutter).
