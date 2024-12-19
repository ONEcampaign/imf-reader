from unittest.mock import patch, MagicMock, ANY
import pytest
import requests
import pandas as pd
from imf_reader import sdr
from imf_reader.sdr.read_exchange_rate import (
    preprocess_data,
    fetch_exchange_rates,
    get_exchange_rates_data,
    extract_exchange_series,
    extract_dates_series,
    parse_data,
    BASE_URL,
)


@pytest.fixture
def input_df():
    df = pd.DataFrame(
        {
            "SDR Valuations": [
                "Report date\tCurrency Unit\tCurrency amount\tExchange Rate",
                "2023-11-30\tEuro\t0.456\t-1.234",
                "U.S.$1.00 = SDR\t0.123",
                "SDR1 = US$\t0.321",
            ]
        }
    )
    return df


class TestExchangeRateModule:

    @pytest.fixture(autouse=True)
    def auto_clear_cache(self):
        """Clear cache before each test."""
        sdr.clear_cache()

    @patch("requests.post")
    def test_get_exchange_rates_data_success(self, mock_post):
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
        result = get_exchange_rates_data()

        # Assertions
        pd.testing.assert_frame_equal(result, expected_df)
        mock_post.assert_called_once_with(BASE_URL, data={"__EVENTTARGET": "lbnTSV"})

    def test_get_exchange_rates_data_connection_error(self):
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
                get_exchange_rates_data()

            # Verify the mock was called with the expected arguments
            mock_post.assert_called_once_with(
                BASE_URL, data={"__EVENTTARGET": "lbnTSV"}
            )

    def test_get_exchange_rates_data_parse_error(self):
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
                get_exchange_rates_data()

            # Assertions
            mock_post.assert_called_once_with(
                BASE_URL, data={"__EVENTTARGET": "lbnTSV"}
            )
            mock_read_csv.assert_called_once_with(ANY, delimiter="/t", engine="python")

    def test_preprocess_data_success(self, input_df):
        """Test preprocessing of the DataFrame"""

        expected_df = pd.DataFrame(
            {
                "Report date": ["2023-11-30", "U.S.$1.00 = SDR", "SDR1 = US$"],
                "Currency Unit": ["Euro", "0.123", "0.321"],
                "Currency amount": ["0.456", None, None],
                "Exchange Rate": ["-1.234", None, None],
            }
        )
        expected_df.columns.name = 0
        result = preprocess_data(input_df)

        # Assertion
        pd.testing.assert_frame_equal(result, expected_df)

    def test_preprocess_data_missing_column(self):
        """Test that KeyError is raised when 'Report date' column is missing."""
        # Create the input DataFrame
        input_df = pd.DataFrame(
            [
                "Other Column\tCurrency Unit\tCurrency amount\tExchange Rate",
                "2023-11-30\tEuro\t0.456\t-1.234",
                "U.S.$1.00 = SDR\t0.123",
                "SDR1 = US$\t0.321",
            ]
        )

        # Assert that KeyError is raised with the correct message
        with pytest.raises(KeyError, match="Missing required column: Report date"):
            preprocess_data(input_df)

    @pytest.mark.parametrize(
        "currency_code, expected_xrate",
        [
            ("U.S.$1.00 = SDR", "0.123"),
            ("SDR1 = US$", "0.321"),
        ],
    )
    def test_extract_exchange_series(self, input_df, currency_code, expected_xrate):
        """Test extracting the exchange series for a specific column value"""
        input_df = preprocess_data(input_df)
        result = extract_exchange_series(input_df, currency_code)
        expected_series = pd.Series([expected_xrate], name="Currency Unit")

        # Assertion
        pd.testing.assert_series_equal(result, expected_series)

    def test_extract_dates_series(self, input_df):
        """Test extracting unique dates from the DataFrame"""
        preprocessed_df = preprocess_data(input_df)
        result = extract_dates_series(preprocessed_df)
        expected_series = pd.Series(["2023-11-30"], name="Report date")

        # Assertion
        pd.testing.assert_series_equal(result, expected_series)

    @pytest.mark.parametrize(
        "currency_code, expected_xrate",
        [
            ("USD", 0.123),
            ("SDR", 0.321),
        ],
    )
    def test_parse_data_valid_input(self, input_df, currency_code, expected_xrate):
        """Test parsing valid input DataFrame with mocked helpers"""

        expected_df = pd.DataFrame(
            {"date": pd.to_datetime(["2023-11-30"]), "exchange_rate": [expected_xrate]},
        )
        result = parse_data(input_df, currency_code)

        # Assertions
        pd.testing.assert_frame_equal(result, expected_df)
        assert result.date.dtype == "datetime64[ns]"
        assert result.exchange_rate.dtype == "float64"

    def test_parse_data_invalid_unit_basis(self, input_df):
        """Test parse_data raises error on invalid unit_basis."""
        # Assert that ValueError is raised when passing an invalid unit_basis
        with pytest.raises(
            ValueError, match="unit_basis must be either 'SDR' or 'USD'"
        ):
            parse_data(input_df, "INVALID")

    @patch("imf_reader.sdr.read_exchange_rate.get_exchange_rates_data")
    @patch("imf_reader.sdr.read_exchange_rate.parse_data")
    def test_fetch_exchange_rates(self, mock_parse_data, mock_get_data, input_df):
        """Test fetching exchange rates"""
        # Mock return values for the patched functions
        mock_get_data.return_value = input_df
        mock_parse_data.return_value = pd.DataFrame(
            {"date": pd.to_datetime(["2023-11-30"]), "exchange_rate": [0.123]}
        )
        expected_df = pd.DataFrame(
            {"date": pd.to_datetime(["2023-11-30"]), "exchange_rate": [0.123]}
        )

        # Mock the logger
        with patch("imf_reader.sdr.read_exchange_rate.logger.info") as mock_logger:
            result = fetch_exchange_rates("USD")

            # Assertions
            mock_get_data.assert_called_once()
            mock_parse_data.assert_called_once_with(mock_get_data.return_value, "USD")
            pd.testing.assert_frame_equal(result, expected_df)
            mock_logger.assert_called_once_with("Fetching exchange rate data")
