from imf_reader.sdr.read_announcements import (
    get_holdings_and_allocations_data,
    get_latest_date,
)
from imf_reader.sdr.read_exchange_rate import fetch_exchange_rates
from imf_reader.sdr.read_interest_rate import fetch_interest_rates
from imf_reader.config import logger


def clear_cache():
    """Clear the cache for all lru_cache-decorated functions."""

    cleared_caches = 0

    # read_announcements
    if (
        get_holdings_and_allocations_data.cache_info().currsize > 0
        or get_latest_date.cache_info().currsize > 0
    ):
        get_holdings_and_allocations_data.cache_clear()
        get_latest_date.cache_clear()
        cleared_caches += 1
        logger.info("Cache cleared - Holdings and allocations")

    # read_exchange_rate
    if fetch_exchange_rates.cache_info().currsize > 0:
        fetch_exchange_rates.cache_clear()
        cleared_caches += 1
        logger.info("Cache cleared - Exchange rates")

    # read_interest_rate
    if fetch_interest_rates.cache_info().currsize > 0:
        fetch_interest_rates.cache_clear()
        cleared_caches += 1
        logger.info("Cache cleared - Interest rates")

    if cleared_caches == 0:

        logger.info("Unable to clear cache - No cached data")
