"""Functions to scrape the IMF WEO website"""

import io
from datetime import timedelta
from zipfile import BadZipFile, ZipFile, is_zipfile

from bs4 import BeautifulSoup

from imf_reader.config import BulkPayloadCorruptError, NoDataError, logger
from imf_reader.utils import make_request

BASE_URL = "https://www.imf.org/"

# Lazy singleton — created on first use so no I/O at import time.
_zip_cache = None


def _get_zip_cache():
    """Return the module-level CacheManager, creating it on first access."""
    global _zip_cache
    if _zip_cache is None:
        from imf_reader.cache.manager import CacheManager

        _zip_cache = CacheManager(sublayer="weo_sdmx", ttl=timedelta(days=7), keep_n=4)
    return _zip_cache


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

        The first call for a given ``(month, year)`` downloads the ~30 MB SDMX
        zip from the IMF website, validates it, and stores it atomically on disk.
        Subsequent calls within the TTL window (7 days) return the cached copy
        without any HTTP requests.

        Args:
            month: The month of the data to download. Can be April or October.
            year: The year of the data to download.

        Returns:
            The zip file object containing the SDMX data files.

        Raises:
            BulkPayloadCorruptError: If the downloaded (or cached) zip fails
                integrity validation.
        """
        key = f"weo_{str(month).lower()}_{int(year)}.zip"

        def _fetch_bytes() -> bytes:
            soup = get_soup(month, year)
            sdmx_url = SDMXScraper.get_sdmx_url(soup)
            # Bypass the requests-cache layer: this payload is validated and
            # cached by CacheManager. Letting requests-cache also store it would
            # mean that a corrupt 200 response (truncated/non-zip) gets retained
            # for 1 day, so the next retry would read the same corrupt body
            # instead of re-downloading.
            response = make_request(sdmx_url, use_http_cache=False)
            return response.content

        def _validate(content: bytes) -> None:
            if not is_zipfile(io.BytesIO(content)):
                raise BulkPayloadCorruptError(f"Not a zip file for {month} {year}")
            with ZipFile(io.BytesIO(content)) as zf:
                bad = zf.testzip()
                if bad is not None:
                    raise BulkPayloadCorruptError(
                        f"Corrupt zip for {month} {year}: bad entry {bad!r}"
                    )

        path = _get_zip_cache().get_or_fetch(key, _fetch_bytes, validator=_validate)
        return ZipFile(str(path))
