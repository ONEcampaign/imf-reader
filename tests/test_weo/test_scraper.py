"""Tests for weo scraper module."""

import pytest
from unittest.mock import patch, Mock
from bs4 import BeautifulSoup
import io
from zipfile import ZipFile, BadZipFile

from imf_reader.weo import scraper
from imf_reader.config import NoDataError


TEST_URL = "https://test.com"


def test_get_soup():
    """Test get_soup"""

    # Mock the requests.get function
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"<html></html>"

        # Call the function with the mock object
        soup = scraper.get_soup("April", 2021)

        # Assert the result
        assert isinstance(soup, BeautifulSoup)
        assert str(soup) == "<html></html>"


class TestSDMXScraper:
    """Test SDMXScraper class."""

    def test_get_sdmx_url(self):
        """Test get_sdmx_url"""

        # set up mock
        mock_soup = Mock(spec=BeautifulSoup)
        mock_soup.find.return_value.get.return_value = "test/url"

        # test expected behavior
        result = scraper.SDMXScraper.get_sdmx_url(mock_soup)
        assert result == "test/url"

        # Test when href is None
        mock_soup.find.return_value.get.return_value = None
        with pytest.raises(NoDataError, match="SDMX data not found"):
            scraper.SDMXScraper.get_sdmx_url(mock_soup)

        # test AttributeError
        mock_soup.find.return_value.get.side_effect = AttributeError
        with pytest.raises(NoDataError, match="SDMX data not found"):
            scraper.SDMXScraper.get_sdmx_url(mock_soup)

    @patch("imf_reader.weo.scraper.make_request")
    def test_get_sdmx_folder(self, mock_request):
        """Test get_sdmx_folder"""

        # set up mock
        zip_content = io.BytesIO()
        with ZipFile(zip_content, "w") as zipf:
            zipf.writestr("test.txt", "test content")
        mock_request.return_value.content = zip_content.getvalue()

        # Test expected behavior
        folder = scraper.SDMXScraper.get_sdmx_folder(TEST_URL)
        assert isinstance(folder, ZipFile)  # The result is a ZipFile object
        assert folder.testzip() is None  # No exception is raised

        # Test BadZipFile
        bad_zip_content = io.BytesIO(b"this is not a valid zip file")
        mock_request.return_value.content = bad_zip_content.getvalue()
        with pytest.raises(BadZipFile):
            scraper.SDMXScraper.get_sdmx_folder(TEST_URL)

    @patch("imf_reader.weo.scraper.make_request")
    @patch.object(ZipFile, "testzip")
    def test_get_sdmx_folder_corrupt_zip(self, mock_testzip, mock_request):
        """Test get_sdmx_folder with a corrupt zip file"""

        # Create a valid zip file
        valid_zip_content = io.BytesIO()
        with ZipFile(valid_zip_content, "w") as zipf:
            zipf.writestr("test.txt", "This is some test content")

        # Set up the mock to return the valid zip file
        mock_request.return_value.content = valid_zip_content.getvalue()

        # Mock testzip to always return a non-None value
        mock_testzip.return_value = lambda: "test.txt"

        # Test that a BadZipFile exception is raised
        with pytest.raises(BadZipFile, match="Corrupt zip file"):
            scraper.SDMXScraper.get_sdmx_folder(TEST_URL)
