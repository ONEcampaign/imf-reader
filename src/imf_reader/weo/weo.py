"""Module to read and process WEO data"""

import pandas as pd
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
import io
from zipfile import ZipFile


BASE_URL = "https://www.imf.org/"


def get_sdmx_url(month, year) -> str:
    """Get the url to download the WEO data in SDMX format."""

    url = f"{BASE_URL}/en/Publications/WEO/weo-database/{year}/{month}/download-entire-database"
    response = requests.get(url)
    soup = BeautifulSoup(response.content, "html.parser")
    href = soup.find("a", string="SDMX Data").get("href")

    return f"{BASE_URL}{href}"


def get_sdmx_folder(sdmx_url: str) -> ZipFile:
    """download SDMX data files as a zip file object"""

    response = requests.get(sdmx_url)
    folder = ZipFile(io.BytesIO(response.content))

    return folder


def parse_xml(tree: ET.ElementTree) -> pd.DataFrame:
    """Parse the WEO XML tree and return a DataFrame with the data.

    Args:
        tree: The XML tree to parse.

    Returns:
        A DataFrame with the data.
    """

    rows = []  # List of dictionaries to store the data
    root = tree.getroot()
    for series in root[1]:  # Datasets are in the second element of the root
        for obs in series:
            rows.append({**series.attrib, **obs.attrib})

    return pd.DataFrame(rows)


