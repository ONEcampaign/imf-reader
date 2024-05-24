"""Script to parse data from the IMF WEO website."""

import pandas as pd
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile
from typing import Literal, Tuple
import numpy as np

from imf_reader.config import NoDataError, UnexpectedFileError, logger

SDMX_FIELDS_TO_MAP = {
    "UNIT": "IMF.CL_WEO_UNIT.1.0",
    "CONCEPT": "IMF.CL_WEO_CONCEPT.1.0",
    "REF_AREA": "IMF.CL_WEO_REF_AREA.1.0",
    "FREQ": "IMF.CL_FREQ.1.0",
    "SCALE": "IMF.CL_WEO_SCALE.1.0",
}

TAB_COL_MAPPER = {'WEO Country Code': "REF_AREA_CODE",
                      'ISO': "ISO_CODE",
                      'WEO Subject Code': "CONCEPT_CODE",
                      'Country': "REF_AREA_LABEL",
                      'Subject Descriptor': "CONCEPT_LABEL",
                      'Subject Notes': "CONCEPT_NOTES",
                      'Units': "UNIT",
                      'Scale': "SCALE_LABEL",
                      "Estimates Start After": "LASTACTUALDATE",
                      "Country/Series-specific Notes": "NOTES",
                      "WEO Country Group Code": "REF_AREA_CODE",
                      "Country Group Name": "REF_AREA_LABEL"
                      }

# numeric columns and the type to convert them to
SDMX_NUMERIC_COLUMNS = ["REF_AREA_CODE", "OBS_VALUE", "SCALE_CODE", "LASTACTUALDATE", "TIME_PERIOD"]


class SDMXParser:
    """Class to parse SDMX data"""

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

        for column, lookup_name in SDMX_FIELDS_TO_MAP.items():
            mapper = SDMXParser.lookup_schema_element(schema_tree, lookup_name)
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
    def parse(sdmx_folder: ZipFile) -> pd.DataFrame:
        """Pipeline to parse the SDMX data files.

        Args:
            sdmx_folder: The folder containing the SDMX data files.

        Returns:
            A DataFrame with the WEO data.
        """

        SDMXParser.check_folder(sdmx_folder)

        # Get the data and schema trees
        data_tree = ET.parse(sdmx_folder.open([file for file in sdmx_folder.namelist() if file.endswith(".xml")][0]))
        schema_tree = ET.parse(sdmx_folder.open([file for file in sdmx_folder.namelist() if file.endswith(".xsd")][0]))

        # Parse the data
        data = SDMXParser.parse_xml(data_tree)

        # clean the data
        data = SDMXParser.add_label_columns(data, schema_tree)  # add label columns
        data[SDMX_NUMERIC_COLUMNS] = data[SDMX_NUMERIC_COLUMNS].apply(pd.to_numeric,
                                                                      errors="coerce")  # convert to numeric

        logger.debug("Data successfully retrieved and cleaned")
        return data


class TabParser:
    """Class to parse the WEO tabular data"""

    @staticmethod
    def remove_footnote(df: pd.DataFrame) -> pd.DataFrame:
        """Remove the footnote from the DataFrame."""

        if "International Monetary Fund" in df.iloc[-1, 0]:
            return df.iloc[:-1]
        return df

    @staticmethod
    def remove_unwanted_cols(df: pd.DataFrame) -> pd.DataFrame:
        """Remove unwanted columns from the DataFrame such as any null unnamed columns."""
        return df.loc[:, ~df.columns.str.contains('^Unnamed')]

    @staticmethod
    def clean_value_col(df: pd.DataFrame) -> pd.DataFrame:
        """Clean the value column by removing commas, fixing nulls and converting to numeric."""

        df["OBS_VALUE"] = pd.to_numeric(df["OBS_VALUE"].str.replace(",", "").replace('--', np.nan))
        return df

    @staticmethod
    def clean_country_data(df):
        """ """

        (df
         .pipe(TabParser.remove_footnote)
         .pipe(TabParser.remove_unwanted_cols)
         .rename(columns = TAB_COL_MAPPER) # rename columns
         .melt(id_vars = TAB_COL_MAPPER.values(), var_name = "TIME_PERIOD", value_name="OBS_VALUE")  # melt to long
         .pipe(TabParser.clean_value_col)  # clean the value column
         )

