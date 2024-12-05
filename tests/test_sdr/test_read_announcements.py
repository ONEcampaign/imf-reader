import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
from bs4 import BeautifulSoup
from imf_reader.sdr import read_announcements


class TestReadAnnouncements(unittest.TestCase):
    """Tests functions in the read_announcements module."""

    @patch("pandas.read_csv")
    def test_read_tsv(self, mock_read_csv):
        """Ensure read_tsv processes well-formated tsv correctly and raises ValueError on malformed data."""
        # Mock successful TSV read
        mock_read_csv.return_value = pd.DataFrame({"A": [1], "B": [2]})
        result = read_announcements.read_tsv("mock_url")
        self.assertTrue(isinstance(result, pd.DataFrame))

        # Mock failure
        mock_read_csv.side_effect = pd.errors.ParserError
        with self.assertRaises(ValueError):
            read_announcements.read_tsv("mock_url")

    def test_clean_df_correct_format(self):
        """Test clean_df with the expected format."""
        # Mock input DataFrame
        raw_data = pd.DataFrame({0: ["", "", "", "Country A\t$100\t$200"]})
        expected_data = pd.DataFrame(
            {
                "entity": ["Country A", "Country A"],
                "indicator": ["holdings", "allocations"],
                "value": [100, 200],
            }
        )

        result = read_announcements.clean_df(raw_data)
        pd.testing.assert_frame_equal(result, expected_data)

    def test_clean_df_empty(self):
        """Test clean_df with an empty DataFrame"""
        input_df = pd.DataFrame()
        with self.assertRaises(IndexError):
            read_announcements.clean_df(input_df)

    def test_format_date(self):
        """Test format_date computes last day of a given month/year."""
        self.assertEqual(read_announcements.format_date(2, 2024), "2024-2-29")
        self.assertEqual(read_announcements.format_date(1, 2023), "2023-1-31")

    @patch("imf_reader.sdr.read_announcements.read_tsv")
    @patch("imf_reader.sdr.read_announcements.clean_df")
    def test_get_holdings_and_allocations_data(self, mock_clean_df, mock_read_tsv):
        """Test get_holdings_and_allocations_data caches data properly."""
        mock_read_tsv.return_value = pd.DataFrame()
        mock_clean_df.return_value = pd.DataFrame({"data": [1]})

        result = read_announcements.get_holdings_and_allocations_data(2024, 11)
        self.assertTrue("data" in result.columns)

    @patch("imf_reader.sdr.read_announcements.make_request")
    @patch("bs4.BeautifulSoup")
    def test_get_latest_date(self, mock_soup, mock_make_request):
        """Test correct extraction of get_latest_date."""
        # Simulate HTML content
        html_content = """
        <html>
            <body>
                <table></table><table></table><table></table><table></table>
                <table>
                    <tr><td>Header</td></tr>
                    <tr><td>November 30, 2024</td></tr>
                </table>
            </body>
        </html>
        """
        mock_make_request.return_value.content = html_content
        mock_soup.return_value = BeautifulSoup(html_content, "html.parser")

        # Call the function
        year, month = read_announcements.get_latest_date()

        # Assert expected output
        self.assertEqual((year, month), (2024, 11))

    @patch("imf_reader.sdr.read_announcements.get_latest_date")
    @patch("imf_reader.sdr.read_announcements.get_holdings_and_allocations_data")
    def test_fetch_allocations_holdings(self, mock_get_data, mock_get_latest_date):
        """Ensure fetch_allocations_holdings fetches data for the provided date or the latest date."""
        # Mock latest date and data fetch
        mock_get_latest_date.return_value = (2024, 11)
        mock_get_data.return_value = pd.DataFrame({"data": [1]})

        result = read_announcements.fetch_allocations_holdings()
        self.assertTrue("data" in result.columns)

        # Test with specific date
        result = read_announcements.fetch_allocations_holdings((2023, 10))
        mock_get_data.assert_called_with(2023, 10)


if __name__ == "__main__":
    unittest.main()
