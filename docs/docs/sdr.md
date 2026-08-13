# Special Drawing Rights

The Special Drawing Rights (SDR) is an international reserve asset the IMF created in 1969, exchangeable for usable currencies. Read more in the IMF's [SDR factsheet](https://www.imf.org/en/About/Factsheets/Sheets/2023/special-drawing-rights-sdr).

The IMF publishes no API for SDR data. The `sdr` module works by parsing pages on the IMF website, so it is sensitive to the IMF restructuring those pages.

## Holdings and allocations

`fetch_allocations_holdings()` fetches the latest available month:

```python
from imf_reader import sdr

df = sdr.fetch_allocations_holdings()
```

The returned frame is long-format, one row per entity per indicator:

| Column      | Holds                       |
| ----------- | --------------------------- |
| `entity`    | The reporting entity        |
| `indicator` | `holdings` or `allocations` |
| `value`     | The reported amount         |
| `date`      | The month the data covers   |

SDR holdings and allocations are published monthly. Pass a `(year, month)` tuple to fetch a specific one:

```python
from imf_reader import sdr

df = sdr.fetch_allocations_holdings((2021, 4))
```

A date later than the latest available month raises `ValueError`, naming the latest available date.

## Check the latest available month

```python
from imf_reader import sdr

latest = sdr.fetch_latest_allocations_holdings_date()
```

Returns a `(year, month)` tuple.

!!! warning "Heads up"

    SDR and WEO order their date arguments differently. SDR takes `(year, month)` as integers, WEO takes `(month, year)` with the month as a name.

    ```python
    from imf_reader import sdr

    sdr.fetch_allocations_holdings((2021, 4))   # April 2021: year, then month
    ```

    ```python
    from imf_reader import weo

    weo.fetch_data(("April", 2021))   # April 2021: month name, then year
    ```

    Passing one module's order to the other fails silently, away from the call site. Check
    which one you're calling.

## Exchange rates

```python
from imf_reader import sdr

df = sdr.fetch_exchange_rates()
```

`fetch_exchange_rates()` defaults to `unit_basis="SDR"`, which returns 1 SDR expressed in USD. Pass `"USD"` for 1 USD expressed in SDR:

```python
from imf_reader import sdr

df = sdr.fetch_exchange_rates("USD")
```

Both calls return the full historical series, up to the latest available date, in two columns: `date` and `exchange_rate`.

The SDR's value is the sum, in US dollars, of a basket of five currencies: the US dollar, euro, Japanese yen, pound sterling, and Chinese renminbi. The IMF calculates it daily except on IMF holidays, and reviews the basket every five years.

## Interest rates

```python
from imf_reader import sdr

df = sdr.fetch_interest_rates()
```

`fetch_interest_rates()` takes no arguments and returns the full historical series, with columns `interest_rate`, `effective_from`, and `effective_to`. The rate for the current week is released Sunday morning, Washington DC time.

## Clearing SDR data

```python
from imf_reader import cache

cache.clear_cache(scope="sdr")
```

`sdr.clear_cache()` still works. It emits a `DeprecationWarning` and is removed in 3.0. See [Caching](caching.md) for the rest of the cache API.

## Next steps

- [Caching](caching.md) - cache locations, TTLs, and the full `cache` API
- [World Economic Outlook](weo.md) - the package's other data source, with its own date-argument order
- [Why imf-reader](why-imf-reader.md) - why the package parses web pages instead of calling an API
