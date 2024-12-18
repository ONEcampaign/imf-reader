from imf_reader.sdr.read_announcements import (
    get_holdings_and_allocations_data,
    get_latest_date,
)
from imf_reader.sdr.read_exchange_rate import fetch_exchange_rates
from imf_reader.sdr.read_interest_rate import fetch_interest_rates
from imf_reader.config import logger


def clear_cache():
    """Clear the cache for all lru_cache-decorated functions in the 3 sdr modules."""

    # clear cache from read_announcements module
    get_holdings_and_allocations_data.cache_clear()
    get_latest_date.cache_clear()

    # clear cache from read_exchange_rate module
    fetch_exchange_rates.cache_clear()

    # clear cache from read_interest_rate module
    fetch_interest_rates.cache_clear()

    logger.info("Cache cleared")
