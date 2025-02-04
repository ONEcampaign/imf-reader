from unittest.mock import patch, Mock
import pytest
import pandas as pd
import re
from imf_reader import sdr
from imf_reader.sdr.read_announcements import (
    read_tsv,
    clean_df,
    format_date,
    get_holdings_and_allocations_data,
    get_latest_allocations_holdings_date,
    fetch_allocations_holdings,
    BASE_URL,
    MAIN_PAGE_URL,
)


@pytest.fixture
def input_df():
    df = pd.DataFrame(
        {
            "SDR Allocations and Holdings": [
                "for all members as of June 30, 2020",
                "(in SDRs)",
                "Members\tSDR Holdings\tSDR Allocations",
                "Spain\t123\t456",
                "Total\t321\t654",
            ]
        }
    )
    return df


class TestReadAnnouncements:
    """Tests functions in the read_announcements module."""

    @pytest.fixture(autouse=True)
    def auto_clear_cache(self):
        """Clear cache before each test."""
        sdr.clear_cache()

    @patch("pandas.read_csv")
    def test_read_tsv_success(self, mock_read_csv):
        """Test read_tsv successfully processes a well-formatted TSV."""
        mock_read_csv.return_value = pd.DataFrame({"A": [1], "B": [2]})
        result = read_tsv("mock_url")
        assert isinstance(result, pd.DataFrame)
        assert result.equals(pd.DataFrame({"A": [1], "B": [2]}))

    @patch("pandas.read_csv")
    def test_read_tsv_failure(self, mock_read_csv):
        """Test read_tsv raises ValueError on malformed data."""
        mock_read_csv.side_effect = pd.errors.ParserError
        with pytest.raises(ValueError, match="SDR data not available for this date"):
            read_tsv("mock_url")

    def test_clean_df_correct_format(self, input_df):
        """Test clean_df with the expected format."""
        # Mock input DataFrame

        expected_df = pd.DataFrame(
            {
                "entity": ["Spain", "Total", "Spain", "Total"],
                "indicator": ["holdings", "holdings", "allocations", "allocations"],
                "value": [123, 321, 456, 654],
            }
        )

        result = clean_df(input_df)
        pd.testing.assert_frame_equal(result, expected_df)

    @pytest.mark.parametrize(
        "month, year, expected",
        [
            (1, 2024, "2024-1-31"),  # January 2024
            (2, 2024, "2024-2-29"),  # February (Leap year)
            (2, 2023, "2023-2-28"),  # February (Non-leap year)
            (4, 2024, "2024-4-30"),  # April
            (12, 2023, "2023-12-31"),  # December
        ],
    )
    def test_format_date_valid(self, month, year, expected):
        """Test format_date returns the correct last day of the month."""
        assert format_date(month, year) == expected

    def test_format_date_invalid_month(self):
        """Test format_date raises ValueError for invalid month input."""
        with pytest.raises(ValueError):
            format_date(0, 2024)  # Invalid month (0)

        with pytest.raises(ValueError):
            format_date(13, 2024)  # Invalid month (13)

    @patch("imf_reader.sdr.read_announcements.read_tsv")
    @patch("imf_reader.sdr.read_announcements.clean_df")
    def test_get_holdings_and_allocations_data_success(
        self, mock_clean_df, mock_read_tsv, input_df
    ):
        """Test get_holdings_and_allocations_data successfully returns processed data."""
        # Mock the read_tsv output
        mock_read_tsv.return_value = input_df
        # Mock the clean_df output
        mock_clean_df.return_value = clean_df(input_df)

        # Expected final output
        expected_df = pd.DataFrame(
            {
                "entity": ["Spain", "Total", "Spain", "Total"],
                "indicator": ["holdings", "holdings", "allocations", "allocations"],
                "value": [123, 321, 456, 654],
                "date": [pd.to_datetime("2024-02-29")] * 4,
            }
        )

        # Call the function
        result = get_holdings_and_allocations_data(2024, 2)

        # Assertions
        mock_read_tsv.assert_called_once_with(
            f"{BASE_URL}extsdr2.aspx?date1key=2024-2-29&tsvflag=Y"
        )
        mock_clean_df.assert_called_once()
        pd.testing.assert_frame_equal(result, expected_df)

    @patch(
        "imf_reader.sdr.read_announcements.read_tsv",
        side_effect=ValueError("Data not available"),
    )
    def test_get_holdings_and_allocations_data_failure(self, mock_read_tsv):
        """Test get_holdings_and_allocations_data raises ValueError when read_tsv fails."""
        with pytest.raises(ValueError, match="Data not available"):
            get_holdings_and_allocations_data(1800, 1)

    @patch("imf_reader.sdr.read_announcements.make_request")
    def test_get_latest_date_success(self, mock_make_request):
        """Test get_latest_allocations_holdings_date successfully returns the latest date."""

        # Mock HTML content
        mock_html_content = """
        <html>
            <body>
                <table>
                    <tr></tr> <!-- Index 0 -->
                    <tr><td>November 30, 2023</td></tr> <!-- Index 1: Latest date -->
                </table>
                <table></table>
                <table></table>
                <table></table>
                <table>
                    <tr></tr>
                    <tr><td>November 30, 2023</td></tr>
                </table>
            </body>
        </html>
        """

        # Mock the make_request response
        mock_response = Mock()
        mock_response.content = mock_html_content
        mock_make_request.return_value = mock_response

        # Call the function
        result = get_latest_allocations_holdings_date()

        # Assertions
        mock_make_request.assert_called_once_with(MAIN_PAGE_URL)
        assert result == (2023, 11)  # Expected year and month

    @patch("imf_reader.sdr.read_announcements.make_request")
    def test_get_latest_date_invalid_html(self, mock_make_request):
        """Test get_latest_allocations_holdings_date raises an error when HTML parsing fails."""

        # Mock malformed HTML content
        mock_response = Mock()
        mock_response.content = "<html><body></body></html>"  # Missing tables
        mock_make_request.return_value = mock_response

        # Call the function and expect an IndexError
        with pytest.raises(IndexError):
            get_latest_allocations_holdings_date()

    @patch("imf_reader.sdr.read_announcements.get_latest_allocations_holdings_date")
    @patch("imf_reader.sdr.read_announcements.clean_df")
    @patch("imf_reader.sdr.read_announcements.read_tsv")
    @patch("imf_reader.sdr.read_announcements.get_holdings_and_allocations_data")
    def test_fetch_allocations_holdings_default_date(
        self,
        mock_get_holdings_and_allocations_data,
        mock_read_tsv,
        mock_clean_df,
        mock_get_latest_date,
        input_df,
    ):
        """Test fetch_allocations_holdings when no date is provided."""
        # Mock get_latest_allocations_holdings_date to return a specific date
        mock_get_latest_date.return_value = (2024, 2)

        # Mock read_tsv
        mock_read_tsv.return_value = input_df

        # Mock clean_df to return a cleaned DataFrame
        cleaned_df = pd.DataFrame(
            {
                "entity": ["Spain", "Total", "Spain", "Total"],
                "indicator": ["holdings", "holdings", "allocations", "allocations"],
                "value": [123, 321, 456, 654],
                "date": [pd.to_datetime("2024-02-29")] * 4,
            }
        )
        mock_clean_df.return_value = cleaned_df

        # Mock get_holdings_and_allocations_data to return the final DataFrame
        mock_get_holdings_and_allocations_data.return_value = cleaned_df

        # Call the function
        result = fetch_allocations_holdings()

        # Assertions
        mock_get_latest_date.assert_called_once()  # Ensure get_latest_allocations_holdings_date was called
        mock_get_holdings_and_allocations_data.assert_called_once_with(
            2024, 2
        )  # Ensure the correct call
        pd.testing.assert_frame_equal(
            result, cleaned_df
        )  # Ensure the result matches the cleaned data


@patch("imf_reader.sdr.read_announcements.get_holdings_and_allocations_data")
@patch(
    "imf_reader.sdr.read_announcements.get_latest_allocations_holdings_date",
    return_value=(2024, 1),
)
def test_fetch_allocations_holdings_future_date(
    mock_get_latest_date, mock_get_holdings_and_allocations_data
):
    """Test fetch_allocations_holdings when unavailable future date is provided."""
    with pytest.raises(
        ValueError,
        match=re.escape(
            "SDR data unavailable for: (2025, 1).\nLatest available: (2024, 1)"
        ),
    ):
        fetch_allocations_holdings((2025, 1))
