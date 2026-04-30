"""Tests for weo scraper module."""

import io
from unittest.mock import Mock, patch
from zipfile import BadZipFile, ZipFile

import pytest
from bs4 import BeautifulSoup

from imf_reader.cache.config import reset_cache_dir, set_cache_dir
from imf_reader.config import BulkPayloadCorruptError, NoDataError
from imf_reader.weo import scraper

TEST_URL = "https://test.com"


def _make_zip_bytes(filename: str = "data.txt", content: str = "hello") -> bytes:
    """Return raw bytes of a valid in-memory zip."""
    buf = io.BytesIO()
    with ZipFile(buf, "w") as zf:
        zf.writestr(filename, content)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path):
    """Redirect the cache to a temp directory and reset the scraper's lazy singleton."""
    set_cache_dir(tmp_path)
    # Reset the module-level lazy singleton so each test gets a fresh CacheManager
    # pointed at the new tmp root.
    scraper._zip_cache = None
    yield tmp_path
    reset_cache_dir()
    scraper._zip_cache = None


def test_get_soup(cache_disabled):
    """Test get_soup — cache must be disabled so the requests.get patch is intercepted."""

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


class TestSDMXScraperCacheIntegration:
    """Integration tests for SDMXScraper.scrape with the CacheManager layer."""

    @patch("imf_reader.weo.scraper.make_request")
    def test_scrape_cache_hit_skips_http(self, mock_request):
        """Second scrape() call must not hit the network when a valid cache entry exists."""
        zip_bytes = _make_zip_bytes("sdmx.xml", "<data/>")

        # make_request is called twice on the first call:
        # once for get_soup (the HTML page) and once for the SDMX zip URL.
        # We set up return values for both.
        html_response = Mock()
        html_response.content = (
            b'<html><body><a href="/sdmx_url">SDMX Data</a></body></html>'
        )
        zip_response = Mock()
        zip_response.content = zip_bytes
        mock_request.side_effect = [html_response, zip_response]

        # First call — cache miss, downloads content.
        result1 = scraper.SDMXScraper.scrape("April", 2024)
        assert isinstance(result1, ZipFile)
        assert mock_request.call_count == 2

        # Reset call count; second call should be a cache hit — zero HTTP calls.
        mock_request.reset_mock()
        mock_request.side_effect = None  # would raise if called unexpectedly

        result2 = scraper.SDMXScraper.scrape("April", 2024)
        assert isinstance(result2, ZipFile)
        mock_request.assert_not_called()

    @patch("imf_reader.weo.scraper.make_request")
    def test_scrape_corrupt_zip_raises_BulkPayloadCorruptError(self, mock_request):
        """make_request returning non-zip bytes must raise BulkPayloadCorruptError."""
        html_response = Mock()
        html_response.content = (
            b'<html><body><a href="/sdmx_url">SDMX Data</a></body></html>'
        )
        bad_response = Mock()
        bad_response.content = b"this is definitely not a zip file"
        mock_request.side_effect = [html_response, bad_response]

        with pytest.raises(BulkPayloadCorruptError):
            scraper.SDMXScraper.scrape("October", 2023)

        # Cache entry must be gone so the next call can retry cleanly.
        from imf_reader.cache.config import get_active_root

        sublayer = get_active_root() / "weo_sdmx"
        assert not (sublayer / "weo_october_2023.zip").exists()
