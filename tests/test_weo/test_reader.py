"""Tests for reader module"""

import io
import xml.etree.ElementTree as ET
from datetime import datetime
from unittest.mock import patch
from zipfile import ZipFile

import pandas as pd
import pytest

from imf_reader.config import NoDataError
from imf_reader.weo import reader
from imf_reader.weo import translate as translate_module
from imf_reader.weo.api import OUTPUT_COLUMNS
from imf_reader.weo.scraper import SDMXScraper


def _build_sdmx_zip_bytes(
    *,
    ref_area: str = "111",
    concept: str = "NGDP",
    unit: str = "E",
    freq: str = "A",
    scale: str = "1",
    time_period: str = "2024",
    obs_value: str = "100.5",
) -> bytes:
    """Build a minimal real SDMX zip -- one Series/Obs pair plus a schema
    carrying just enough codelist entries for SDMXParser.parse to run
    end to end, mirroring the shape test_parser.py's own tests construct."""
    # Plain (unprefixed) tag names: parse_xml only cares about root[1]'s
    # position and each Series/Obs's attributes, not real SDMX-ML namespaces.
    # A colon-prefixed tag with no xmlns declaration parses fine in memory but
    # fails on the real XML parser once serialised and re-read from the zip.
    root = ET.Element("StructureSpecificData")
    ET.SubElement(root, "Header")
    dataset = ET.SubElement(root, "DataSet")
    series = ET.SubElement(
        dataset,
        "Series",
        attrib={
            "UNIT": unit,
            "CONCEPT": concept,
            "REF_AREA": ref_area,
            "FREQ": freq,
            "LASTACTUALDATE": "2023",
            "SCALE": scale,
            "NOTES": "",
        },
    )
    ET.SubElement(
        series, "Obs", attrib={"TIME_PERIOD": time_period, "OBS_VALUE": obs_value}
    )
    xml_bytes = ET.tostring(root)

    xs = "http://www.w3.org/2001/XMLSchema"
    schema_root = ET.Element(f"{{{xs}}}schema")
    codelists = {
        "IMF.CL_WEO_UNIT.1.0": (unit, "zip unit label"),
        "IMF.CL_WEO_CONCEPT.1.0": (concept, "zip concept label"),
        "IMF.CL_WEO_REF_AREA.1.0": (ref_area, "zip area label"),
        "IMF.CL_FREQ.1.0": (freq, "Annual"),
        "IMF.CL_WEO_SCALE.1.0": (scale, "Units"),
    }
    for simple_type_name, (value, label) in codelists.items():
        simple_type = ET.SubElement(
            schema_root, f"{{{xs}}}simpleType", attrib={"name": simple_type_name}
        )
        restriction = ET.SubElement(
            simple_type, f"{{{xs}}}restriction", attrib={"base": "xs:string"}
        )
        enumeration = ET.SubElement(
            restriction, f"{{{xs}}}enumeration", attrib={"value": value}
        )
        annotation = ET.SubElement(enumeration, f"{{{xs}}}annotation")
        documentation = ET.SubElement(annotation, f"{{{xs}}}documentation")
        documentation.text = label
    xsd_bytes = ET.tostring(schema_root)

    buf = io.BytesIO()
    with ZipFile(buf, "w") as zf:
        zf.writestr("weo_data.xml", xml_bytes)
        zf.writestr("weo_schema.xsd", xsd_bytes)
    return buf.getvalue()


def test_validate_version():
    """Test for validate_version function."""

    # Test that the function correctly validates a valid version
    assert reader.validate_version(("April", 2024)) == ("April", 2024)  # April
    assert reader.validate_version(("October", 2024)) == ("October", 2024)  # October

    # Test that the function correctly validates a valid version with different case and leading/trailing spaces
    assert reader.validate_version((" april ", "2024")) == ("April", 2024)
    assert reader.validate_version(("october", " 2024 ")) == ("October", 2024)
    assert reader.validate_version((" apRil ", "2024")) == ("April", 2024)

    # Test that the function raises a TypeError for an invalid month
    with pytest.raises(TypeError):
        reader.validate_version(("March", 2024))

    # Test that the function raises a TypeError for an invalid year
    with pytest.raises(TypeError, match=r"Invalid year\. Must be an integer"):
        reader.validate_version(("April", "twenty twenty four"))

    # Test that the function raises a TypeError for an invalid version format
    with pytest.raises(TypeError):
        reader.validate_version("April 2024")


@patch("imf_reader.weo.reader.datetime")
def test_gen_latest_version(mock_datetime):
    """Test for gen_latest_version function."""

    # Mock the current date to be in April
    mock_datetime.now.return_value = datetime(2024, 4, 1)
    assert reader.gen_latest_version() == ("April", 2024)

    # Mock the current date to be in October
    mock_datetime.now.return_value = datetime(2024, 10, 1)
    assert reader.gen_latest_version() == ("October", 2024)

    # Mock the current date to be in January
    mock_datetime.now.return_value = datetime(2024, 1, 1)
    assert reader.gen_latest_version() == ("October", 2023)


def test_roll_back_version():
    """Test for roll_back_version function."""

    # Test that the function correctly rolls back from April to the previous October
    assert reader.roll_back_version(("April", 2024)) == ("October", 2023)

    # Test that the function correctly rolls back from October to April of the same year
    assert reader.roll_back_version(("October", 2024)) == ("April", 2024)

    # Test that the function raises a ValueError for an invalid month
    with pytest.raises(ValueError):
        reader.roll_back_version(("March", 2024))


@patch("imf_reader.weo.reader.get_weo_versions")
@patch("imf_reader.weo.reader.get_weo_data")
def test_fetch_data(mock_get_weo_data, mock_get_weo_versions):
    """Test for fetch_data method."""

    # Mock the get_weo_data function to return a specific DataFrame
    mock_data = pd.DataFrame({"column1": [1, 2, 3], "column2": [4, 5, 6]})
    mock_get_weo_data.return_value = mock_data
    mock_get_weo_versions.return_value = [("October", 2025), ("April", 2025)]

    # Test that the function correctly fetches data when a version is passed
    pd.testing.assert_frame_equal(reader.fetch_data(("April", 2024)), mock_data)
    mock_get_weo_data.assert_called_with(("April", 2024))

    # when no version is passed, check that get_weo_versions is called for latest
    mock_get_weo_data.reset_mock()
    reader.fetch_data()
    mock_get_weo_versions.assert_called()
    mock_get_weo_data.assert_called_with(("October", 2025))


@patch("imf_reader.weo.reader.get_weo_versions")
@patch("imf_reader.weo.reader.get_weo_data")
def test_fetch_data_attribute(mock_get_weo_data, mock_get_weo_versions):
    """Test for fetch_data method attribute."""

    mock_data = pd.DataFrame({"column1": [1, 2, 3], "column2": [4, 5, 6]})
    mock_get_weo_data.return_value = mock_data
    mock_get_weo_versions.return_value = [("April", 2024), ("October", 2023)]

    # when a version is passed, check that the attribute is set
    reader.fetch_data(("April", 2022))
    assert reader.fetch_data.last_version_fetched == ("April", 2022)

    # when no version is passed, check that the attribute is set to latest
    reader.fetch_data()
    assert reader.fetch_data.last_version_fetched == ("April", 2024)


@patch("imf_reader.weo.reader._fetch")
@patch("imf_reader.weo.reader.roll_back_version")
@patch("imf_reader.weo.reader.get_weo_versions")
@patch("imf_reader.weo.reader.get_weo_data")
def test_fetch_data_handles_no_data_error(
    mock_get_weo_data, mock_get_weo_versions, mock_roll_back_version, mock_fetch
):
    """Test for fetch_data method when the API fails and falls back to scraper with rollback"""

    # Mock get_weo_versions to return a specific version list
    mock_get_weo_versions.return_value = [("April", 2024), ("October", 2023)]

    # Mock get_weo_data to raise ValueError (version not in API)
    mock_get_weo_data.side_effect = ValueError("Version not available")

    # Mock the _fetch function to raise a NoDataError for the first call and return a DataFrame for the second call
    mock_fetch.side_effect = [
        NoDataError,
        pd.DataFrame({"column1": [1, 2, 3], "column2": [4, 5, 6]}),
    ]

    # Mock the roll_back_version function to return a specific version
    mock_roll_back_version.return_value = ("October", 2023)

    # Call the fetch_data function without passing a version
    df = reader.fetch_data()

    # Check that get_weo_versions was called to get latest version
    mock_get_weo_versions.assert_called()

    # Check that _fetch was called twice (once for the initial call and once after the NoDataError)
    assert mock_fetch.call_count == 2

    # Check that roll_back_version was called once with the latest version
    mock_roll_back_version.assert_called_once_with(("April", 2024))

    # Check that the DataFrame returned by fetch_data is as expected
    pd.testing.assert_frame_equal(
        df, pd.DataFrame({"column1": [1, 2, 3], "column2": [4, 5, 6]})
    )


@patch("imf_reader.weo.reader.to_api_vocabulary")
@patch("imf_reader.weo.reader.SDMXParser")
@patch.object(SDMXScraper, "scrape")
@patch("imf_reader.weo.reader.get_weo_versions")
@patch("imf_reader.weo.reader.get_weo_data")
def test_fetch_data_rolls_back_on_resolver_no_data_error(
    mock_get_weo_data,
    mock_get_weo_versions,
    mock_scrape,
    mock_parser,
    mock_to_api_vocabulary,
    cache_disabled,
):
    """A genuinely unpublished release -- every candidate URL 404s, so
    ``_resolve_sdmx_url`` raises NoDataError -- must still trigger the rollback to
    the previous version. This is the counterpart to the 403 case (finding 1),
    which must NOT roll back, and guards against that fix over-correcting into
    swallowing every scrape failure as "not a rollback trigger"."""

    mock_get_weo_versions.return_value = [("April", 2024), ("October", 2023)]
    mock_get_weo_data.side_effect = ValueError("Version not available")

    expected = pd.DataFrame({"column1": [1, 2, 3], "column2": [4, 5, 6]})
    mock_to_api_vocabulary.return_value = expected

    # SDMXScraper.scrape is what reader._fetch calls; raising NoDataError on the
    # first (April 2024) call mirrors what _resolve_sdmx_url raises when every
    # candidate 404s. The second call (October 2023, after rollback) succeeds.
    mock_scrape.side_effect = [NoDataError("no data"), object()]

    df = reader.fetch_data(("April", 2024))

    assert mock_scrape.call_count == 2
    mock_scrape.assert_any_call("April", 2024)
    mock_scrape.assert_any_call("October", 2023)
    pd.testing.assert_frame_equal(df, expected)


@patch.object(translate_module, "_fetch_codelist")
@patch.object(SDMXScraper, "scrape")
def test_fetch_wires_scrape_parse_and_translate_together(
    mock_scrape, mock_fetch_codelist, cache_disabled
):
    """Exercises reader._fetch's real body end to end: SDMXScraper.scrape ->
    SDMXParser.parse -> to_api_vocabulary. Every test above either patches
    _fetch wholesale or patches its three steps individually, so none of them
    would catch to_api_vocabulary being dropped from _fetch, or reordered
    ahead of SDMXParser.parse -- only calling the real, undecorated pipeline
    can."""
    zip_bytes = _build_sdmx_zip_bytes(ref_area="111", concept="NGDP", unit="E")
    mock_scrape.return_value = ZipFile(io.BytesIO(zip_bytes))

    codelists = {
        ("IMF.RES", "CL_WEO_COUNTRY"): {"USA": "United States"},
        ("IMF.RES", "CL_WEO_INDICATOR"): {"NGDP": "Gross domestic product"},
        ("IMF", "CL_UNIT"): {"XDC": "Domestic currency"},
    }
    mock_fetch_codelist.side_effect = lambda agency, codelist_id: codelists[
        (agency, codelist_id)
    ]

    df = reader._fetch(("April", 2024))

    assert list(df.columns) == OUTPUT_COLUMNS
    row = df.iloc[0]
    # 111 is the legacy numeric area code for the United States. If
    # to_api_vocabulary were skipped, or ran before SDMXParser.parse instead
    # of after, this would still read "111" (or fail outright), not "USA".
    assert row["REF_AREA_CODE"] == "USA"
    assert row["UNIT_CODE"] == "XDC"
