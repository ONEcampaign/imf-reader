import pytest
import pandas as pd
import requests
from unittest.mock import patch, MagicMock, ANY
from io import BytesIO
from imf_reader.sdr.read_interest_rate import (
    BASE_URL,
    get_interest_rates_data,
    preprocess_data,
    _filter_data,
    _format_data,
    clean_data,
    fetch_interest_rates,
)


@pytest.fixture
def input_df():
    df = pd.DataFrame(
        {
            "SDR Interest Rate Calculation": [
                "Effective from\tEffective to\tCurrency Unit\tCurrency amount\tExchange rate",
                "01/12/2024\t05/12/2024\tN/A\tN/A",
                "SDR Interest Rate\t1.50",
                "06/12/2024\t08/12/2024\tN/A\tN/A",
                "Total\t2.75",
                "09/12/2024\t12/12/2024\tN/A\tN/A",
                "Floor for SDR Interest Rate\t3.50",
                "empty row",
            ]
        }
    )
    return df


class TestReadInterestRate:

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear cache before each test."""
        fetch_interest_rates.cache_clear()

    @patch("requests.post")
    def test_get_interest_rates_data(self, mock_post):
        """Test successful data retrieval and parsing"""
        # Mock the response content with a valid TSV format
        mock_response = MagicMock()
        mock_response.content = (
            b"Column1\tColumn2\n2023-11-30\t1.234\n2023-12-01\t0.789\n"
        )
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        expected_df = pd.DataFrame(
            {"Column1\tColumn2": ["2023-11-30\t1.234", "2023-12-01\t0.789"]}
        )
        result = get_interest_rates_data()

        # Assertions
        pd.testing.assert_frame_equal(result, expected_df)
        mock_post.assert_called_once_with(BASE_URL, data={"__EVENTTARGET": "lbnTSV"})

    def test_get_interest_rates_data_connection_error(self):
        """Test ConnectionError is raised when requests.post fails."""
        with patch("requests.post") as mock_post:
            # Simulate raising a requests.exceptions.RequestException
            mock_post.side_effect = requests.exceptions.RequestException(
                "Network error"
            )

            # Verify the exception
            with pytest.raises(
                ConnectionError,
                match=f"Could not connect to {BASE_URL}",
            ):
                get_interest_rates_data()

            # Verify the mock was called with the expected arguments
            mock_post.assert_called_once_with(
                BASE_URL, data={"__EVENTTARGET": "lbnTSV"}
            )

    def test_get_interest_rates_data_parse_error(self):
        """Test ValueError is raised when parsing fails."""
        with patch("requests.post") as mock_post, patch(
            "pandas.read_csv"
        ) as mock_read_csv:
            # Mock the response content with invalid data
            mock_response = MagicMock()
            mock_response.content = b"invalid data"
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            # Simulate pd.read_csv raising a ParserError
            mock_read_csv.side_effect = pd.errors.ParserError("Parsing error")

            # Use pytest.raises to assert the ValueError
            with pytest.raises(ValueError, match="Could not parse data"):
                get_interest_rates_data()

            # Assertions
            mock_post.assert_called_once_with(
                BASE_URL, data={"__EVENTTARGET": "lbnTSV"}
            )
            mock_read_csv.assert_called_once_with(ANY, delimiter="/t", engine="python")

    def test_preprocess_data_success(self, input_df):
        """Test preprocess_data function with valid input."""
        expected_df = pd.DataFrame(
            {
                "effective_from": [
                    "01/12/2024",
                    "SDR Interest Rate",
                    "06/12/2024",
                    "Total",
                    "09/12/2024",
                    "Floor for SDR Interest Rate",
                ],
                "effective_to": [
                    "05/12/2024",
                    "1.50",
                    "08/12/2024",
                    "2.75",
                    "12/12/2024",
                    "3.50",
                ],
            }
        )
        expected_df.columns.name = 0
        result = preprocess_data(input_df).reset_index(drop=True)

        # Validate the structure and content of the DataFrame
        pd.testing.assert_frame_equal(result, expected_df)

    def test_preprocess_data_missing_column(self):
        """Test preprocess_data function raises KeyError when required columns are missing."""
        invalid_df = pd.DataFrame(
            {
                "SDR Interest Rate Calculation": [
                    "Some column\tAnother column",
                    "01/12/2024\tN/A",
                ]
            }
        )

        with pytest.raises(KeyError, match="Missing required column: Effective from"):
            preprocess_data(invalid_df)

    def test_filter_data_valid(self, input_df):
        """Test _filter_data with a valid DataFrame."""

        input_df = preprocess_data(input_df)
        result = _filter_data(input_df)

        # Expected Output DataFrame
        expected_df = pd.DataFrame(
            {
                "effective_from": ["01/12/2024", "SDR Interest Rate", "06/12/2024", "09/12/2024"],
                "effective_to": ["05/12/2024", "1.50", "08/12/2024", "12/12/2024"],
            }
        )
        expected_df.columns.name = 0

        # Validate the results
        pd.testing.assert_frame_equal(result, expected_df)


    def test_format_data_valid(self, input_df):
        """Test _format_data with valid input."""
        expected_df = pd.DataFrame({
            "interest_rate": ["1.50"],
            "effective_from": ["01/12/2024"],
            "effective_to": ["05/12/2024"]
        })

        result = (preprocess_data(input_df)
                  .pipe(_filter_data)
                  .pipe(_format_data)
                  .reset_index(drop=True))

        # Validate the structure and content of the DataFrame
        pd.testing.assert_frame_equal(result, expected_df)



    def test_clean_data_valid(self, input_df):
        """Test clean_data with valid input DataFrame."""
        expected_df = pd.DataFrame(
            {
                "interest_rate": [1.50],
                "effective_from": [
                    pd.Timestamp("01/12/2024"),
                ],
                "effective_to": [
                    pd.Timestamp("05/12/2024"),
                ],
            }
        )

        result = clean_data(input_df).reset_index(drop=True)

        # Validate the structure and content of the resulting DataFrame
        pd.testing.assert_frame_equal(result, expected_df)

    @patch("imf_reader.sdr.read_interest_rate.get_interest_rates_data")
    @patch("imf_reader.sdr.read_interest_rate.clean_data")
    def test_fetch_exchange_rates(self, mock_clean_data, mock_get_data, input_df):
        """Test fetching exchange rates"""
        # Mock return values for the patched functions
        mock_get_data.return_value = input_df
        mock_get_data.return_value = input_df
        mock_clean_data.return_value = pd.DataFrame(
            {
                "interest_rate": [1.50],
                "effective_from": [
                    pd.Timestamp("01/12/2024"),
                ],
                "effective_to": [
                    pd.Timestamp("05/12/2024"),
                ],
            }
        )

        expected_df = pd.DataFrame(
            {
                "interest_rate": [1.50],
                "effective_from": [
                    pd.Timestamp("01/12/2024"),
                ],
                "effective_to": [
                    pd.Timestamp("05/12/2024"),
                ],
            }
        )

        # Mock the logger
        with patch("imf_reader.sdr.read_interest_rate.logger.info") as mock_logger:
            result = fetch_interest_rates()

            # Assertions
            mock_get_data.assert_called_once()
            mock_clean_data.assert_called_once_with(mock_get_data.return_value)
            pd.testing.assert_frame_equal(result, expected_df)
            mock_logger.assert_called_once_with("Fetching SDR interest rates")
