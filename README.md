[![PyPI](https://img.shields.io/pypi/v/imf-reader.svg)](https://pypi.org/project/imf-reader/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/imf_reader.svg)](https://pypi.org/project/imf_reader/)
[![Documentation Status](https://readthedocs.org/projects/imf-reader/badge/?version=latest)](https://imf-reader.readthedocs.io/en/latest/?badge=latest)
[![codecov](https://codecov.io/gh/ONEcampaign/imf-reader/branch/main/graph/badge.svg?token=YN8S1719NH)](https://codecov.io/gh/ONEcampaign/imf-reader)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)


# imf-reader

A package to access IMF data. This package only supports access to the World Economic Outlook (WEO) database.
Support for other IMF data and databases may be added in the future.

WEO data is accessed through SDMX (Statistical Data and Metadata eXchange) files published by the IMF.
For more information on SDMX, please visit the [SDMX.org](https://sdmx.org/). 

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


Caching is used to avoid multiple requests to the IMF website for the same data and to enhance performance. 
Caching using the LRU (Least Recently Used) algorithm approach and stores data in RAM. The cache is cleared when the program is terminated.
To clear the cache manually, use the `clear_cache` function.

```python
weo.clear_cache()
```


For more advanced usage and tools for WEO data please use the [weo-reader package](https://github.com/epogrebnyak/weo-reader).


## Contributing

Interested in contributing? Check out the contributing guidelines. Please note that this project is released with a Code of Conduct. By contributing to this project, you agree to abide by its terms.

## License

`imf-reader` was initially created by Luca Picci and is maintained by the ONE Campaign. It is licensed under the terms of the MIT license.

## Credits

`imf-reader` was created with [`cookiecutter`](https://cookiecutter.readthedocs.io/en/latest/) and the `py-pkgs-cookiecutter` [template](https://github.com/py-pkgs/py-pkgs-cookiecutter).
