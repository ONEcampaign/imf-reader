"""Special Drawing Rights (SDR) reader module.

This module offers access to the IMF's Special Drawing Rights (SDR) data.
The SDR is an international reserve asset created by the IMF in 1969.
It is not a currency, but the holder of SDRs can exchange them for usable currencies in times of need.

Read more about SDRs at: https://www.imf.org/en/About/Factsheets/Sheets/2023/special-drawing-rights-sdr


Usage:

Import the module

```python
from imf_reader import sdr
```

Read allocations and holdings data

```python
sdr.fetch_allocations_holdings()
```
SDRs holdings and allocations are published at a monthly frequency. The function fetches the latest data available by
default. Check the latest available date

```python
sdr.get_latest_date()
```

To retrieve SDR holdings and allocations for a specific month and year, eg April 2021, pass the year and month as a tuple

```python
sdr.fetch_allocations_holdings((2021, 4))
```

Read interest rates

```python
sdr.fetch_interest_rates()
```

Read exchange rates

```python
sdr.fetch_exchange_rates()
```
By default, the exchange rate is in USDs per 1 SDR. To get the exchange rate in SDRs per 1 USD, pass the unit basis as "USD"

```python
sdr.fetch_exchange_rates("USD")
```

Clear cached data

```python
sdr.clear_cache()
```

"""

from imf_reader.sdr.read_interest_rate import fetch_interest_rates
from imf_reader.sdr.read_exchange_rate import fetch_exchange_rates
from imf_reader.sdr.read_announcements import fetch_allocations_holdings, get_latest_date
from imf_reader.sdr.clear_cache import clear_cache
