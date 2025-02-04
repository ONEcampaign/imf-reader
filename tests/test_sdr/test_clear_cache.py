"""Tests for the clear cache function in the SDR module."""

from unittest.mock import patch
from imf_reader.sdr.clear_cache import clear_cache


@patch(
    "imf_reader.sdr.read_announcements.get_holdings_and_allocations_data.cache_clear"
)
@patch(
    "imf_reader.sdr.read_announcements.fetch_latest_allocations_holdings_date.cache_clear"
)
@patch("imf_reader.sdr.read_exchange_rate.fetch_exchange_rates.cache_clear")
@patch("imf_reader.sdr.read_interest_rate.fetch_interest_rates.cache_clear")
def test_clear_cache(
    mock_cache_clear1, mock_cache_clear2, mock_cache_clear3, mock_cache_clear4
):
    """Test for clear_cache method. Check that cache_clear is called for each function."""

    # Call the clear_cache function
    clear_cache()

    # Check that cache_clear was called for each function
    mock_cache_clear1.assert_called_once()
    mock_cache_clear2.assert_called_once()
    mock_cache_clear3.assert_called_once()
    mock_cache_clear4.assert_called_once()
