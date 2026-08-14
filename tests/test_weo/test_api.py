"""Tests for weo api module."""

from typing import ClassVar
from unittest.mock import patch

import pandas as pd
import pytest

from imf_reader.config import VersionNotAvailableError
from imf_reader.weo import api
from imf_reader.weo.api import FlowRef
from imf_reader.weo.scraper import KNOWN_CORRUPT_RELEASES, SDMX_RELEASES


class _MockResponse:
    """Minimal stand-in for requests.Response: only .json() and .text are used."""

    def __init__(self, *, json_data=None, text=""):
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data


def _discovery_response(flows: list[tuple[str, str]]) -> _MockResponse:
    """Build a mock ``detail=allstubs`` dataflow-listing response.

    Args:
        flows: (dataflow_id, version) pairs to include.
    """
    return _MockResponse(
        json_data={
            "data": {
                "dataflows": [
                    {"id": flow_id, "version": version} for flow_id, version in flows
                ]
            }
        }
    )


def _probe_response(publication_date: str) -> _MockResponse:
    """Build a mock single-row PUBLICATION_DATE probe response."""
    return _MockResponse(
        text=(
            "COUNTRY,INDICATOR,PUBLICATION_DATE\n"
            f"USA,NGDP_RPCH,{publication_date}\n"
        )
    )


class TestGetWeoVersions:
    """get_weo_versions() must union the API mapping with the SDMX archive."""

    @patch("imf_reader.weo.api._fetch_flow_mapping")
    def test_union_includes_sdmx_only_releases(self, mock_mapping):
        """April 2020 is only in the SDMX archive; the API mapping alone
        (October 2025, April 2025) must not be all that comes back."""
        mock_mapping.return_value = {
            ("October", 2025): FlowRef("WEO", "9.0.0"),
            ("April", 2025): FlowRef("WEO", "6.0.0"),
        }

        versions = api.get_weo_versions()

        assert ("April", 2020) in versions
        assert ("October", 2025) in versions

    @patch("imf_reader.weo.api._fetch_flow_mapping")
    def test_excludes_known_corrupt_releases(self, mock_mapping):
        mock_mapping.return_value = {
            ("October", 2025): FlowRef("WEO", "9.0.0"),
            ("April", 2025): FlowRef("WEO", "6.0.0"),
        }

        versions = api.get_weo_versions()

        assert ("April", 2021) not in versions
        assert ("October", 2023) not in versions

    @patch("imf_reader.weo.api._fetch_flow_mapping")
    def test_sorted_newest_first(self, mock_mapping):
        mock_mapping.return_value = {
            ("October", 2025): FlowRef("WEO", "9.0.0"),
            ("April", 2025): FlowRef("WEO", "6.0.0"),
        }

        versions = api.get_weo_versions()

        assert versions == sorted(
            versions, key=lambda v: (v[1], 0 if v[0] == "April" else 1), reverse=True
        )
        assert versions[0] == ("October", 2025)

    @patch("imf_reader.weo.api._fetch_flow_mapping")
    def test_count_is_api_and_sdmx_minus_corrupt_and_overlap(self, mock_mapping):
        """11 fetchable SDMX releases (13 minus the 2 corrupt) union 2 API
        versions, minus the April 2025 overlap between them = 12."""
        mock_mapping.return_value = {
            ("October", 2025): FlowRef("WEO", "9.0.0"),
            ("April", 2025): FlowRef("WEO", "6.0.0"),
        }

        versions = api.get_weo_versions()

        assert len(versions) == 12
        assert len(SDMX_RELEASES) == 13
        assert len(KNOWN_CORRUPT_RELEASES) == 2

    @patch("imf_reader.weo.api._fetch_flow_mapping")
    def test_propagates_api_failure_instead_of_degrading(self, mock_mapping):
        """If the API mapping is unreachable, the whole call must fail rather than
        silently falling back to the SDMX-only list."""
        mock_mapping.side_effect = ConnectionError("api.imf.org unreachable")

        with pytest.raises(ConnectionError, match=r"api\.imf\.org unreachable"):
            api.get_weo_versions()


class TestGetWeoDataVersionResolution:
    """get_weo_data(version=None) must resolve 'latest' against the API mapping
    alone, never through the SDMX-inclusive union get_weo_versions() returns."""

    @patch("imf_reader.weo.api._get_weo_data_cached")
    @patch("imf_reader.weo.api._fetch_flow_mapping")
    def test_none_resolves_within_api_mapping_only(
        self, mock_mapping, mock_cached_fetch
    ):
        # April 2025 is the only API version on offer. October 2024 and every
        # other SDMX-only release is newer-looking to nothing here, but if the
        # union ever leaked in, an SDMX release the API cannot serve could be
        # picked as "latest" instead.
        mock_mapping.return_value = {("April", 2025): FlowRef("WEO", "6.0.0")}
        mock_cached_fetch.return_value = "sentinel"

        api.get_weo_data(version=None)

        # get_weo_data resolves the FlowRef and passes it explicitly so
        # @dataframe_cache's key covers (version, ref), not version alone --
        # otherwise a flow remapping is invisible to the cache key and a
        # stale entry is served forever. See
        # TestGetWeoDataCachedKeyIncludesFlowRef below.
        mock_cached_fetch.assert_called_once_with(
            ("April", 2025), FlowRef("WEO", "6.0.0")
        )


class TestFetchFlowMapping:
    """_fetch_flow_mapping discovers WEO/vintage flows via ``detail=allstubs``
    and labels each by probing PUBLICATION_DATE -- never the lastUpdatedAt
    structure annotation, which is inverted on live flows."""

    def test_maps_bare_and_vintage_flows_from_probes(self, cache_disabled):
        discovery = _discovery_response(
            [("WEO", "9.0.0"), ("WEO_2025_OCT_VINTAGE", "1.0.0")]
        )
        probes = {
            "WEO/9.0.0": _probe_response("2026-04-14T13:00:00Z"),
            "WEO_2025_OCT_VINTAGE/1.0.0": _probe_response("2025-10-14T13:00:00Z"),
        }

        def fake_get(url, **kwargs):
            if "structure/dataflow" in url:
                return discovery
            for flow_key, resp in probes.items():
                if f"/{flow_key}/" in url:
                    return resp
            raise AssertionError(f"Unexpected probe URL: {url}")

        with patch("imf_reader.weo.api.make_get_request", side_effect=fake_get):
            mapping = api._fetch_flow_mapping()

        assert mapping == {
            ("April", 2026): FlowRef("WEO", "9.0.0"),
            ("October", 2025): FlowRef("WEO_2025_OCT_VINTAGE", "1.0.0"),
        }

    def test_labels_by_publication_date_not_last_updated_at(self, cache_disabled):
        """Regression test for the reported bug: a flow's ``lastUpdatedAt``
        annotation (2025-10-08, if it were read at all) is inverted relative
        to its real PUBLICATION_DATE (2026-04-14). The mapping must land on
        the label the probe reports; the annotation-reading code path is
        deleted entirely, so this response does not even carry one."""
        discovery = _discovery_response([("WEO", "9.0.0")])
        probe = _probe_response("2026-04-14T13:00:00Z")

        def fake_get(url, **kwargs):
            return discovery if "structure/dataflow" in url else probe

        with patch("imf_reader.weo.api.make_get_request", side_effect=fake_get):
            mapping = api._fetch_flow_mapping()

        assert mapping == {("April", 2026): FlowRef("WEO", "9.0.0")}

    def test_vintage_probe_failure_falls_back_to_id_derived_label(
        self, cache_disabled
    ):
        discovery = _discovery_response([("WEO_2025_OCT_VINTAGE", "1.0.0")])

        def fake_get(url, **kwargs):
            if "structure/dataflow" in url:
                return discovery
            raise ConnectionError("probe unreachable")

        with patch("imf_reader.weo.api.make_get_request", side_effect=fake_get):
            mapping = api._fetch_flow_mapping()

        assert mapping == {
            ("October", 2025): FlowRef("WEO_2025_OCT_VINTAGE", "1.0.0")
        }

    def test_vintage_unparseable_month_and_failed_probe_is_skipped(
        self, cache_disabled
    ):
        """A vintage id whose month code this package doesn't recognise
        (structurally valid, semantically useless) combined with a failed
        probe leaves the flow with no usable label at all -- it must be
        skipped with a warning, not crash the whole mapping, and other flows
        must still come through."""
        discovery = _discovery_response(
            [("WEO", "9.0.0"), ("WEO_2025_JUL_VINTAGE", "1.0.0")]
        )
        good_probe = _probe_response("2026-04-14T13:00:00Z")

        def fake_get(url, **kwargs):
            if "structure/dataflow" in url:
                return discovery
            if "/WEO/9.0.0/" in url:
                return good_probe
            raise ConnectionError("probe unreachable")

        with (
            patch("imf_reader.weo.api.make_get_request", side_effect=fake_get),
            patch("imf_reader.weo.api.logger.warning") as mock_warning,
        ):
            mapping = api._fetch_flow_mapping()

        assert mapping == {("April", 2026): FlowRef("WEO", "9.0.0")}
        assert any(
            "WEO_2025_JUL_VINTAGE" in str(call.args)
            for call in mock_warning.call_args_list
        )

    def test_bare_weo_probe_failure_raises(self, cache_disabled):
        """A bare WEO flow determines 'latest'; a probe failure on one must
        raise, not be silently skipped -- skipping it would let get_weo_data
        resolve 'latest' to an older release with no signal, the exact class
        of bug this module exists to fix."""
        discovery = _discovery_response([("WEO", "9.0.0")])

        def fake_get(url, **kwargs):
            if "structure/dataflow" in url:
                return discovery
            raise ConnectionError("api.imf.org unreachable")

        with (
            patch("imf_reader.weo.api.make_get_request", side_effect=fake_get),
            pytest.raises(ConnectionError),
        ):
            api._fetch_flow_mapping()

    def test_bare_flow_wins_over_vintage_on_collision(self, cache_disabled):
        """If a vintage flow ever duplicates a bare flow's (month, year), the
        bare flow wins -- old bare versions stay live and serving data, so
        preferring them keeps behaviour stable as vintages accumulate."""
        discovery = _discovery_response(
            [("WEO_2025_OCT_VINTAGE", "1.0.0"), ("WEO", "9.0.0")]
        )
        probe = _probe_response("2025-10-14T13:00:00Z")  # both claim October 2025

        def fake_get(url, **kwargs):
            return discovery if "structure/dataflow" in url else probe

        with patch("imf_reader.weo.api.make_get_request", side_effect=fake_get):
            mapping = api._fetch_flow_mapping()

        assert mapping == {("October", 2025): FlowRef("WEO", "9.0.0")}


class TestGetWeoDataCached:
    """_get_weo_data_cached must build the URL from the resolved FlowRef --
    including the vintage dataflow id -- it takes ``ref`` as a required
    argument. (Version-not-available handling for a missing version lives in
    the public ``get_weo_data`` wrapper -- see
    TestGetWeoDataCachedKeyIncludesFlowRef.test_get_weo_data_raises_for_unavailable_explicit_version
    -- since a required ``ref`` means this inner function has no mapping of
    its own left to check against.)"""

    @patch("imf_reader.weo.api._align_schema")
    @patch("imf_reader.weo.api.make_get_request")
    def test_builds_vintage_url(
        self, mock_get_request, mock_align_schema, cache_disabled
    ):
        mock_get_request.return_value = _MockResponse(text="COUNTRY\nUSA\n")
        mock_align_schema.return_value = "sentinel"

        api._get_weo_data_cached(
            ("October", 2025), FlowRef("WEO_2025_OCT_VINTAGE", "1.0.0")
        )

        called_url = mock_get_request.call_args[0][0]
        assert called_url == (
            "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES/"
            "WEO_2025_OCT_VINTAGE/1.0.0/*"
        )


class TestGetWeoDataCachedKeyIncludesFlowRef:
    """Regression test for a reported bug: fetch_data(("October", 2025))
    returned stale, wrongly-labelled data because a parquet cache entry
    written under the old (month, year)-only key looked identical after the
    mapping was fixed to resolve that label to a different FlowRef. The
    cache key must depend on the resolved FlowRef too, so a remapping is a
    cache miss instead of silently serving the old entry."""

    @patch("imf_reader.weo.api._align_schema")
    @patch("imf_reader.weo.api.make_get_request")
    def test_same_version_different_flowref_is_a_cache_miss(
        self, mock_get_request, mock_align_schema, tmp_cache_root
    ):
        mock_get_request.return_value = _MockResponse(text="COUNTRY\nUSA\n")
        mock_align_schema.side_effect = [
            pd.DataFrame({"sentinel": ["old-mapping"]}),
            pd.DataFrame({"sentinel": ["new-mapping"]}),
        ]

        old_ref = FlowRef("WEO", "6.0.0")
        new_ref = FlowRef("WEO_2025_OCT_VINTAGE", "1.0.0")

        first = api._get_weo_data_cached(("October", 2025), old_ref)
        second = api._get_weo_data_cached(("October", 2025), new_ref)

        assert first["sentinel"].iloc[0] == "old-mapping"
        assert second["sentinel"].iloc[0] == "new-mapping"
        assert mock_get_request.call_count == 2
        assert mock_align_schema.call_count == 2

    @patch("imf_reader.weo.api._align_schema")
    @patch("imf_reader.weo.api.make_get_request")
    def test_same_version_same_flowref_is_a_cache_hit(
        self, mock_get_request, mock_align_schema, tmp_cache_root
    ):
        mock_get_request.return_value = _MockResponse(text="COUNTRY\nUSA\n")
        mock_align_schema.return_value = pd.DataFrame({"sentinel": ["cached"]})

        ref = FlowRef("WEO", "9.0.0")
        api._get_weo_data_cached(("April", 2026), ref)
        api._get_weo_data_cached(("April", 2026), ref)

        assert mock_get_request.call_count == 1

    @patch("imf_reader.weo.api._get_weo_data_cached")
    @patch("imf_reader.weo.api._fetch_flow_mapping")
    def test_get_weo_data_resolves_ref_before_calling_cached_fetch(
        self, mock_mapping, mock_cached_fetch
    ):
        """get_weo_data must resolve the FlowRef for an *explicit* version
        too (not only version=None), so an explicit fetch_data(("October",
        2025)) also lands under a cache key that includes the ref."""
        ref = FlowRef("WEO_2025_OCT_VINTAGE", "1.0.0")
        mock_mapping.return_value = {("October", 2025): ref}
        mock_cached_fetch.return_value = "sentinel"

        api.get_weo_data(("October", 2025))

        mock_cached_fetch.assert_called_once_with(("October", 2025), ref)

    @patch("imf_reader.weo.api._fetch_flow_mapping")
    def test_get_weo_data_raises_for_unavailable_explicit_version(
        self, mock_mapping
    ):
        mock_mapping.return_value = {("April", 2025): FlowRef("WEO", "6.0.0")}

        with pytest.raises(VersionNotAvailableError):
            api.get_weo_data(("October", 2025))


class TestFetchSeriesMetadata:
    """_fetch_series_metadata fetches the series-attributes sidecar and
    returns only the columns this package uses."""

    _SIDECAR_COLUMNS: ClassVar[list[str]] = [
        "COUNTRY",
        "INDICATOR",
        "FREQUENCY",
        "LATEST_ACTUAL_ANNUAL_DATA",
        "METHODOLOGY_NOTES",
        "COUNTRY_UPDATE_DATE",
    ]

    def test_requests_the_series_sidecar_url(self, cache_disabled):
        response = _MockResponse(
            text=",".join(self._SIDECAR_COLUMNS) + "\n"
        )

        with patch(
            "imf_reader.weo.api.make_get_request", return_value=response
        ) as mock_get_request:
            api._fetch_series_metadata(FlowRef("WEO_2025_OCT_VINTAGE", "1.0.0"))

        called_url = mock_get_request.call_args[0][0]
        assert called_url == (
            "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES/"
            "WEO_2025_OCT_VINTAGE/1.0.0/*"
            "?attributes=series&firstNObservations=1"
        )
        assert mock_get_request.call_args.kwargs["headers"] == {
            "Accept": "text/csv"
        }

    def test_returns_only_the_documented_columns(self, cache_disabled):
        response = _MockResponse(
            text=(
                ",".join([*self._SIDECAR_COLUMNS, "VALUATION", "SERIES_NAME"])
                + "\n"
                "USA,NGDP_RPCH,A,2024,a note,9/19/2025,volume,GDP growth\n"
            )
        )

        with patch("imf_reader.weo.api.make_get_request", return_value=response):
            meta = api._fetch_series_metadata(FlowRef("WEO", "9.0.0"))

        assert list(meta.columns) == self._SIDECAR_COLUMNS


def _minimal_api_frame(rows: list[dict]) -> pd.DataFrame:
    """A minimal main-fetch frame: just enough columns for _align_schema to
    run (COUNTRY/INDICATOR/FREQUENCY drive the metadata join; the rest are
    filled with harmless defaults so each test only spells out what it needs).
    """
    defaults = {
        "UNIT": "XDC",
        "SCALE": 0,
        "FREQUENCY": "A",
        "TIME_PERIOD": 2024,
        "OBS_VALUE": 1.0,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def _sidecar_frame(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "FREQUENCY": "A",
        "LATEST_ACTUAL_ANNUAL_DATA": pd.NA,
        "METHODOLOGY_NOTES": pd.NA,
        "COUNTRY_UPDATE_DATE": pd.NA,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


class TestAlignSchemaMetadataJoin:
    """_align_schema left-joins the series metadata sidecar onto the main
    frame before the REF_AREA_CODE/CONCEPT_CODE rename, and degrades to
    null metadata columns (never raising) on any sidecar problem."""

    @pytest.fixture(autouse=True)
    def _patch_codelists(self, monkeypatch):
        # Not under test here; label columns are irrelevant to the metadata
        # join and an empty mapping keeps these tests off the network.
        monkeypatch.setattr(api, "_fetch_codelist", lambda agency, codelist_id: {})

    def test_populates_metadata_columns_from_sidecar(self, monkeypatch):
        df = _minimal_api_frame([{"COUNTRY": "USA", "INDICATOR": "NGDP_RPCH"}])
        meta = _sidecar_frame(
            [
                {
                    "COUNTRY": "USA",
                    "INDICATOR": "NGDP_RPCH",
                    "LATEST_ACTUAL_ANNUAL_DATA": "2024",
                    "METHODOLOGY_NOTES": "a note",
                    "COUNTRY_UPDATE_DATE": "9/19/2025",
                }
            ]
        )
        monkeypatch.setattr(api, "_fetch_series_metadata", lambda ref: meta)

        result = api._align_schema(df, FlowRef("WEO", "9.0.0"))
        row = result.iloc[0]

        assert row["LASTACTUALDATE"] == 2024
        assert row["NOTES"] == "a note"
        assert row["COUNTRY_UPDATE_DATE"] == pd.Timestamp("2025-09-19")
        assert result["LASTACTUALDATE"].dtype == "Int64"
        assert result["NOTES"].dtype == "string"
        assert result["COUNTRY_UPDATE_DATE"].dtype == "datetime64[us]"

    @pytest.mark.parametrize(
        "raw, expected_year",
        [
            ("FY2023/24", 2023),
            ("2024", 2024),
            ("garbage", None),
        ],
    )
    def test_last_actual_annual_data_parsing(self, monkeypatch, raw, expected_year):
        df = _minimal_api_frame([{"COUNTRY": "USA", "INDICATOR": "NGDP_RPCH"}])
        meta = _sidecar_frame(
            [
                {
                    "COUNTRY": "USA",
                    "INDICATOR": "NGDP_RPCH",
                    "LATEST_ACTUAL_ANNUAL_DATA": raw,
                }
            ]
        )
        monkeypatch.setattr(api, "_fetch_series_metadata", lambda ref: meta)

        result = api._align_schema(df, FlowRef("WEO", "9.0.0"))

        assert result["LASTACTUALDATE"].dtype == "Int64"
        value = result.iloc[0]["LASTACTUALDATE"]
        if expected_year is None:
            assert pd.isna(value)
        else:
            assert value == expected_year

    def test_sidecar_failure_degrades_to_null_columns(self, monkeypatch):
        df = _minimal_api_frame([{"COUNTRY": "USA", "INDICATOR": "NGDP_RPCH"}])

        def _raise(ref):
            raise ConnectionError("sidecar unreachable")

        monkeypatch.setattr(api, "_fetch_series_metadata", _raise)

        with patch("imf_reader.weo.api.logger.warning") as mock_warning:
            result = api._align_schema(df, FlowRef("WEO", "9.0.0"))

        assert len(result) == 1
        assert pd.isna(result.iloc[0]["LASTACTUALDATE"])
        assert pd.isna(result.iloc[0]["NOTES"])
        assert pd.isna(result.iloc[0]["COUNTRY_UPDATE_DATE"])
        assert result["LASTACTUALDATE"].dtype == "Int64"
        assert result["NOTES"].dtype == "string"
        assert result["COUNTRY_UPDATE_DATE"].dtype == "datetime64[us]"
        assert mock_warning.called

    def test_duplicated_sidecar_key_drops_sidecar_entirely(self, monkeypatch):
        df = _minimal_api_frame(
            [
                {"COUNTRY": "USA", "INDICATOR": "NGDP_RPCH"},
                {"COUNTRY": "BEL", "INDICATOR": "NGDP_RPCH"},
            ]
        )
        meta = _sidecar_frame(
            [
                {
                    "COUNTRY": "USA",
                    "INDICATOR": "NGDP_RPCH",
                    "LATEST_ACTUAL_ANNUAL_DATA": "2024",
                },
                {
                    "COUNTRY": "USA",
                    "INDICATOR": "NGDP_RPCH",
                    "LATEST_ACTUAL_ANNUAL_DATA": "2023",
                },
            ]
        )
        monkeypatch.setattr(api, "_fetch_series_metadata", lambda ref: meta)

        with patch("imf_reader.weo.api.logger.warning") as mock_warning:
            result = api._align_schema(df, FlowRef("WEO", "9.0.0"))

        # Row count unchanged: the sidecar was dropped, not merged and fanned out.
        assert len(result) == 2
        assert result["LASTACTUALDATE"].isna().all()
        assert mock_warning.called

    def test_sidecar_column_collision_drops_main_frame_copy(self, monkeypatch):
        """Some dataflow versions already carry one of the sidecar's own
        column names in the main CSV (WEO 6.0.0 carries
        LATEST_ACTUAL_ANNUAL_DATA, WEO 9.0.0 carries COUNTRY_UPDATE_DATE).
        The join must drop that copy before merging rather than let pandas
        suffix both as _x/_y, and the sidecar's value must be the one that
        survives -- see _join_series_metadata's docstring."""
        df = _minimal_api_frame(
            [
                {
                    "COUNTRY": "USA",
                    "INDICATOR": "NGDP_RPCH",
                    # Stale value already on the main frame -- must lose to
                    # the sidecar's, not merge into a suffixed column.
                    "COUNTRY_UPDATE_DATE": "1/1/2000",
                }
            ]
        )
        meta = _sidecar_frame(
            [
                {
                    "COUNTRY": "USA",
                    "INDICATOR": "NGDP_RPCH",
                    "COUNTRY_UPDATE_DATE": "9/19/2025",
                }
            ]
        )
        monkeypatch.setattr(api, "_fetch_series_metadata", lambda ref: meta)

        result = api._align_schema(df, FlowRef("WEO", "9.0.0"))

        assert not any("_x" in c or "_y" in c for c in result.columns)
        assert "COUNTRY_UPDATE_DATE" in result.columns
        assert result.iloc[0]["COUNTRY_UPDATE_DATE"] == pd.Timestamp("2025-09-19")

    def test_row_count_invariant_across_merge(self, monkeypatch):
        df = _minimal_api_frame(
            [
                {"COUNTRY": "USA", "INDICATOR": "NGDP_RPCH"},
                {"COUNTRY": "BEL", "INDICATOR": "NGDP_RPCH"},
            ]
        )
        meta = _sidecar_frame(
            [
                {
                    "COUNTRY": "USA",
                    "INDICATOR": "NGDP_RPCH",
                    "LATEST_ACTUAL_ANNUAL_DATA": "2024",
                }
            ]
        )
        monkeypatch.setattr(api, "_fetch_series_metadata", lambda ref: meta)

        result = api._align_schema(df, FlowRef("WEO", "9.0.0"))

        assert len(result) == 2


class TestOutputColumnsAppended:
    """COUNTRY_UPDATE_DATE must be appended, never inserted: positional
    access on the first 15 columns is live in the wild."""

    def test_country_update_date_appended_first_15_unchanged(self):
        assert api.OUTPUT_COLUMNS[-1] == "COUNTRY_UPDATE_DATE"
        assert api.OUTPUT_COLUMNS[:15] == [
            "UNIT_CODE",
            "CONCEPT_CODE",
            "REF_AREA_CODE",
            "REF_AREA_IMF_CODE",
            "FREQ_CODE",
            "LASTACTUALDATE",
            "SCALE_CODE",
            "NOTES",
            "TIME_PERIOD",
            "OBS_VALUE",
            "UNIT_LABEL",
            "CONCEPT_LABEL",
            "REF_AREA_LABEL",
            "FREQ_LABEL",
            "SCALE_LABEL",
        ]
        assert len(api.OUTPUT_COLUMNS) == 16


class TestFetchCodelistWarnsOnEmpty:
    """An empty or renamed codelist must not fail silently -- every label
    column mapping through it becomes <NA> on both the API and bulk paths,
    so the warning is the only signal an operator gets that a codelist
    stopped resolving."""

    def test_warns_and_returns_empty_on_no_codelists(self, cache_disabled):
        response = _MockResponse(json_data={"data": {"codelists": []}})

        with (
            patch("imf_reader.weo.api.make_get_request", return_value=response),
            patch("imf_reader.weo.api.logger.warning") as mock_warning,
        ):
            result = api._fetch_codelist("IMF.RES", "CL_WEO_COUNTRY")

        assert result == {}
        assert mock_warning.called
        warned_args = mock_warning.call_args.args
        assert "IMF.RES" in warned_args
        assert "CL_WEO_COUNTRY" in warned_args
