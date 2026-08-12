"""Tests for weo scraper module."""

import io
import os
from unittest.mock import Mock, patch
from zipfile import ZipFile

import pytest
import requests
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


class TestSdmxUrlResolution:
    """Tests for _sdmx_url_candidates and _resolve_sdmx_url. All offline."""

    def test_candidates_month_segment_first_from_2024(self):
        """2024 is where the IMF switched to the month-segment path shape."""
        candidates = scraper._sdmx_url_candidates("April", 2024)
        assert len(candidates) == 3
        assert candidates[0].endswith("/2024/april/weoapr2024-sdmxdata.zip")

    def test_candidates_bare_first_before_2024(self):
        candidates = scraper._sdmx_url_candidates("October", 2023)
        assert len(candidates) == 3
        assert candidates[0].endswith("/2023/weooct2023-sdmxdata.zip")

    def test_candidates_known_good_urls(self):
        """Pinned as literals so a refactor cannot silently change them."""
        assert scraper._sdmx_url_candidates("April", 2025) == [
            "https://www.imf.org/-/media/files/publications/weo/weo-database"
            "/2025/april/weoapr2025-sdmxdata.zip",
            "https://www.imf.org/-/media/files/publications/weo/weo-database"
            "/2025/weoapr2025-sdmxdata.zip",
            "https://www.imf.org/-/media/files/publications/weo/weo-database"
            "/2025/01/weoapr2025-sdmxdata.zip",
        ]
        assert scraper._sdmx_url_candidates("October", 2023) == [
            "https://www.imf.org/-/media/files/publications/weo/weo-database"
            "/2023/weooct2023-sdmxdata.zip",
            "https://www.imf.org/-/media/files/publications/weo/weo-database"
            "/2023/october/weooct2023-sdmxdata.zip",
            "https://www.imf.org/-/media/files/publications/weo/weo-database"
            "/2023/02/weooct2023-sdmxdata.zip",
        ]
        assert scraper._sdmx_url_candidates("October", 2020) == [
            "https://www.imf.org/-/media/files/publications/weo/weo-database"
            "/2020/weooct2020-sdmxdata.zip",
            "https://www.imf.org/-/media/files/publications/weo/weo-database"
            "/2020/october/weooct2020-sdmxdata.zip",
            "https://www.imf.org/-/media/files/publications/weo/weo-database"
            "/2020/02/weooct2020-sdmxdata.zip",
        ]

    def test_invalid_month_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported month"):
            scraper._sdmx_url_candidates("March", 2024)

    @patch("imf_reader.weo.scraper.get_uncached_session")
    def test_resolve_returns_first_candidate_hit(self, mock_get_session):
        session = Mock()
        session.get.return_value = Mock(status_code=200)
        mock_get_session.return_value = session

        url = scraper._resolve_sdmx_url("April", 2025)

        assert url == scraper._sdmx_url_candidates("April", 2025)[0]
        assert session.get.call_count == 1

    @patch("imf_reader.weo.scraper.get_uncached_session")
    def test_resolve_falls_through_404s_to_later_candidate(self, mock_get_session):
        """October 2020: the first two forms 404, the release-number form succeeds."""
        session = Mock()
        session.get.side_effect = [
            Mock(status_code=404),
            Mock(status_code=404),
            Mock(status_code=206),
        ]
        mock_get_session.return_value = session

        url = scraper._resolve_sdmx_url("October", 2020)

        assert url == scraper._sdmx_url_candidates("October", 2020)[2]
        assert session.get.call_count == 3

    @patch("imf_reader.weo.scraper.get_uncached_session")
    def test_resolve_all_404_raises_no_data_error(self, mock_get_session):
        session = Mock()
        session.get.return_value = Mock(status_code=404)
        mock_get_session.return_value = session

        with pytest.raises(NoDataError) as exc_info:
            scraper._resolve_sdmx_url("October", 2025)

        message = str(exc_info.value)
        assert "October" in message
        assert "2025" in message
        for candidate in scraper._sdmx_url_candidates("October", 2025):
            assert candidate in message

    @patch("imf_reader.weo.scraper.get_uncached_session")
    def test_resolve_probes_with_ranged_get_not_head(self, mock_get_session):
        """HEAD is served by Akamai and 403s on this host; a ranged GET is served
        by Cloudflare and works. A refactor to HEAD would reintroduce the block."""
        session = Mock()
        session.get.return_value = Mock(status_code=200)
        mock_get_session.return_value = session

        scraper._resolve_sdmx_url("April", 2025)

        session.head.assert_not_called()
        _args, kwargs = session.get.call_args
        assert kwargs["headers"] == {"Range": "bytes=0-0"}
        assert kwargs["stream"] is True

    @patch("imf_reader.weo.scraper.get_uncached_session")
    def test_resolve_403_raises_instead_of_trying_next_candidate(
        self, mock_get_session
    ):
        """A 403 (e.g. bot management) is not "not found" -- it must fail loudly
        rather than fall through to the next candidate, which could paper over a
        media-path block by resolving to a stale or wrong release."""
        response = Mock(status_code=403)
        response.raise_for_status.side_effect = requests.HTTPError("403 Client Error")
        session = Mock()
        session.get.return_value = response
        mock_get_session.return_value = session

        with pytest.raises(requests.HTTPError):
            scraper._resolve_sdmx_url("April", 2025)

        assert session.get.call_count == 1

    @patch("imf_reader.weo.scraper.get_uncached_session")
    def test_resolve_propagates_transport_error(self, mock_get_session):
        """A genuine transport failure must surface to the caller, not be
        swallowed as 'not found'."""
        session = Mock()
        session.get.side_effect = requests.ConnectionError("connection refused")
        mock_get_session.return_value = session

        with pytest.raises(requests.ConnectionError):
            scraper._resolve_sdmx_url("April", 2025)


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
    @patch("imf_reader.weo.scraper.SDMXScraper.get_sdmx_url")
    def test_scrape_cache_hit_skips_http(self, mock_get_sdmx_url, mock_bulk_fetcher):
        """Second scrape() call must not hit the network when a valid cache entry exists."""
        zip_bytes = _make_zip_bytes("sdmx.xml", "<data/>")
        mock_get_sdmx_url.return_value = TEST_URL
        mock_bulk_fetcher.side_effect = _fake_bulk_fetcher_writing(zip_bytes)

        # The first call misses the cache, resolving the URL and downloading content.
        result1 = scraper.SDMXScraper.scrape("April", 2024)
        assert isinstance(result1, ZipFile)
        assert mock_get_sdmx_url.call_count == 1
        assert mock_bulk_fetcher.call_count == 1

        # Reset call counts. The second call should be a cache hit, so the fetcher
        # (and therefore the URL resolution it wraps) must not run at all.
        mock_get_sdmx_url.reset_mock()
        mock_bulk_fetcher.reset_mock()

        result2 = scraper.SDMXScraper.scrape("April", 2024)
        assert isinstance(result2, ZipFile)
        mock_get_sdmx_url.assert_not_called()
        mock_bulk_fetcher.assert_not_called()

    @patch("imf_reader.weo.scraper.bulk_fetcher")
    @patch("imf_reader.weo.scraper.SDMXScraper.get_sdmx_url")
    def test_scrape_corrupt_zip_raises_BulkPayloadCorruptError(
        self, mock_get_sdmx_url, mock_bulk_fetcher
    ):
        """A non-zip payload must raise BulkPayloadCorruptError and leave no cache entry."""
        mock_get_sdmx_url.return_value = TEST_URL
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
    @patch("imf_reader.weo.scraper.SDMXScraper.get_sdmx_url")
    def test_scrape_transport_failure_raises_connection_error(
        self, mock_get_sdmx_url, mock_bulk_fetcher
    ):
        """A readerkit transport failure during the download reaches the caller as
        ConnectionError, like every other network failure in the package."""
        mock_get_sdmx_url.return_value = TEST_URL

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
    @patch("imf_reader.weo.scraper.SDMXScraper.get_sdmx_url")
    def test_scrape_requests_connection_error_raises_connection_error(
        self, mock_get_sdmx_url, mock_bulk_fetcher
    ):
        """A requests.ConnectionError exhausted by the fetcher's own retries reaches
        the caller as builtin ConnectionError, like every other network failure in
        the package."""
        mock_get_sdmx_url.return_value = TEST_URL

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
    @patch("imf_reader.weo.scraper.SDMXScraper.get_sdmx_url")
    def test_scrape_http_error_raises_connection_error(
        self, mock_get_sdmx_url, mock_bulk_fetcher
    ):
        """An HTTPError from raise_for_status() (not retried by the fetcher) reaches
        the caller as builtin ConnectionError."""
        mock_get_sdmx_url.return_value = TEST_URL

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
    @patch("imf_reader.weo.scraper.SDMXScraper.get_sdmx_url")
    def test_scrape_read_timeout_raises_connection_error(
        self, mock_get_sdmx_url, mock_bulk_fetcher
    ):
        """A ReadTimeout reaches the caller as builtin ConnectionError. The fetcher
        retries neither it nor any other Timeout except ConnectTimeout, so it escapes
        on the first attempt."""
        mock_get_sdmx_url.return_value = TEST_URL

        def _bulk_fetcher(url, *, session):
            def _fail(ctx):
                raise requests.ReadTimeout("read timed out")

            return _fail

        mock_bulk_fetcher.side_effect = _bulk_fetcher

        with pytest.raises(
            ConnectionError, match="Could not download the WEO SDMX data"
        ):
            scraper.SDMXScraper.scrape("April", 2024)

    @patch("imf_reader.weo.scraper.get_uncached_session")
    def test_scrape_403_reaches_caller_as_connection_error_not_no_data_error(
        self, mock_get_session
    ):
        """A 403 on every candidate must surface as ConnectionError, the same as
        any other network failure -- not as NoDataError, which reader.fetch_data
        would catch and silently roll back to a different release for."""
        response = Mock(status_code=403)
        response.raise_for_status.side_effect = requests.HTTPError("403 Client Error")
        session = Mock()
        session.get.return_value = response
        mock_get_session.return_value = session

        with pytest.raises(ConnectionError) as exc_info:
            scraper.SDMXScraper.scrape("April", 2024)

        assert not isinstance(exc_info.value, NoDataError)

    @patch("imf_reader.weo.scraper.bulk_fetcher")
    @patch("imf_reader.weo.scraper.SDMXScraper.get_sdmx_url")
    def test_scrape_no_data_error_propagates_untranslated(
        self, mock_get_sdmx_url, mock_bulk_fetcher
    ):
        """NoDataError raised by the fetcher (e.g. from URL resolution) must not be
        caught or translated by the network-failure handler."""
        mock_get_sdmx_url.return_value = TEST_URL

        def _bulk_fetcher(url, *, session):
            def _fail(ctx):
                raise NoDataError("SDMX data not found")

            return _fail

        mock_bulk_fetcher.side_effect = _bulk_fetcher

        with pytest.raises(NoDataError, match="SDMX data not found"):
            scraper.SDMXScraper.scrape("April", 2024)


class TestKnownCorruptReleaseMessage:
    """The corrupt-zip error is enriched, and marked non-retryable, only for the
    two releases known to be corrupt at the IMF's own source."""

    @patch("imf_reader.weo.scraper.bulk_fetcher")
    @patch("imf_reader.weo.scraper.SDMXScraper.get_sdmx_url")
    def test_known_corrupt_release_message_is_enriched(
        self, mock_get_sdmx_url, mock_bulk_fetcher
    ):
        mock_get_sdmx_url.return_value = TEST_URL
        mock_bulk_fetcher.side_effect = _fake_bulk_fetcher_writing(
            b"this is definitely not a zip file"
        )

        with pytest.raises(BulkPayloadCorruptError) as exc_info:
            scraper.SDMXScraper.scrape("October", 2023)

        message = str(exc_info.value)
        assert "IMF's own published archive" in message
        assert "not a bug in imf-reader" in message
        assert exc_info.value.is_retryable is False

    @patch("imf_reader.weo.scraper.bulk_fetcher")
    @patch("imf_reader.weo.scraper.SDMXScraper.get_sdmx_url")
    def test_healthy_release_message_is_not_enriched(
        self, mock_get_sdmx_url, mock_bulk_fetcher
    ):
        """A corrupt payload for a release that isn't on the known-corrupt list
        gets the plain message and stays retryable — the archive could just be
        having a bad day."""
        mock_get_sdmx_url.return_value = TEST_URL
        mock_bulk_fetcher.side_effect = _fake_bulk_fetcher_writing(
            b"this is definitely not a zip file"
        )

        with pytest.raises(BulkPayloadCorruptError) as exc_info:
            scraper.SDMXScraper.scrape("April", 2024)

        message = str(exc_info.value)
        assert "IMF's own published archive" not in message
        assert exc_info.value.is_retryable is True


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("IMF_READER_LIVE_TESTS") != "1",
    reason="hits the real IMF CDN; set IMF_READER_LIVE_TESTS=1 to run",
)
@pytest.mark.parametrize(
    ("month", "year"),
    [("April", 2025), ("October", 2023), ("October", 2020)],
)
def test_resolve_sdmx_url_live(month, year):
    """Resolves a known-good release against the real CDN.

    Only checks that a URL resolves, not that the zip is valid: April 2021 and
    October 2023's zips are corrupt at the IMF's source, not in transit.
    """
    url = scraper._resolve_sdmx_url(month, year)
    assert url.startswith(scraper.MEDIA_BASE)
