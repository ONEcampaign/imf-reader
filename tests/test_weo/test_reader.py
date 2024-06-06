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


@patch("imf_reader.weo.reader._fetch")
def test_fetch_data(mock_fetch):
    """Test for fetch_data method."""

    # Mock the _fetch function to return a specific DataFrame
    mock_data = pd.DataFrame({"column1": [1, 2, 3], "column2": [4, 5, 6]})
    mock_fetch.return_value = mock_data

    # Test that the function correctly fetches data when a version is passed
    pd.testing.assert_frame_equal(reader.fetch_data(("April", 2024)), mock_data)
    # check that validate_version is called
    mock_fetch.assert_called_once_with(("April", 2024))

    # when no version is passed, check that gen_latest_version is called
    reader.fetch_data()
    mock_fetch.assert_called_with(reader.gen_latest_version())


@patch("imf_reader.weo.reader._fetch.cache_clear")
def test_clear_cache(mock_cache_clear):
    """Test for clear_cache method."""

    # Call the clear_cache function
    reader.clear_cache()

    # Check that cache_clear was called
    mock_cache_clear.assert_called_once()


@patch("imf_reader.weo.reader._fetch")
@patch("imf_reader.weo.reader.roll_back_version")
@patch("imf_reader.weo.reader.gen_latest_version")
def test_fetch_data_handles_NoDataError(
    mock_gen_latest_version, mock_roll_back_version, mock_fetch
):
    """Test for fetch_data method when the version needs to be rolled back"""

    # Mock the gen_latest_version function to return a specific version
    mock_gen_latest_version.return_value = ("April", 2024)

    # Mock the _fetch function to raise a NoDataError for the first call and return a DataFrame for the second call
    mock_fetch.side_effect = [
        NoDataError,
        pd.DataFrame({"column1": [1, 2, 3], "column2": [4, 5, 6]}),
    ]

    # Mock the roll_back_version function to return a specific version
    mock_roll_back_version.return_value = ("October", 2023)

    # Call the fetch_data function without passing a version
    df = reader.fetch_data()

    # Check that gen_latest_version was called once
    mock_gen_latest_version.assert_called_once()

    # Check that _fetch was called twice (once for the initial call and once after the NoDataError)
    assert mock_fetch.call_count == 2

    # Check that roll_back_version was called once with the version returned by gen_latest_version
    mock_roll_back_version.assert_called_once_with(("April", 2024))

    # Check that the DataFrame returned by fetch_data is as expected
    pd.testing.assert_frame_equal(
        df, pd.DataFrame({"column1": [1, 2, 3], "column2": [4, 5, 6]})
    )
