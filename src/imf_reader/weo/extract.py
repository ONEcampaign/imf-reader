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
from datetime import datetime

from imf_reader.config import NoDataError, UnexpectedFileError, logger


FIELDS_TO_MAP = {
    "UNIT": "IMF.CL_WEO_UNIT.1.0",
    "CONCEPT": "IMF.CL_WEO_CONCEPT.1.0",
    "REF_AREA": "IMF.CL_WEO_REF_AREA.1.0",
    "FREQ": "IMF.CL_FREQ.1.0",
    "SCALE": "IMF.CL_WEO_SCALE.1.0",
}

# numeric columns and the type to convert them to
NUMERIC_COLUMNS = ["REF_AREA_CODE", "OBS_VALUE", "SCALE_CODE", "LASTACTUALDATE", "TIME_PERIOD"]


class SDMXParser:
    """class to parse WEO SDMX files

    Args:
        sdmx_folder: The SDMX zip file to parse
    """

    def __init__(self, sdmx_folder: ZipFile):
        self.sdmx_folder = sdmx_folder

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

    def add_label_columns(self, data_df: pd.DataFrame, schema_tree: ET.ElementTree) -> pd.DataFrame:
        """Maps columns with codes to columns with labels and renames the code columns.

        Args:
            data_df: The DataFrame to add the label columns to.
            schema_tree: The schema tree to search for the labels.

        Returns:
            The DataFrame with the label columns and renamed code columns.
        """

        for column, lookup_name in FIELDS_TO_MAP.items():
            mapper = self.lookup_schema_element(schema_tree, lookup_name)
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

    def get_data(self, month: str, year: str | int) -> pd.DataFrame:
        """Main pipeline to get the data from the WEO database.

        This method will scrape the IMF website to retrieve the SDMX data files, parse the data and schema files,
        clean the data and return a DataFrame with the WEO data.

        Args:
            month: The month of the data to download. Can be April or October.
            year: The year of the data to download.

        Returns:
            A DataFrame with the WEO data.
        """

        self.check_folder(self.sdmx_folder)

        # Get the data and schema trees
        data_tree = ET.parse(self.sdmx_folder.open([file for file in self.sdmx_folder.namelist() if file.endswith(".xml")][0]))
        schema_tree = ET.parse(self.sdmx_folder.open([file for file in self.sdmx_folder.namelist() if file.endswith(".xsd")][0]))

        # Parse the data
        data = self.parse_xml(data_tree)

        # clean the data
        data = self.add_label_columns(data, schema_tree)  # add label columns
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


def gen_latest_version() -> Tuple[Literal["April", "October"], int]:
    """Generates the latest expected version based on the current date as a tuple of month and year"""

    current_year = datetime.now().year
    current_month = datetime.now().month

    # if month is less than 4 (April) return the version 2 (October) for the previous year
    if current_month < 4:
        return "October", current_year - 1

    # elif month is less than 10 (October) return current year and version 2 (April)
    elif current_month < 10:
        return "April", current_year

    # else (if month is more than 10 (October) return current month and version 2 (October)
    else:
        return "October", current_year


def roll_back_version(version: Tuple[Literal["April", "October"], int]) -> Tuple[Literal["April", "October"], int]:
    """Roll back version to the previous version

    Args:
        version: The version to roll back

    Returns:
        The rolled back version
    """

    if version[0] == "October":
        logger.info(f"Rolling back version to April {version[1]}")
        return "April", version[1]

    elif version[0] == "April":
        logger.info(f"Rolling back version to October {version[1] - 1}")
        return "October", version[1] - 1

    else:
        raise ValueError(f"Invalid version: {version}")


def fetch_data(version: Tuple[Literal["April", "October"], int] | str = "latest") -> pd.DataFrame:
    """Fetch WEO data from the IMF website

    Args:
        version: The version of the WEO data to fetch as a tuple of month and year. Valid months are 'April' and 'October'.
        If no version is provided, the latest version will be fetched.

    Returns:
        A pandas DataFrame with the WEO data.
    """

    if isinstance(version, str):
        if version != "latest":
            raise ValueError("Invalid version. Must be a tuple or 'latest'")
        version = gen_latest_version()
        try:
            df = SDMXParser.get_data(*version)
            logger.info(f"Latest WEO version {version[0]} {version[1]} data fetched successfully")
            return df

        # If no data is found, roll back version only once and if no data is found again, raise NoDataError
        except NoDataError:
            logger.warning(f"No data found for expected latest version {version[0]} {version[1]}")
            version = roll_back_version(version)
            try:
                df = SDMXParser.get_data(*version)
                logger.info(f"WEO version {version[0]} {version[1]} data fetched successfully")
                return df
            except NoDataError:
                raise NoDataError(f"No data found for expected versions {version} and {roll_back_version(version)}")
            except UnexpectedFileError:
                raise UnexpectedFileError(f"Unable to parse data for version {version[0]} {version[1]}")
            except Exception as e:
                raise e

        # Any other error, raise it
        except UnexpectedFileError:
            raise UnexpectedFileError(f"Unable to parse data for version {version[0]} {version[1]}")
        except Exception as e:
            raise e

    else:
        try:
            df = SDMXParser.get_data(validate_version_month(version[0]), version[1])
            logger.info(f"WEO version {version[0]} {version[1]} data fetched successfully")
            return df
        except NoDataError:
            raise NoDataError(f"No data found for version {version[0]} {version[1]}")
        except UnexpectedFileError:
            raise UnexpectedFileError(f"Unable to parse data for version {version[0]} {version[1]}")
        except Exception as e:
            raise e


































