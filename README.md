[![PyPI version](https://img.shields.io/pypi/v/imf-reader?label=PyPI%20-%20version)](https://pypi.org/project/imf-reader/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/imf-reader.svg)](https://pypi.org/project/imf-reader/)
[![Anaconda version](https://img.shields.io/conda/vn/conda-forge/imf-reader?label=conda%20-%20version)](https://anaconda.org/channels/conda-forge/packages/imf-reader)
[![Docs](https://img.shields.io/badge/docs-imf--reader-blue)](https://docs.one.org/tools/imf-reader/)

# imf-reader

Python access to IMF World Economic Outlook and Special Drawing Rights data.

imf-reader fetches two IMF datasets that are hard to reach programmatically, the World
Economic Outlook (WEO) database and Special Drawing Rights (SDR) data, and returns them as
tidy pandas DataFrames.

WEO data comes from the IMF's SDMX API for releases from April 2025 onward and from a
discontinued bulk SDMX archive for everything before it, translated onto one vocabulary so
columns and codes match across both sources. SDR daily valuation and weekly interest rates
have no API, so imf-reader parses them from IMF web pages. SDR allocations and holdings do
exist on the API at monthly frequency, but this package has not moved to it and still parses
them from web pages too. Both sources make the package sensitive to changes in the IMF's site
structure or file formats. Please report any issues you encounter.

## Installation

```bash
pip install imf-reader
```

Or with uv:

```bash
uv add imf-reader
```

Or from conda-forge:

```bash
conda install imf-reader
```

## Usage

Fetch WEO data and filter it, for example Nigeria's real GDP growth:

```python
from imf_reader import weo

df = weo.fetch_data()
growth = df[
    (df.REF_AREA_CODE == "NGA")
    & (df.CONCEPT_CODE == "NGDP_RPCH")
    & (df.TIME_PERIOD.between(2020, 2024))
]
print(growth[["REF_AREA_LABEL", "TIME_PERIOD", "OBS_VALUE", "UNIT_LABEL"]].to_string(index=False))
```

**Output:**

```
REF_AREA_LABEL  TIME_PERIOD  OBS_VALUE UNIT_LABEL
       Nigeria         2020  -6.368898    Percent
       Nigeria         2021   1.109253    Percent
       Nigeria         2022   4.318829    Percent
       Nigeria         2023   3.315904    Percent
       Nigeria         2024   4.071067    Percent
```

`fetch_data()` returns observations. The IMF also publishes series-level metadata, one row per
series, covering methodology notes, classification codes, and fiscal-year reporting conventions:

```python
meta = weo.fetch_series_metadata()
merged = weo.fetch_data_with_metadata()
```

`fetch_series_metadata()` returns that metadata on its own, keyed on `REF_AREA_CODE`,
`CONCEPT_CODE`, and `FREQ_CODE`. `fetch_data_with_metadata()` returns the two merged, resolving
both halves to the same release. Series metadata covers April 2025 onward, the releases the IMF
API itself carries.

Fetch SDR allocations and holdings:

```python
from imf_reader import sdr

df = sdr.fetch_allocations_holdings()
```

This returns one row per entity per indicator, with `entity`, `indicator` (`holdings` or
`allocations`), `value`, and `date` columns.

Versions, caching, and the full column reference for both datasets are covered in the
documentation.

## Documentation

Full documentation lives at [docs.one.org/tools/imf-reader](https://docs.one.org/tools/imf-reader/).
Start with [Why imf-reader](https://docs.one.org/tools/imf-reader/why-imf-reader/) for the
motivation, [Getting started](https://docs.one.org/tools/imf-reader/getting-started/) for a
first walkthrough, and the [WEO](https://docs.one.org/tools/imf-reader/weo/) and
[SDR](https://docs.one.org/tools/imf-reader/sdr/) guides for dataset-specific detail.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines. This
project is released with a [Code of Conduct](CONDUCT.md). By contributing, you agree to
abide by its terms.

## License

`imf-reader` is licensed under the [MIT license](LICENSE). It was created by Luca Picci and
is maintained by the ONE Campaign.
</content>
