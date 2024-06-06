"""Tests for weo parser module."""

import pytest
from unittest.mock import patch
import pandas as pd
import xml.etree.ElementTree as ET

from imf_reader.weo.parser import SDMXParser
from imf_reader.config import UnexpectedFileError


class TestSDMXParser:
    """Tests for SDMXParser class."""

    def test_parse_xml(self):
        """Test for parse_xml method."""

        # Create a mock XML tree
        root = ET.Element(
            "message:StructureSpecificData",
            attrib={
                "xmlns:ss": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/structurespecific",
                "xmlns:footer": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message/footer",
                "xmlns:ns1": "urn:sdmx:org.sdmx.infomodel.datastructure.DataStructure=IMF:WEO_PUB(1.0):ObsLevelDim:TIME_PERIOD",
                "xmlns:message": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message",
                "xmlns:common": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                "xmlns:xml": "http://www.w3.org/XML/1998/namespace",
            },
        )
        header = ET.SubElement(root, "message:Header")
        dataset = ET.SubElement(
            root,
            "message:DataSet",
            attrib={
                "ss:dataScope": "DataStructure",
                "xsi:type": "ns1:DataSetType",
                "ss:structureRef": "IMF_WEO_PUB_1_0",
            },
        )
        series = ET.SubElement(
            dataset,
            "Series",
            attrib={
                "UNIT": "B",
                "CONCEPT": "NGDP_D",
                "REF_AREA": "111",
                "FREQ": "A",
                "LASTACTUALDATE": "2023",
                "SCALE": "1",
                "NOTES": "See notes for:  Gross domestic product, constant prices (National currency) Gross domestic product, current prices (National currency).",
            },
        )
        obs = ET.SubElement(
            series, "Obs", attrib={"TIME_PERIOD": "1980", "OBS_VALUE": "39.372"}
        )

        tree = ET.ElementTree(root)

        # Call the parse_xml method
        df = SDMXParser.parse_xml(tree)

        # Create the expected DataFrame
        expected_df = pd.DataFrame(
            [
                {
                    "UNIT": "B",
                    "CONCEPT": "NGDP_D",
                    "REF_AREA": "111",
                    "FREQ": "A",
                    "LASTACTUALDATE": "2023",
                    "SCALE": "1",
                    "NOTES": "See notes for:  Gross domestic product, constant prices (National currency) Gross domestic product, current prices (National currency).",
                    "TIME_PERIOD": "1980",
                    "OBS_VALUE": "39.372",
                }
            ]
        )

        # Assert that the returned DataFrame is as expected
        pd.testing.assert_frame_equal(df, expected_df)

    def test_lookup_schema_element(self):
        """Test for lookup_schema_element method."""

        # Define the namespace
        ns = {"xs": "http://www.w3.org/2001/XMLSchema"}

        # Create a mock schema tree
        root = ET.Element("{%s}schema" % ns["xs"], attrib={"xmlns:xs": ns["xs"]})
        simpleType = ET.SubElement(
            root, "{%s}simpleType" % ns["xs"], attrib={"name": "IMF.CL_WEO_UNIT.1.0"}
        )
        restriction = ET.SubElement(
            simpleType, "{%s}restriction" % ns["xs"], attrib={"base": "xs:string"}
        )
        enumeration = ET.SubElement(
            restriction, "{%s}enumeration" % ns["xs"], attrib={"value": "A"}
        )
        annotation = ET.SubElement(enumeration, "{%s}annotation" % ns["xs"])
        documentation = ET.SubElement(annotation, "{%s}documentation" % ns["xs"])
        documentation.text = "Current international dollar"
        tree = ET.ElementTree(root)

        # Call the lookup_schema_element method
        lookup_dict = SDMXParser.lookup_schema_element(tree, "IMF.CL_WEO_UNIT.1.0")

        # Create the expected dictionary
        expected_dict = {"A": "Current international dollar"}

        # Assert that the returned dictionary is as expected
        assert lookup_dict == expected_dict

    @patch(
        "imf_reader.weo.parser.SDMXParser.lookup_schema_element",
        return_value={"A": "Current international dollar"},
    )
    def test_add_label_columns(self, mock_lookup):
        """Test for add_label_columns method."""

        # Create a mock DataFrame
        data_df = pd.DataFrame(
            [
                {
                    "UNIT": "A",
                    "CONCEPT": "NGDP_D",
                    "REF_AREA": "111",
                    "FREQ": "A",
                    "LASTACTUALDATE": "2023",
                    "SCALE": "1",
                    "NOTES": "See notes for:  Gross domestic product, constant prices (National currency) Gross domestic product, current prices (National currency).",
                    "TIME_PERIOD": "1980",
                    "OBS_VALUE": "39.372",
                }
            ]
        )

        # Call the add_label_columns method
        result_df = SDMXParser.add_label_columns(data_df, None)

        # Assert that the returned DataFrame is a DataFrame
        assert isinstance(result_df, pd.DataFrame)

        assert "UNIT_LABEL" in result_df.columns
        assert "UNIT_CODE" in result_df.columns

        assert result_df["UNIT_CODE"].iloc[0] == "A"
        assert result_df["UNIT_LABEL"].iloc[0] == "Current international dollar"

    @patch("zipfile.ZipFile")
    def test_check_folder(self, mock_zip):
        """Test for check_folder method."""

        # check that the xml check raises an error when there are more than one xml file
        mock_zip.namelist.return_value = ["file1.xml", "file2.xml", "file1.xsd"]
        with pytest.raises(
            UnexpectedFileError,
            match="There should be exactly one xml file in the folder",
        ):
            SDMXParser.check_folder(mock_zip)

        # check that the xml check raises an error when there are no xml files
        mock_zip.namelist.return_value = ["file1.xsd"]
        with pytest.raises(
            UnexpectedFileError,
            match="There should be exactly one xml file in the folder",
        ):
            SDMXParser.check_folder(mock_zip)

        # check that the xsd check raises an error when there are more than one xsd file
        mock_zip.namelist.return_value = ["file1.xml", "file1.xsd", "file2.xsd"]
        with pytest.raises(
            UnexpectedFileError,
            match="There should be exactly one xsd file in the folder",
        ):
            SDMXParser.check_folder(mock_zip)

        # check that the xsd check raises an error when there are no xsd files
        mock_zip.namelist.return_value = ["file1.xml"]
        with pytest.raises(
            UnexpectedFileError,
            match="There should be exactly one xsd file in the folder",
        ):
            SDMXParser.check_folder(mock_zip)

        # check that the function doesn't raise an error when there is one xml and one xsd file
        mock_zip.namelist.return_value = ["file1.xml", "file1.xsd"]
        assert SDMXParser.check_folder(mock_zip) is None

    def test_clean_numeric_columns(self):
        """Test for clean_numeric_columns method."""

        # Create a DataFrame with some numeric columns containing "n/a" and "--"
        data_df = pd.DataFrame(
            {
                "REF_AREA_CODE": ["1", "2", "n/a", "--"],
                "OBS_VALUE": ["1.1", "2.2", "n/a", ""],
                "SCALE_CODE": ["3", "4", "n/a", "NULL"],
                "LASTACTUALDATE": ["2023", "2024", "n/a", "--"],
                "TIME_PERIOD": ["1980", "1981", "n/a", "--"],
            }
        )

        # Call the clean_numeric_columns method
        result_df = SDMXParser.clean_numeric_columns(data_df)

        # Create the expected DataFrame
        expected_df = pd.DataFrame(
            {
                "REF_AREA_CODE": [1, 2, pd.NA, pd.NA],
                "OBS_VALUE": [1.1, 2.2, pd.NA, pd.NA],
                "SCALE_CODE": [3, 4, pd.NA, pd.NA],
                "LASTACTUALDATE": [2023, 2024, pd.NA, pd.NA],
                "TIME_PERIOD": [1980, 1981, pd.NA, pd.NA],
            }
        )

        # Assert that the columns are numeric
        for column in result_df.columns:
            assert pd.api.types.is_numeric_dtype(result_df[column])

        # Assert that "n/a" and "--" have been replaced with nulls
        for column in result_df.columns:
            assert result_df[column].isnull().any()

        # check error is raised if any other unusual values are present
        data_df = pd.DataFrame(
            {
                "REF_AREA_CODE": ["1", "2", "n/a", "--"],
                "OBS_VALUE": ["1.1", "2.2", "n/a", "abc"],
                "SCALE_CODE": ["3", "4", "n/a", "--"],
                "LASTACTUALDATE": ["2023", "2024", "n/a", "--"],
                "TIME_PERIOD": ["1980", "1981", "n/a", "--"],
            }
        )

        with pytest.raises(ValueError):
            SDMXParser.clean_numeric_columns(data_df)
