"""Functions to scrape the IMF WEO website"""

import requests
from bs4 import BeautifulSoup
import io
from zipfile import ZipFile, BadZipFile

from imf_reader.config import NoDataError, UnexpectedFileError, logger

BASE_URL = "https://www.imf.org/"


def make_request(url: str) -> requests.models.Response:
    """Make a request to a url.

    Args:
        url: url to make request to

    Returns:
        requests.models.Response: response object
    """

    try:
        response = requests.get(url)
        if response.status_code != 200:
            raise ConnectionError(
                f"Could not connect to {url}. Status code: {response.status_code}"
            )

        return response

    except requests.exceptions.RequestException as e:
        raise ConnectionError(f"Could not connect to {url}. Error: {str(e)}")


class SDMXScraper:
    """Class to scrape the IMF WEO website for SDMX files."""

    @staticmethod
    def get_sdmx_url(month: str, year: int | str) -> str:
        """Get the url to download the WEO data in SDMX format.

        Args:
            month: The month of the data to download. Can be April or October.
            year: The year of the data to download.
        """

        url = f"{BASE_URL}/en/Publications/WEO/weo-database/{year}/{month}/download-entire-database"
        response = make_request(url)
        soup = BeautifulSoup(response.content, "html.parser")
        href = soup.find("a", string="SDMX Data").get("href")

        if href is None:
            raise NoDataError("SDMX Data link not found")

        logger.debug("SDMX URL found")
        return f"{BASE_URL}{href}"

    @staticmethod
    def get_sdmx_folder(sdmx_url: str) -> ZipFile:
        """download SDMX data files as a zip file object

        Args:
            sdmx_url: The url to download the SDMX data files.
        """

        response = make_request(sdmx_url)
        folder = ZipFile(io.BytesIO(response.content))

        # Validate the zip file
        if folder.testzip():
            raise BadZipFile("Corrupt zip file")

        logger.debug("Zip folder downloaded successfully")
        return folder


class TabScraper:
    """Class to scrape the IMF WEO website for tab files."""

    pass



