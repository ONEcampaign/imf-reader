"""Module to read and process WEO data

TODO: default to latest version
TODO: implement tests

"""

import pandas as pd
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
import io
from zipfile import ZipFile, BadZipFile
from typing import Literal, Tuple

from imf_reader.config import NoDataError, UnexpectedFileError, logger


BASE_URL = "https://www.imf.org/"

FIELDS_TO_MAP = {
    "UNIT": "IMF.CL_WEO_UNIT.1.0",
    "CONCEPT": "IMF.CL_WEO_CONCEPT.1.0",
    "REF_AREA": "IMF.CL_WEO_REF_AREA.1.0",
    "FREQ": "IMF.CL_FREQ.1.0",
    "SCALE": "IMF.CL_WEO_SCALE.1.0",
}

# numeric columns and the type to convert them to
NUMERIC_COLUMNS = ["REF_AREA_CODE", "OBS_VALUE", "SCALE_CODE", "LASTACTUALDATE", "TIME_PERIOD"]


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

        logger.debug("XML parsed successfully")
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

        logger.debug(".xsd schema parsed and columns added successfully")
        return data_df

    @staticmethod
    def check_folder(sdmx_folder: ZipFile) -> None:
        """Check that the folder contains the necessary files.

        This method checks that there is only 1 xml and 1 xsd file in the folder.

        Args:
            sdmx_folder: The folder to check.
        """

        if len([file for file in sdmx_folder.namelist() if file.endswith(".xml")]) != 1:
            raise UnexpectedFileError("There should be exactly one xml file in the folder")

        if len([file for file in sdmx_folder.namelist() if file.endswith(".xsd")]) != 1:
            raise UnexpectedFileError("There should be exactly one xsd file in the folder")

        logger.debug("Zip folder check passed")

    @staticmethod
    def get_data(month: str, year: str | int) -> pd.DataFrame:
        """Main pipeline to get the data from the WEO database.

        This method will scrape the IMF website to retrieve the SDMX data files, parse the data and schema files,
        clean the data and return a DataFrame with the WEO data.

        Args:
            month: The month of the data to download. Can be April or October.
            year: The year of the data to download.

        Returns:
            A DataFrame with the WEO data.
        """

        sdmx_url = Parser.get_sdmx_url(month, year)
        sdmx_folder = Parser.get_sdmx_folder(sdmx_url)
        Parser.check_folder(sdmx_folder)

        # Get the data and schema trees
        data_tree = ET.parse(sdmx_folder.open([file for file in sdmx_folder.namelist() if file.endswith(".xml")][0]))
        schema_tree = ET.parse(sdmx_folder.open([file for file in sdmx_folder.namelist() if file.endswith(".xsd")][0]))

        # Parse the data
        data = Parser.parse_xml(data_tree)

        # clean the data
        data = Parser.add_label_columns(data, schema_tree)  # add label columns
        data[NUMERIC_COLUMNS] = data[NUMERIC_COLUMNS].apply(pd.to_numeric, errors="coerce")  # convert to numeric

        logger.debug("Data successfully retrieved and cleaned")
        return data


def validate_version_month(month: str) -> str:
    """Checks that the month is April or October
    removes whitespace and converts to sentence case

    Args:
        month: The month to validate

    Returns:
        The validated month
    """

    # clean string - remove whitespace and convert to sentence case
    month = month.strip().capitalize()

    if month not in ["April", "October"]:
        raise TypeError("Invalid month. Must be `April` or `October`")

    return month


def fetch_weo(version: Tuple[Literal["April", "October"], int]) -> pd.DataFrame:
    """Fetch WEO data from the IMF website"""

    month, year = version
    month = validate_version_month(month)
    df = Parser.get_data(month, year)

    logger.info(f"WEO version {month} {year} data fetched successfully")
    return df


































