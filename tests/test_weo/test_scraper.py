"""Tests for weo scraper module."""

import io
from unittest.mock import Mock, patch
from zipfile import BadZipFile, ZipFile

import pytest
import requests
from bs4 import BeautifulSoup
from readerkit import RedirectPolicyError

import imf_reader.cache.config as cfg
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
    """Redirect the cache to a temp directory and reset the memoised readerkit objects."""
    set_cache_dir(tmp_path)
    cfg.reset_objects()
    yield tmp_path
    reset_cache_dir()
    cfg.reset_objects()


def test_get_soup(cache_disabled):
    """Test get_soup with a mocked make_request response."""

    with patch("imf_reader.weo.scraper.make_request") as mock_get:
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


def _fake_bulk_fetcher_writing(payload: bytes):
    """Build a bulk_fetcher stand-in that writes ``payload`` to the FetchContext path.

    Mirrors bulk_fetcher's own signature (url, *, session=...) -> Fetcher, so it can
    replace the real thing wherever scrape() calls it.
    """

    def _bulk_fetcher(url, *, session):
        def _write(ctx):
            ctx.path.write_bytes(payload)

        return _write

    return _bulk_fetcher


class TestSDMXScraperCacheIntegration:
    """Integration tests for SDMXScraper.scrape with the artifact-cache layer."""

    @patch("imf_reader.weo.scraper.bulk_fetcher")
    @patch("imf_reader.weo.scraper.make_request")
    def test_scrape_cache_hit_skips_http(self, mock_request, mock_bulk_fetcher):
        """Second scrape() call must not hit the network when a valid cache entry exists."""
        zip_bytes = _make_zip_bytes("sdmx.xml", "<data/>")

        html_response = Mock()
        html_response.content = (
            b'<html><body><a href="/sdmx_url">SDMX Data</a></body></html>'
        )
        mock_request.return_value = html_response
        mock_bulk_fetcher.side_effect = _fake_bulk_fetcher_writing(zip_bytes)

        # The first call misses the cache, scraping the page and downloading content.
        result1 = scraper.SDMXScraper.scrape("April", 2024)
        assert isinstance(result1, ZipFile)
        assert mock_request.call_count == 1
        assert mock_bulk_fetcher.call_count == 1

        # Reset call counts. The second call should be a cache hit, so the fetcher
        # (and therefore the page scrape it wraps) must not run at all.
        mock_request.reset_mock()
        mock_bulk_fetcher.reset_mock()

        result2 = scraper.SDMXScraper.scrape("April", 2024)
        assert isinstance(result2, ZipFile)
        mock_request.assert_not_called()
        mock_bulk_fetcher.assert_not_called()

    @patch("imf_reader.weo.scraper.bulk_fetcher")
    @patch("imf_reader.weo.scraper.make_request")
    def test_scrape_corrupt_zip_raises_BulkPayloadCorruptError(
        self, mock_request, mock_bulk_fetcher
    ):
        """A non-zip payload must raise BulkPayloadCorruptError and leave no cache entry."""
        html_response = Mock()
        html_response.content = (
            b'<html><body><a href="/sdmx_url">SDMX Data</a></body></html>'
        )
        mock_request.return_value = html_response
        mock_bulk_fetcher.side_effect = _fake_bulk_fetcher_writing(
            b"this is definitely not a zip file"
        )

        with pytest.raises(BulkPayloadCorruptError):
            scraper.SDMXScraper.scrape("October", 2023)

        # The rejected payload and its half-written temp file must both be gone from disk,
        # so the next call re-downloads instead of tripping over the leftovers.
        bulk_dir = cfg.get_bulk_cache_dir()
        leftovers = (
            [p.name for p in bulk_dir.iterdir() if p.is_file()]
            if bulk_dir.exists()
            else []
        )
        assert leftovers == [], f"corrupt payload left behind: {leftovers}"

    @patch("imf_reader.weo.scraper.bulk_fetcher")
    @patch("imf_reader.weo.scraper.make_request")
    def test_scrape_transport_failure_raises_connection_error(
        self, mock_request, mock_bulk_fetcher
    ):
        """A readerkit transport failure during the download reaches the caller as
        ConnectionError, like every other network failure in the package."""
        html_response = Mock()
        html_response.content = (
            b'<html><body><a href="/sdmx_url">SDMX Data</a></body></html>'
        )
        mock_request.return_value = html_response

        def _bulk_fetcher(url, *, session):
            def _fail(ctx):
                raise RedirectPolicyError(
                    "redirect hop rejected",
                    url=url,
                    target="http://elsewhere.example",
                    policy="any",
                )

            return _fail

        mock_bulk_fetcher.side_effect = _bulk_fetcher

        with pytest.raises(
            ConnectionError, match="Could not download the WEO SDMX data"
        ):
            scraper.SDMXScraper.scrape("April", 2024)

    @patch("imf_reader.weo.scraper.bulk_fetcher")
    @patch("imf_reader.weo.scraper.make_request")
    def test_scrape_requests_connection_error_raises_connection_error(
        self, mock_request, mock_bulk_fetcher
    ):
        """A requests.ConnectionError exhausted by the fetcher's own retries reaches
        the caller as builtin ConnectionError, like every other network failure in
        the package."""
        html_response = Mock()
        html_response.content = (
            b'<html><body><a href="/sdmx_url">SDMX Data</a></body></html>'
        )
        mock_request.return_value = html_response

        def _bulk_fetcher(url, *, session):
            def _fail(ctx):
                raise requests.ConnectionError("connection refused")

            return _fail

        mock_bulk_fetcher.side_effect = _bulk_fetcher

        with pytest.raises(
            ConnectionError, match="Could not download the WEO SDMX data"
        ):
            scraper.SDMXScraper.scrape("April", 2024)

    @patch("imf_reader.weo.scraper.bulk_fetcher")
    @patch("imf_reader.weo.scraper.make_request")
    def test_scrape_http_error_raises_connection_error(
        self, mock_request, mock_bulk_fetcher
    ):
        """An HTTPError from raise_for_status() (not retried by the fetcher) reaches
        the caller as builtin ConnectionError."""
        html_response = Mock()
        html_response.content = (
            b'<html><body><a href="/sdmx_url">SDMX Data</a></body></html>'
        )
        mock_request.return_value = html_response

        def _bulk_fetcher(url, *, session):
            def _fail(ctx):
                raise requests.HTTPError("404 Client Error")

            return _fail

        mock_bulk_fetcher.side_effect = _bulk_fetcher

        with pytest.raises(
            ConnectionError, match="Could not download the WEO SDMX data"
        ):
            scraper.SDMXScraper.scrape("April", 2024)

    @patch("imf_reader.weo.scraper.bulk_fetcher")
    @patch("imf_reader.weo.scraper.make_request")
    def test_scrape_read_timeout_raises_connection_error(
        self, mock_request, mock_bulk_fetcher
    ):
        """A ReadTimeout reaches the caller as builtin ConnectionError. The fetcher
        retries neither it nor any other Timeout except ConnectTimeout, so it escapes
        on the first attempt."""
        html_response = Mock()
        html_response.content = (
            b'<html><body><a href="/sdmx_url">SDMX Data</a></body></html>'
        )
        mock_request.return_value = html_response

        def _bulk_fetcher(url, *, session):
            def _fail(ctx):
                raise requests.ReadTimeout("read timed out")

            return _fail

        mock_bulk_fetcher.side_effect = _bulk_fetcher

        with pytest.raises(
            ConnectionError, match="Could not download the WEO SDMX data"
        ):
            scraper.SDMXScraper.scrape("April", 2024)

    @patch("imf_reader.weo.scraper.bulk_fetcher")
    @patch("imf_reader.weo.scraper.make_request")
    def test_scrape_no_data_error_propagates_untranslated(
        self, mock_request, mock_bulk_fetcher
    ):
        """NoDataError raised by the fetcher (e.g. from get_sdmx_url) must not be
        caught or translated by the network-failure handler."""
        html_response = Mock()
        html_response.content = (
            b'<html><body><a href="/sdmx_url">SDMX Data</a></body></html>'
        )
        mock_request.return_value = html_response

        def _bulk_fetcher(url, *, session):
            def _fail(ctx):
                raise NoDataError("SDMX data not found")

            return _fail

        mock_bulk_fetcher.side_effect = _bulk_fetcher

        with pytest.raises(NoDataError, match="SDMX data not found"):
            scraper.SDMXScraper.scrape("April", 2024)
