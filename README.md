[![PyPI](https://img.shields.io/pypi/v/imf-reader.svg)](https://pypi.org/project/imf-reader/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/imf_reader.svg)](https://pypi.org/project/imf_reader/)
[![Documentation Status](https://readthedocs.org/projects/imf-reader/badge/?version=latest)](https://imf-reader.readthedocs.io/en/latest/?badge=latest)
[![codecov](https://codecov.io/gh/ONEcampaign/imf-reader/branch/main/graph/badge.svg?token=YN8S1719NH)](https://codecov.io/gh/ONEcampaign/imf-reader)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)


# imf-reader

A package to access IMF data. 

This package supports access to IMF data with no/limited accessibility through the API,
including the World Economic Outlook (WEO) database and Special Drawing Rights (SDR) data

__NOTE__:

This package is designed to scrape data from the IMF website. 
The IMF does not provide an official API for accessing WEO data yet. As a result, 
the tools in this package are subject to breakage if the IMF changes the structure of their website,
or releases corrupted data files or unexpected data formats. Please report any issues you encounter.

## Installation

```bash
$ pip install imf-reader
```

## Usage

### 1. World Economic Outlook (WEO) data

WEO data is accessed through SDMX (Statistical Data and Metadata eXchange) files published by the IMF.
For more information on SDMX, please visit the [SDMX.org](https://sdmx.org/).

Tools to access WEO data can be found in the `weo` module.
Import the `weo` module and call the `fetch_data` function to retrieve the latest WEO data.

```python
from imf_reader import weo

df = weo.fetch_data()
print(df)

```

By default, the function will return the WEO data for the latest year available.
You can specify a version by passing the month and year of the version you want to retrieve.
NOTE: The WEO reports are released in April and October of each year. The month of the version must 
be either "April" or "October".

```python
df = weo.fetch_data(version=("April", 2020))
```

If the version of the data fetched is needed, it can be 
retrieved from the function attribute `last_version_fetched`.

```python
df = weo.fetch_data()
print(weo.fetch_data.last_version_fetched)
# >>> ('April', 2024) or whichever version was just fetched
```


#### Caching

Caching is used to avoid multiple requests to the IMF website for the same data and to enhance
performance. See the [Caching](#caching) section below for full details on cache location,
environment variable overrides, and how to clear or redirect the cache.


For more advanced usage and tools for WEO data please use the [weo-reader package](https://github.com/epogrebnyak/weo-reader).


### 2. Special Drawing Rights (SDR) data

The SDR is an international reserve asset created by the IMF in 1969.
It is not a currency, but the holder of SDRs can exchange them for usable currencies in times of need.

Read more about SDRs at: https://www.imf.org/en/About/Factsheets/Sheets/2023/special-drawing-rights-sdr


Import the module

```python
from imf_reader import sdr
```

Read allocations and holdings data.

```python
sdr.fetch_allocations_holdings()
```
SDRs holdings and allocations are published at a monthly frequency. The function fetches the latest data available by
default. Check the latest available date

```python
sdr.fetch_latest_allocations_holdings_date()
```

To retrieve SDR holdings and allocations for a specific month and year, eg April 2021, pass the year and month as a tuple

```python
sdr.fetch_allocations_holdings((2021, 4))
```

Read interest rates. This function gets the historical interest rates for SDRs up to the most recent value available.

```python
sdr.fetch_interest_rates()
```

Read exchange rates. This function gets the historical exchange rates for SDRs up to the most recent value available.

```python
sdr.fetch_exchange_rates()
```
By default, the exchange rate is in USDs per 1 SDR. To get the exchange rate in SDRs per 1 USD, pass the unit basis as "USD"

```python
sdr.fetch_exchange_rates("USD")
```

To clear cached SDR data, see the [Caching](#caching) section below.


## Caching

`imf-reader` caches data to disk to avoid redundant requests and to survive process restarts.

### Cache location

The cache is stored in the platform-appropriate user cache directory, segmented by package
version so that upgrading the package starts with a clean cache automatically:

- **Linux:** `~/.cache/imf_reader/<version>/` (e.g. `~/.cache/imf_reader/1.5.0/`)
- **macOS:** `~/Library/Caches/imf_reader/<version>/`
- **Windows:** `%LOCALAPPDATA%\imf_reader\<version>\`

The version segment ensures that a package upgrade never silently serves data that was shaped
by an older version of the code.

### Overriding the cache directory

Set the `IMF_READER_CACHE_DIR` environment variable before importing the package:

```bash
export IMF_READER_CACHE_DIR=/path/to/my/cache
```

Or redirect programmatically at runtime:

```python
from imf_reader import cache

cache.set_cache_dir("/path/to/my/cache")
cache.get_cache_dir()       # inspect the current path
cache.reset_cache_dir()     # restore to the default platformdirs path
```

### Clearing the cache

The canonical way to clear all cached data:

```python
from imf_reader import cache

cache.clear_cache()                  # clear everything
cache.clear_cache(scope="weo")       # WEO data only
cache.clear_cache(scope="sdr")       # SDR data only
cache.clear_cache(scope="http")      # HTTP-layer cache only
cache.clear_cache(scope="all")       # equivalent to no scope argument
```

A scoped clear only touches the named scope: `cache.clear_cache(scope="sdr")`
removes SDR data and leaves the WEO and HTTP caches intact. The HTTP-layer
clear additionally closes the active cached HTTP session so subsequent calls
hit the network rather than reusing a dropped on-disk SQLite cache.

The legacy module-level helpers still work but emit a `DeprecationWarning` pointing at
`cache.clear_cache()`. They will be removed in v2.0:

```python
from imf_reader import weo, sdr

weo.clear_cache()   # deprecated — use cache.clear_cache(scope="weo")
sdr.clear_cache()   # deprecated — use cache.clear_cache(scope="sdr")
```

### Disabling the cache for development

Disable the cache for the lifetime of the current process. While disabled,
no payloads are written under the cache directory: bulk downloads land in a
system temp file used only for the current call, and dataframe results are
returned without being persisted.

```python
from imf_reader import cache

cache.disable_cache()
# ... work without caching ...
cache.enable_cache()
```

### Corrupted bulk downloads

If a WEO bulk SDMX download is corrupted, it is automatically evicted from the cache and a
`cache.BulkPayloadCorruptError` is raised. Re-running the same call will trigger a fresh
download:

```python
from imf_reader import cache

try:
    df = weo.fetch_data()
except cache.BulkPayloadCorruptError:
    df = weo.fetch_data()
```

## Contributing

This package relies on webscraping techniques to access data from the source. It is likely
that the functionality of this package will break if the IMF changes the structure of their website
or their data files. If you encounter any issues, please report them.

Interested in contributing? Check out the contributing guidelines. Please note that this project is released with a Code of Conduct. By contributing to this project, you agree to abide by its terms.

## License

`imf-reader` was initially created by Luca Picci and is maintained by the ONE Campaign. It is licensed under the terms of the MIT license.

## Credits

`imf-reader` was created with [`cookiecutter`](https://cookiecutter.readthedocs.io/en/latest/) and the `py-pkgs-cookiecutter` [template](https://github.com/py-pkgs/py-pkgs-cookiecutter).
