"""Module to read and process WEO data"""

import pandas as pd
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
import io
from zipfile import ZipFile

from imf_reader.config import NoDataError, UnexpectedFileError


BASE_URL = "https://www.imf.org/"

FIELDS_TO_MAP = {
    "UNIT": "IMF.CL_WEO_UNIT.1.0",
    "CONCEPT": "IMF.CL_WEO_CONCEPT.1.0",
    "REF_AREA": "IMF.CL_WEO_REF_AREA.1.0",
    "FREQ": "IMF.CL_FREQ.1.0",
    "SCALE": "IMF.CL_WEO_SCALE.1.0",
}


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


class Parser:
    """class to fetch and parse WEO data"""

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

        return f"{BASE_URL}{href}"

    @staticmethod
    def get_sdmx_folder(sdmx_url: str) -> ZipFile:
        """download SDMX data files as a zip file object

        Args:
            sdmx_url: The url to download the SDMX data files.
        """

        response = make_request(sdmx_url)
        folder = ZipFile(io.BytesIO(response.content))

        return folder

    @staticmethod
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

    @staticmethod
    def lookup_schema_element(schema_tree: ET.ElementTree, field_name) -> dict[str, str]:
        """Lookup the elements in the schema and find the label for a given label_name.

        Args:
            schema_tree: The schema tree to search.
            field_name: The label to search for.

        Returns:
            A dictionary with the label codes and label names.
        """

        xpath_expr = f"./{{http://www.w3.org/2001/XMLSchema}}simpleType[@name='{field_name}']/*/*"
        query = schema_tree.findall(xpath_expr)

        # Loop through the query and create a dictionary
        lookup_dict = {}
        for elem in query:
            lookup_dict[elem.attrib["value"]] = elem[0][0].text

        return lookup_dict

    @staticmethod
    def add_label_columns(data_df: pd.DataFrame, schema_tree: ET.ElementTree) -> pd.DataFrame:
        """Maps columns with codes to columns with labels and renames the code columns.

        Args:
            data_df: The DataFrame to add the label columns to.
            schema_tree: The schema tree to search for the labels.

        Returns:
            The DataFrame with the label columns and renamed code columns.
        """

        for column, lookup_name in FIELDS_TO_MAP.items():
            mapper = Parser.lookup_schema_element(schema_tree, lookup_name)
            data_df[f"{column}_LABEL"] = data_df[column].map(mapper)
            data_df.rename(columns={column: f"{column}_CODE"}, inplace=True)

        return data_df

    @staticmethod
    def check_folder(sdmx_folder: ZipFile) -> None:
        """Check that the folder contains the necessary files.

        Args:
            sdmx_folder: The folder to check.
        """

        # if there are more than two files in the folder raise error
        if len(sdmx_folder.namelist()) > 2:
            raise UnexpectedFileError("More than two files in zip file")

        # if there is no xml or xsd file in the folder raise error
        if not any(file.endswith(".xml") for file in sdmx_folder.namelist()):
            raise UnexpectedFileError("XML file not found in the folder")
        if not any(file.endswith(".xsd") for file in sdmx_folder.namelist()):
            raise UnexpectedFileError("XSD file not found in the folder")

        # logger.info("Folder check passed")

    @staticmethod
    def get_data(month, year) -> pd.DataFrame:
        """Pipeline to get the data from the WEO database."""

        sdmx_url = Parser.get_sdmx_url(month, year)
        sdmx_folder = Parser.get_sdmx_folder(sdmx_url)
        Parser.check_folder(sdmx_folder)

        # Get the data and schema trees
        data_tree = ET.parse(sdmx_folder.open([file for file in sdmx_folder.namelist() if file.endswith(".xml")][0]))
        schema_tree = ET.parse(sdmx_folder.open([file for file in sdmx_folder.namelist() if file.endswith(".xsd")][0]))

        # Parse the data
        data = Parser.parse_xml(data_tree)

        # clean the data
        data = Parser.add_label_columns(data, schema_tree)

        return data


























