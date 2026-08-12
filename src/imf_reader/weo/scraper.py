"""Functions to scrape the IMF WEO website"""

import io
from datetime import timedelta
from pathlib import Path
from zipfile import BadZipFile, ZipFile, is_zipfile

import requests
from bs4 import BeautifulSoup
from readerkit import ArtifactCorruptError, FetchContext, TransportError, bulk_fetcher

from imf_reader.cache.config import get_artifact_cache, get_uncached_session
from imf_reader.config import BulkPayloadCorruptError, NoDataError, logger
from imf_reader.utils import make_request

BASE_URL = "https://www.imf.org/"


def get_soup(month: str, year: str | int) -> BeautifulSoup:
    """Get the BeautifulSoup object of the IMF WEO website.

    Args:
        month: The month of the data to download. Can be April or October.
        year: The year of the data to download.

    Returns:
        BeautifulSoup object of the IMF WEO website.
    """

    url = f"{BASE_URL}/en/Publications/WEO/weo-database/{year}/{month}/download-entire-database"
    response = make_request(url)
    soup = BeautifulSoup(response.content, "html.parser")

    return soup


class SDMXScraper:
    """Class to scrape the IMF WEO website for SDMX files.
    To use this class, call the scrape method with the month and year of the data to download.
    """

    @staticmethod
    def get_sdmx_url(soup: BeautifulSoup) -> str:
        """Get the url to download the WEO data in SDMX format.

        Args:
            soup: BeautifulSoup object of the IMF WEO website.

        Returns:
            The url to download the SDMX data.
        """

        try:
            href = soup.find("a", string="SDMX Data").get("href")
        except AttributeError:
            raise NoDataError("SDMX data not found")

        if href is None:
            raise NoDataError("SDMX data not found")

        logger.debug("SDMX URL found")
        return f"{href}"

    @staticmethod
    def get_sdmx_folder(sdmx_url: str) -> ZipFile:
        """download SDMX data files as a zip file object

        Args:
            sdmx_url: The url to download the SDMX data files.

        Returns:
            The zip file object containing the SDMX data files.
        """

        response = make_request(sdmx_url)
        folder = ZipFile(io.BytesIO(response.content))

        # Validate the zip file
        if folder.testzip():
            raise BadZipFile("Corrupt zip file")

        logger.debug("Zip folder downloaded successfully")
        return folder

    @staticmethod
    def scrape(month: str, year: str | int) -> ZipFile:
        """Pipeline to scrape SDMX files, with disk-backed caching.

        The first call for a given ``(month, year)`` downloads the SDMX zip from
        the IMF website, validates it, and stores it atomically on disk. The zip
        is a few MB and holds an XML payload around ten times that size. Subsequent
        calls within the TTL window (7 days) return the cached copy without any
        HTTP requests.

        Args:
            month: The month of the data to download. Can be April or October.
            year: The year of the data to download.

        Returns:
            The zip file object containing the SDMX data files.

        Raises:
            BulkPayloadCorruptError: If the downloaded zip fails integrity validation.
            ConnectionError: On any other network failure while downloading the zip.
        """
        key = f"weo_{str(month).lower()}_{int(year)}.zip"

        def _fetch(ctx: FetchContext) -> None:
            # The SDMX URL isn't known until the HTML page is scraped, so that
            # scrape happens inside the fetcher: a cache hit skips it entirely.
            soup = get_soup(month, year)
            sdmx_url = SDMXScraper.get_sdmx_url(soup)
            bulk_fetcher(sdmx_url, session=get_uncached_session())(ctx)

        def _validate(path: Path) -> None:
            if not is_zipfile(path):
                raise BulkPayloadCorruptError(f"Not a zip file for {month} {year}")
            with ZipFile(path) as zf:
                bad = zf.testzip()
                if bad is not None:
                    raise BulkPayloadCorruptError(
                        f"Corrupt zip for {month} {year}: bad entry {bad!r}"
                    )

        try:
            path = get_artifact_cache("weo_sdmx").ensure(
                key,
                fetcher=_fetch,
                ttl=timedelta(days=7),
                validator=_validate,
                suffix=".zip",
            )
        except ArtifactCorruptError as exc:
            raise BulkPayloadCorruptError(
                str(exc), key=exc.key, reason=exc.reason
            ) from exc
        except (TransportError, requests.RequestException) as exc:
            # Covers an exhausted requests.ConnectionError, an HTTPError from
            # raise_for_status(), and a Timeout, none of which the fetcher retries.
            # Every other network failure in the package reaches callers as ConnectionError.
            raise ConnectionError(
                f"Could not download the WEO SDMX data for {month} {year}. Error: {exc}"
            ) from exc
        return ZipFile(str(path))
