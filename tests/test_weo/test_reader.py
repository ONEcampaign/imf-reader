import io
import logging
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from unittest.mock import patch
from zipfile import ZipFile

import pandas as pd
import pytest

from imf_reader.config import (
    DataflowDiscoveryError,
    NoDataError,
    VersionNotAvailableError,
)
from imf_reader.weo import reader
from imf_reader.weo import translate as translate_module
from imf_reader.weo.api import OUTPUT_COLUMNS, FlowRef
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
    assert reader.validate_version(("April", 2024)) == ("April", 2024)  # April
    assert reader.validate_version(("October", 2024)) == ("October", 2024)  # October

    assert reader.validate_version((" april ", "2024")) == ("April", 2024)
    assert reader.validate_version(("october", " 2024 ")) == ("October", 2024)
    assert reader.validate_version((" apRil ", "2024")) == ("April", 2024)

    with pytest.raises(TypeError):
        reader.validate_version(("March", 2024))

    with pytest.raises(TypeError, match=r"Invalid year\. Must be an integer"):
        reader.validate_version(("April", "twenty twenty four"))

    with pytest.raises(TypeError):
        reader.validate_version("April 2024")


@patch("imf_reader.weo.reader.datetime")
def test_gen_latest_version(mock_datetime):
    mock_datetime.now.return_value = datetime(2024, 4, 1, tzinfo=UTC)
    assert reader.gen_latest_version() == ("April", 2024)

    mock_datetime.now.return_value = datetime(2024, 10, 1, tzinfo=UTC)
    assert reader.gen_latest_version() == ("October", 2024)

    mock_datetime.now.return_value = datetime(2024, 1, 1, tzinfo=UTC)
    assert reader.gen_latest_version() == ("October", 2023)


@patch("imf_reader.weo.reader.get_weo_versions")
@patch("imf_reader.weo.reader.get_weo_data")
def test_fetch_data(mock_get_weo_data, mock_get_weo_versions):
    mock_data = pd.DataFrame({"column1": [1, 2, 3], "column2": [4, 5, 6]})
    mock_get_weo_data.return_value = mock_data
    mock_get_weo_versions.return_value = [("October", 2025), ("April", 2025)]

    pd.testing.assert_frame_equal(reader.fetch_data(("April", 2024)), mock_data)
    mock_get_weo_data.assert_called_with(("April", 2024))

    mock_get_weo_data.reset_mock()
    reader.fetch_data()
    mock_get_weo_versions.assert_called()
    mock_get_weo_data.assert_called_with(("October", 2025))


@patch("imf_reader.weo.reader.get_weo_versions")
@patch("imf_reader.weo.reader.get_weo_data")
def test_fetch_data_attribute(mock_get_weo_data, mock_get_weo_versions):
    mock_data = pd.DataFrame({"column1": [1, 2, 3], "column2": [4, 5, 6]})
    mock_get_weo_data.return_value = mock_data
    mock_get_weo_versions.return_value = [("April", 2024), ("October", 2023)]

    reader.fetch_data(("April", 2022))
    assert reader.fetch_data.last_version_fetched == ("April", 2022)

    reader.fetch_data()
    assert reader.fetch_data.last_version_fetched == ("April", 2024)


@patch("imf_reader.weo.reader._fetch")
@patch("imf_reader.weo.reader.get_weo_versions")
@patch("imf_reader.weo.reader.get_weo_data")
def test_fetch_data_rolls_back_through_get_weo_versions_when_latest_fails(
    mock_get_weo_data, mock_get_weo_versions, mock_fetch
):
    """When version=None and both the API and the bulk scraper fail for the
    resolved 'latest' version, fetch_data must walk get_weo_versions() --
    an already-published, newest-first list -- rather than guess a previous
    release from the calendar, and land on the next version that works."""

    mock_get_weo_versions.return_value = [("April", 2024), ("October", 2023)]

    mock_get_weo_data.side_effect = VersionNotAvailableError("Version not available")

    mock_fetch.side_effect = [
        NoDataError,
        pd.DataFrame({"column1": [1, 2, 3], "column2": [4, 5, 6]}),
    ]

    df = reader.fetch_data()

    mock_get_weo_versions.assert_called()

    # _fetch is called twice: once for the initial resolved version and once
    # after rolling back to the next entry in get_weo_versions().
    assert mock_fetch.call_count == 2
    mock_fetch.assert_any_call(("April", 2024))
    mock_fetch.assert_any_call(("October", 2023))

    # The rolled-back version is what fetch_data actually served.
    assert reader.fetch_data.last_version_fetched == ("October", 2023)

    pd.testing.assert_frame_equal(
        df, pd.DataFrame({"column1": [1, 2, 3], "column2": [4, 5, 6]})
    )


@patch.object(SDMXScraper, "scrape")
@patch("imf_reader.weo.reader.get_weo_data")
def test_fetch_data_explicit_version_raises_instead_of_rolling_back(
    mock_get_weo_data, mock_scrape, cache_disabled
):
    """An explicit version that neither the API nor the bulk scraper can serve
    raises rather than falling back to a different release under the
    caller's requested label. Roll-back is only for an unresolved
    version=None request."""

    mock_get_weo_data.side_effect = VersionNotAvailableError("Version not available")
    mock_scrape.side_effect = NoDataError("no data")

    with pytest.raises(NoDataError):
        reader.fetch_data(("April", 2024))

    mock_scrape.assert_called_once_with("April", 2024)


@patch("imf_reader.weo.reader.get_weo_data")
def test_fetch_data_explicit_version_propagates_non_version_error(mock_get_weo_data):
    """Any API-path error other than VersionNotAvailableError -- a pandas
    parse error, an _align_schema bug, a codelist problem -- surfaces as-is,
    rather than being mistaken for 'this version isn't served' and rerouted
    to the bulk scraper or another release."""

    mock_get_weo_data.side_effect = ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        reader.fetch_data(("October", 2025))


@patch("imf_reader.weo.reader._fetch")
@patch("imf_reader.weo.reader.get_weo_data")
def test_fetch_data_explicit_bulk_only_version_reaches_fetch(
    mock_get_weo_data, mock_fetch
):
    """April 2020 predates the API; a VersionNotAvailableError from
    get_weo_data must still fall through to the bulk scraper path."""

    mock_get_weo_data.side_effect = VersionNotAvailableError("not in API")
    expected = pd.DataFrame({"column1": [1], "column2": [2]})
    mock_fetch.return_value = expected

    df = reader.fetch_data(("April", 2020))

    mock_fetch.assert_called_once_with(("April", 2020))
    pd.testing.assert_frame_equal(df, expected)


@patch("imf_reader.weo.reader._fetch")
@patch("imf_reader.weo.reader.get_weo_data")
def test_fetch_data_explicit_version_falls_back_when_catalogue_unusable(
    mock_get_weo_data, mock_fetch
):
    """An unusable dataflow catalogue means the API cannot serve *any*
    version, but for an explicit version the bulk archive is still the
    correct source: it returns the requested release under its own correct
    label, so DataflowDiscoveryError must fall back exactly like
    VersionNotAvailableError does."""

    mock_get_weo_data.side_effect = DataflowDiscoveryError("catalogue unusable")
    expected = pd.DataFrame({"column1": [1], "column2": [2]})
    mock_fetch.return_value = expected

    df = reader.fetch_data(("April", 2020))

    mock_fetch.assert_called_once_with(("April", 2020))
    pd.testing.assert_frame_equal(df, expected)


@patch("imf_reader.weo.reader._fetch")
@patch("imf_reader.weo.reader.get_weo_data")
def test_fetch_data_explicit_version_fallback_logs_a_warning(
    mock_get_weo_data, mock_fetch, caplog, monkeypatch
):
    """The catalogue-unusable fallback keeps the caller's label correct, so its
    return value alone shows nothing. It must still carry a signal above INFO:
    a broken catalogue schema would otherwise reroute every explicit-version
    call in a process with nothing to show for it."""

    mock_get_weo_data.side_effect = DataflowDiscoveryError("catalogue unusable")
    mock_fetch.return_value = pd.DataFrame({"column1": [1], "column2": [2]})

    # config.py turns propagation off on this logger so a caller configuring
    # the root logger does not get duplicate lines. caplog attaches to the
    # root, so it is turned back on for the duration of this test. Capturing
    # by logger name alone works only on pytest 9.1 and up.
    imf_logger = logging.getLogger("imf_reader.config")
    monkeypatch.setattr(imf_logger, "propagate", True)

    with caplog.at_level(logging.WARNING, logger="imf_reader.config"):
        reader.fetch_data(("April", 2020))

    # Compared as a set of distinct messages, because pytest 9.1 records the
    # same line twice (once directly, once through the propagation enabled
    # above) while 9.0 records it once. What this pins is that the fallback
    # emits one warning, not how many handlers observed it.
    messages = {r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING}
    assert len(messages) == 1
    message = messages.pop()
    assert "April" in message
    assert "2020" in message
    assert "DataflowDiscoveryError" in message
    assert "catalogue unusable" in message


@patch("imf_reader.weo.reader.get_weo_versions")
def test_fetch_data_none_propagates_discovery_error_instead_of_archive_fallback(
    mock_get_weo_versions,
):
    """An unresolved version=None request fails loudly when the catalogue is
    unusable: get_weo_versions() (which fetch_data consults first to resolve
    'latest') raises the same error, instead of reaching the bulk-archive
    fallback and silently serving an archive release mislabelled as
    latest."""

    mock_get_weo_versions.side_effect = DataflowDiscoveryError("catalogue unusable")

    with pytest.raises(DataflowDiscoveryError):
        reader.fetch_data()


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


@patch("imf_reader.weo.reader.get_series_metadata")
@patch("imf_reader.weo.reader._resolve_flow_ref")
def test_fetch_series_metadata_returns_data_and_sets_last_version_fetched(
    mock_resolve_flow_ref, mock_get_series_metadata
):
    mock_resolve_flow_ref.return_value = (("October", 2025), FlowRef("WEO", "9.0.0"))
    mock_data = pd.DataFrame({"REF_AREA_CODE": ["USA"], "CONCEPT_CODE": ["NGDP_RPCH"]})
    mock_get_series_metadata.return_value = mock_data

    df = reader.fetch_series_metadata(("October", 2025))

    pd.testing.assert_frame_equal(df, mock_data)
    mock_get_series_metadata.assert_called_once_with(("October", 2025))
    assert reader.fetch_series_metadata.last_version_fetched == ("October", 2025)


@patch.object(SDMXScraper, "scrape")
@patch("imf_reader.weo.reader._fetch")
@patch("imf_reader.weo.reader._resolve_flow_ref")
def test_fetch_series_metadata_unavailable_version_raises_without_bulk_fallback(
    mock_resolve_flow_ref, mock_fetch, mock_scrape
):
    """Anti-regression for the silent-boundary rule: series metadata has no
    bulk-archive fallback, so April 2020 -- unservable by the API -- must
    raise VersionNotAvailableError rather than quietly falling through to the
    SDMX scraper the way fetch_data's roll-back would."""
    mock_resolve_flow_ref.side_effect = VersionNotAvailableError("not available")

    with pytest.raises(VersionNotAvailableError):
        reader.fetch_series_metadata(("April", 2020))

    mock_scrape.assert_not_called()
    mock_fetch.assert_not_called()


@patch("imf_reader.weo.reader.get_weo_versions")
@patch("imf_reader.weo.reader.get_series_metadata")
@patch("imf_reader.weo.reader._resolve_flow_ref")
def test_fetch_series_metadata_does_not_roll_back_when_resolved_latest_fails(
    mock_resolve_flow_ref, mock_get_series_metadata, mock_get_weo_versions
):
    """fetch_series_metadata raises once when the version resolved as
    'latest' cannot be served, unlike fetch_data, which rolls back to an
    older release: there is no bulk archive to land on here, so a failure
    must raise rather than walking get_weo_versions() for a second candidate
    to try."""
    mock_resolve_flow_ref.return_value = (("October", 2025), FlowRef("WEO", "9.0.0"))
    mock_get_series_metadata.side_effect = VersionNotAvailableError("not available")

    with pytest.raises(VersionNotAvailableError):
        reader.fetch_series_metadata()

    mock_resolve_flow_ref.assert_called_once()
    mock_get_series_metadata.assert_called_once()
    mock_get_weo_versions.assert_not_called()


def test_fetch_series_metadata_invalid_version_raises_no_data_error():
    """Mirrors fetch_data's own validate_version handling: a malformed
    version tuple is a caller error, wrapped into NoDataError rather than
    surfacing validate_version's bare TypeError."""
    with pytest.raises(NoDataError):
        reader.fetch_series_metadata(("March", 2024))
