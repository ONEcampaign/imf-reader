"""Functions to scrape the IMF WEO website"""

import requests
from bs4 import BeautifulSoup
import io
from zipfile import ZipFile, BadZipFile
import chardet
import pandas as pd

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


def get_soup(month, year):
    """ """

    url = f"{BASE_URL}/en/Publications/WEO/weo-database/{year}/{month}/download-entire-database"
    response = make_request(url)
    soup = BeautifulSoup(response.content, "html.parser")

    return soup


class SDMXScraper:
    """Class to scrape the IMF WEO website for SDMX files."""

    @staticmethod
    def get_sdmx_url(soup) -> str:
        """Get the url to download the WEO data in SDMX format."""

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

    @staticmethod
    def scrape(month: str, year: str | int) -> ZipFile:
        """Pipeline to scrape SDMX files"""

        # Scrape the IMF WEO website
        soup = get_soup(month, year)

        # find the url to download the SDMX data
        sdmx_url = SDMXScraper.get_sdmx_url(soup)

        # download the SDMX data files
        sdmx_folder = SDMXScraper.get_sdmx_folder(sdmx_url)

        return sdmx_folder


def detect_encoding(response: requests.models.Response) -> str:
    """Detect the encoding of a response.

    Args:
        response: The response object to detect the encoding of.

    Returns:
        The encoding of the response.
    """

    encoding = chardet.detect(response.content)["encoding"]

    if encoding is None:
        raise ValueError("Could not detect encoding of response")

    return encoding


class TabScraper:
    """Class to scrape the IMF WEO website for tab files."""

    @staticmethod
    def get_country_href(soup) -> str:
        """ """

        href = soup.find("a", string="By Countries").get("href")

        if href is None:
            raise NoDataError("Country link not found")

        logger.debug("Country URL found")
        return f"{BASE_URL}{href}"

    @staticmethod
    def get_region_href(soup) -> str:
        """ """

        href = soup.find("a", string="By Country Groups").get("href")

        if href is None:
            raise NoDataError("Region link not found")

        logger.debug("Region URL found")
        return f"{BASE_URL}{href}"

    @staticmethod
    def read_data(href: str):
        """ """

        response = make_request(href)
        encoding = detect_encoding(response)

        try:
            return pd.read_csv(io.BytesIO(response.content), delimiter="\t", encoding=encoding)
        except pd.errors.ParserError as e:
            raise pd.errors.ParserError(f"Could not parse data: {str(e)}")

    @staticmethod
    def scrape(month: str, year: str | int) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Pipeline to scrape tab files from the IMF WEO website."""

        # Scrape the IMF WEO website
        soup = get_soup(month, year)

        # find the hrefs for the country and region tab files
        country_href = TabScraper.get_country_href(soup)
        region_href = TabScraper.get_region_href(soup)

        # read the tab files
        country_data = TabScraper.read_data(country_href)
        region_data = TabScraper.read_data(region_href)

        # return the data
        return country_data, region_data





