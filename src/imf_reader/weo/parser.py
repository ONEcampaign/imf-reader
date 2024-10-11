"""Script to parse data from the IMF WEO website."""

import pandas as pd
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from imf_reader.config import UnexpectedFileError, logger

# columns to map to labels and the schema element to look them up
SDMX_FIELDS_TO_MAP = {
    "UNIT": "IMF.CL_WEO_UNIT.1.0",
    "CONCEPT": "IMF.CL_WEO_CONCEPT.1.0",
    "REF_AREA": "IMF.CL_WEO_REF_AREA.1.0",
    "FREQ": "IMF.CL_FREQ.1.0",
    "SCALE": "IMF.CL_WEO_SCALE.1.0",
}

# numeric columns and the type to convert them to
SDMX_NUMERIC_COLUMNS = {
    "OBS_VALUE": "Float64",
    "REF_AREA_CODE": "Int64",
    "SCALE_CODE": "Int64",
    "LASTACTUALDATE": "Int64",
    "TIME_PERIOD": "Int64",
}


class SDMXParser:
    """Class to parse SDMX data
    To use this class, call the parse method with the folder containing the SDMX files.
    """

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
    def lookup_schema_element(
        schema_tree: ET.ElementTree, field_name
    ) -> dict[str, str]:
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
    def add_label_columns(
        data_df: pd.DataFrame, schema_tree: ET.ElementTree
    ) -> pd.DataFrame:
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
            raise UnexpectedFileError(
                "There should be exactly one xml file in the folder"
            )

        if len([file for file in sdmx_folder.namelist() if file.endswith(".xsd")]) != 1:
            raise UnexpectedFileError(
                "There should be exactly one xsd file in the folder"
            )

        logger.debug("Zip folder check passed")

    @staticmethod
    def clean_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Cleans the numeric columns
        Replaces non numeric values with null values and converts the columns to numeric and the correct type.

        Returns:
            The DataFrame with the numeric columns cleaned.

        """

        for column, dtype in SDMX_NUMERIC_COLUMNS.items():
            df[column] = df[column].str.replace(",", "")  # Remove commas
            df[column] = pd.to_numeric(
                df[column], errors="coerce"
            )  # Convert to numeric
            df[column] = df[column].astype(dtype)

        # set type for the other columns to string
        for column in df.columns:
            if column not in SDMX_NUMERIC_COLUMNS.keys():
                df[column] = df[column].astype("string")

        return df

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
        data_tree = ET.parse(
            sdmx_folder.open(
                [file for file in sdmx_folder.namelist() if file.endswith(".xml")][0]
            )
        )
        schema_tree = ET.parse(
            sdmx_folder.open(
                [file for file in sdmx_folder.namelist() if file.endswith(".xsd")][0]
            )
        )

        # Parse and clean the data
        data = SDMXParser.parse_xml(data_tree)  # Parse the xml data
        data = SDMXParser.add_label_columns(data, schema_tree)  # add label columns
        data = SDMXParser.clean_numeric_columns(data)  # convert to numeric

        logger.debug("Data successfully parsed")
        return data
