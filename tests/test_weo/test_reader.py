"""Tests for reader module"""

import pytest
from unittest.mock import patch
from datetime import datetime
import pandas as pd

from imf_reader.weo import reader
from imf_reader.config import NoDataError


def test_validate_version():
    """Test for validate_version function."""

    # Test that the function correctly validates a valid version
    assert reader.validate_version(("April", 2024)) == ("April", 2024)  # April
    assert reader.validate_version(("October", 2024)) == ("October", 2024)  # October

    # Test that the function correctly validates a valid version with different case and leading/trailing spaces
    assert reader.validate_version((" april ", "2024")) == ("April", 2024)
    assert reader.validate_version(("october", " 2024 ")) == ("October", 2024)
    assert reader.validate_version((" apRil ", "2024")) == ("April", 2024)

    # Test that the function raises a TypeError for an invalid month
    with pytest.raises(TypeError):
        reader.validate_version(("March", 2024))

    # Test that the function raises a TypeError for an invalid year
    with pytest.raises(TypeError, match="Invalid year. Must be an integer"):
        reader.validate_version(("April", "twenty twenty four"))

    # Test that the function raises a TypeError for an invalid version format
    with pytest.raises(TypeError):
        reader.validate_version("April 2024")


@patch("imf_reader.weo.reader.datetime")
def test_gen_latest_version(mock_datetime):
    """Test for gen_latest_version function."""

    # Mock the current date to be in April
    mock_datetime.now.return_value = datetime(2024, 4, 1)
    assert reader.gen_latest_version() == ("April", 2024)

    # Mock the current date to be in October
    mock_datetime.now.return_value = datetime(2024, 10, 1)
    assert reader.gen_latest_version() == ("October", 2024)

    # Mock the current date to be in January
    mock_datetime.now.return_value = datetime(2024, 1, 1)
    assert reader.gen_latest_version() == ("October", 2023)


def test_roll_back_version():
    """Test for roll_back_version function."""

    # Test that the function correctly rolls back from April to the previous October
    assert reader.roll_back_version(("April", 2024)) == ("October", 2023)

    # Test that the function correctly rolls back from October to April of the same year
    assert reader.roll_back_version(("October", 2024)) == ("April", 2024)

    # Test that the function raises a ValueError for an invalid month
    with pytest.raises(ValueError):
        reader.roll_back_version(("March", 2024))


@patch("imf_reader.weo.reader.get_weo_versions")
@patch("imf_reader.weo.reader.get_weo_data")
def test_fetch_data(mock_get_weo_data, mock_get_weo_versions):
    """Test for fetch_data method."""

    # Mock the get_weo_data function to return a specific DataFrame
    mock_data = pd.DataFrame({"column1": [1, 2, 3], "column2": [4, 5, 6]})
    mock_get_weo_data.return_value = mock_data
    mock_get_weo_versions.return_value = [("October", 2025), ("April", 2025)]

    # Test that the function correctly fetches data when a version is passed
    pd.testing.assert_frame_equal(reader.fetch_data(("April", 2024)), mock_data)
    mock_get_weo_data.assert_called_with(("April", 2024))

    # when no version is passed, check that get_weo_versions is called for latest
    mock_get_weo_data.reset_mock()
    reader.fetch_data()
    mock_get_weo_versions.assert_called()
    mock_get_weo_data.assert_called_with(("October", 2025))


@patch("imf_reader.weo.reader.get_weo_versions")
@patch("imf_reader.weo.reader.get_weo_data")
def test_fetch_data_attribute(mock_get_weo_data, mock_get_weo_versions):
    """Test for fetch_data method attribute."""

    mock_data = pd.DataFrame({"column1": [1, 2, 3], "column2": [4, 5, 6]})
    mock_get_weo_data.return_value = mock_data
    mock_get_weo_versions.return_value = [("April", 2024), ("October", 2023)]

    # when a version is passed, check that the attribute is set
    reader.fetch_data(("April", 2022))
    assert reader.fetch_data.last_version_fetched == ("April", 2022)

    # when no version is passed, check that the attribute is set to latest
    reader.fetch_data()
    assert reader.fetch_data.last_version_fetched == ("April", 2024)


@patch("imf_reader.weo.reader._fetch.cache_clear")
def test_clear_cache(mock_cache_clear):
    """Test for clear_cache method."""

    # Call the clear_cache function
    reader.clear_cache()

    # Check that cache_clear was called
    mock_cache_clear.assert_called_once()


@patch("imf_reader.weo.reader._fetch")
@patch("imf_reader.weo.reader.roll_back_version")
@patch("imf_reader.weo.reader.get_weo_versions")
@patch("imf_reader.weo.reader.get_weo_data")
def test_fetch_data_handles_NoDataError(
    mock_get_weo_data, mock_get_weo_versions, mock_roll_back_version, mock_fetch
):
    """Test for fetch_data method when the API fails and falls back to scraper with rollback"""

    # Mock get_weo_versions to return a specific version list
    mock_get_weo_versions.return_value = [("April", 2024), ("October", 2023)]

    # Mock get_weo_data to raise ValueError (version not in API)
    mock_get_weo_data.side_effect = ValueError("Version not available")

    # Mock the _fetch function to raise a NoDataError for the first call and return a DataFrame for the second call
    mock_fetch.side_effect = [
        NoDataError,
        pd.DataFrame({"column1": [1, 2, 3], "column2": [4, 5, 6]}),
    ]

    # Mock the roll_back_version function to return a specific version
    mock_roll_back_version.return_value = ("October", 2023)

    # Call the fetch_data function without passing a version
    df = reader.fetch_data()

    # Check that get_weo_versions was called to get latest version
    mock_get_weo_versions.assert_called()

    # Check that _fetch was called twice (once for the initial call and once after the NoDataError)
    assert mock_fetch.call_count == 2

    # Check that roll_back_version was called once with the latest version
    mock_roll_back_version.assert_called_once_with(("April", 2024))

    # Check that the DataFrame returned by fetch_data is as expected
    pd.testing.assert_frame_equal(
        df, pd.DataFrame({"column1": [1, 2, 3], "column2": [4, 5, 6]})
    )
