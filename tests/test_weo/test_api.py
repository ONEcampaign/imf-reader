"""Tests for weo api module."""

from typing import ClassVar
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from imf_reader.config import DataflowDiscoveryError, VersionNotAvailableError
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
        text=(f"COUNTRY,INDICATOR,PUBLICATION_DATE\nUSA,NGDP_RPCH,{publication_date}\n")
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

    @patch("imf_reader.weo.api._join_series_metadata")
    @patch("imf_reader.weo.api._get_weo_data_cached")
    @patch("imf_reader.weo.api._fetch_flow_mapping")
    def test_none_resolves_within_api_mapping_only(
        self, mock_mapping, mock_cached_fetch, mock_join_metadata
    ):
        # April 2025 is the only API version on offer. October 2024 and every
        # other SDMX-only release is newer-looking to nothing here, but if the
        # union ever leaked in, an SDMX release the API cannot serve could be
        # picked as "latest" instead.
        mock_mapping.return_value = {("April", 2025): FlowRef("WEO", "6.0.0")}
        mock_cached_fetch.return_value = pd.DataFrame(columns=api.OUTPUT_COLUMNS)
        mock_join_metadata.side_effect = lambda df, ref: df

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
        """The mapping lands on the label the probe reports, not any
        ``lastUpdatedAt`` annotation: this response carries no such field,
        since the mapping never reads one."""
        discovery = _discovery_response([("WEO", "9.0.0")])
        probe = _probe_response("2026-04-14T13:00:00Z")

        def fake_get(url, **kwargs):
            return discovery if "structure/dataflow" in url else probe

        with patch("imf_reader.weo.api.make_get_request", side_effect=fake_get):
            mapping = api._fetch_flow_mapping()

        assert mapping == {("April", 2026): FlowRef("WEO", "9.0.0")}

    def test_vintage_probe_failure_falls_back_to_id_derived_label(self, cache_disabled):
        # A bare WEO flow is included alongside the vintage so the mapping
        # clears the "must contain a bare WEO flow" floor this module
        # enforces; only the vintage flow's probe is made to fail.
        discovery = _discovery_response(
            [("WEO_2025_OCT_VINTAGE", "1.0.0"), ("WEO", "9.0.0")]
        )
        good_probe = _probe_response("2026-04-14T13:00:00Z")

        def fake_get(url, **kwargs):
            if "structure/dataflow" in url:
                return discovery
            if "/WEO/9.0.0/" in url:
                return good_probe
            raise ConnectionError("probe unreachable")

        with patch("imf_reader.weo.api.make_get_request", side_effect=fake_get):
            mapping = api._fetch_flow_mapping()

        assert mapping == {
            ("October", 2025): FlowRef("WEO_2025_OCT_VINTAGE", "1.0.0"),
            ("April", 2026): FlowRef("WEO", "9.0.0"),
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
        raise. Skipping it would let get_weo_data resolve 'latest' to an
        older release with no signal."""
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

    def test_well_formed_catalogue_with_bare_weo_succeeds(self, cache_disabled):
        """Guard against a false positive: a normal catalogue response that
        does carry a bare WEO flow must not raise."""
        discovery = _discovery_response([("WEO", "9.0.0")])
        probe = _probe_response("2026-04-14T13:00:00Z")

        def fake_get(url, **kwargs):
            return discovery if "structure/dataflow" in url else probe

        with patch("imf_reader.weo.api.make_get_request", side_effect=fake_get):
            mapping = api._fetch_flow_mapping()

        assert mapping == {("April", 2026): FlowRef("WEO", "9.0.0")}

    def test_vintage_only_no_bare_weo_raises_discovery_error(self, cache_disabled):
        """A mapping made only of vintage flows still cannot resolve 'latest',
        so it is treated the same as an empty catalogue: the IMF has always
        published a bare WEO flow, so its absence means the catalogue
        response itself is unusable."""
        discovery = _discovery_response([("WEO_2025_OCT_VINTAGE", "1.0.0")])
        probe = _probe_response("2025-10-14T13:00:00Z")

        def fake_get(url, **kwargs):
            return discovery if "structure/dataflow" in url else probe

        with (
            patch("imf_reader.weo.api.make_get_request", side_effect=fake_get),
            pytest.raises(DataflowDiscoveryError),
        ):
            api._fetch_flow_mapping()

    def test_unusable_catalogue_raises_and_writes_nothing_to_cache(
        self, tmp_cache_root
    ):
        """An empty ``dataflows`` list is a successful 200 with no usable WEO
        flow, not 'no data available' -- it must raise, and the raise must
        happen before @dataframe_cache's write, so the empty result never
        becomes a 1-hour cache entry that would keep serving April 2025 as
        'latest' for the rest of the hour."""
        discovery = _discovery_response([])

        with (
            patch("imf_reader.weo.api.make_get_request", return_value=discovery),
            pytest.raises(DataflowDiscoveryError),
        ):
            api._fetch_flow_mapping()

        cache_dir = tmp_cache_root / "weo_api"
        written = list(cache_dir.iterdir()) if cache_dir.exists() else []
        assert written == []


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
    """The cache key must include the resolved FlowRef alongside the
    (month, year) label: a flow remapping changes the FlowRef a label
    resolves to without changing the label itself, and a key built from the
    label alone would treat the two as identical, silently serving a stale,
    wrongly-labelled parquet entry forever."""

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

    @patch("imf_reader.weo.api._join_series_metadata")
    @patch("imf_reader.weo.api._get_weo_data_cached")
    @patch("imf_reader.weo.api._fetch_flow_mapping")
    def test_get_weo_data_resolves_ref_before_calling_cached_fetch(
        self, mock_mapping, mock_cached_fetch, mock_join_metadata
    ):
        """get_weo_data must resolve the FlowRef for an *explicit* version
        too (not only version=None), so an explicit fetch_data(("October",
        2025)) also lands under a cache key that includes the ref."""
        ref = FlowRef("WEO_2025_OCT_VINTAGE", "1.0.0")
        mock_mapping.return_value = {("October", 2025): ref}
        mock_cached_fetch.return_value = pd.DataFrame(columns=api.OUTPUT_COLUMNS)
        mock_join_metadata.side_effect = lambda df, ref: df

        api.get_weo_data(("October", 2025))

        mock_cached_fetch.assert_called_once_with(("October", 2025), ref)

    @patch("imf_reader.weo.api._fetch_flow_mapping")
    def test_get_weo_data_raises_for_unavailable_explicit_version(self, mock_mapping):
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
        response = _MockResponse(text=",".join(self._SIDECAR_COLUMNS) + "\n")

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
        assert mock_get_request.call_args.kwargs["headers"] == {"Accept": "text/csv"}

    def test_returns_only_the_documented_columns(self, cache_disabled):
        response = _MockResponse(
            text=(
                ",".join([*self._SIDECAR_COLUMNS, "VALUATION", "SERIES_NAME"]) + "\n"
                "USA,NGDP_RPCH,A,2024,a note,9/19/2025,volume,GDP growth\n"
            )
        )

        with patch("imf_reader.weo.api.make_get_request", return_value=response):
            meta = api._fetch_series_metadata(FlowRef("WEO", "9.0.0"))

        assert list(meta.columns) == self._SIDECAR_COLUMNS


def _minimal_api_frame(rows: list[dict]) -> pd.DataFrame:
    """A minimal main-fetch frame: just enough columns for _align_schema to
    run (the rest are filled with harmless defaults so each test only spells
    out what it needs)."""
    defaults = {
        "UNIT": "XDC",
        "SCALE": 0,
        "FREQUENCY": "A",
        "TIME_PERIOD": 2024,
        "OBS_VALUE": 1.0,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def _observation_frame(rows: list[dict]) -> pd.DataFrame:
    """A minimal post-_align_schema frame: REF_AREA_CODE/CONCEPT_CODE/
    FREQ_CODE already renamed, matching what _join_series_metadata's real
    call site (get_weo_data, once _get_weo_data_cached has returned) hands
    it.

    The three join-key columns are cast to "string" (StringDtype,
    na_value=pd.NA), matching what _align_schema itself produces. A
    dict-built frame would otherwise get the platform's default StringDtype
    (na_value=nan), which is unequal to _align_schema's and so would skip
    the exact merge-key coercion _join_series_metadata guards against.
    """
    defaults = {"FREQ_CODE": "A"}
    df = pd.DataFrame([{**defaults, **row} for row in rows])
    join_keys = ["REF_AREA_CODE", "CONCEPT_CODE", "FREQ_CODE"]
    df[join_keys] = df[join_keys].astype("string")
    return df


def _sidecar_frame(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "FREQUENCY": "A",
        "LATEST_ACTUAL_ANNUAL_DATA": pd.NA,
        "METHODOLOGY_NOTES": pd.NA,
        "COUNTRY_UPDATE_DATE": pd.NA,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


class TestAlignSchemaExcludesSidecarColumns:
    """_align_schema returns the observation columns only; the series
    metadata sidecar is joined separately, in get_weo_data, outside
    _get_weo_data_cached's 7-day cache, so a sidecar failure costs only the
    call that hit it. See _get_weo_data_cached and _join_series_metadata."""

    @pytest.fixture(autouse=True)
    def _patch_codelists(self, monkeypatch):
        # Not under test here; label columns are irrelevant to the observation
        # columns and an empty mapping keeps these tests off the network.
        monkeypatch.setattr(api, "_fetch_codelist", lambda agency, codelist_id: {})

    def test_returns_observation_columns_only(self, monkeypatch):
        mock_fetch_metadata = Mock()
        monkeypatch.setattr(api, "_fetch_series_metadata", mock_fetch_metadata)
        df = _minimal_api_frame([{"COUNTRY": "USA", "INDICATOR": "NGDP_RPCH"}])

        result = api._align_schema(df)

        assert list(result.columns) == api._OBSERVATION_COLUMNS
        for col in api._SIDECAR_SUPPLIED_COLUMNS:
            assert col not in result.columns
        mock_fetch_metadata.assert_not_called()


class TestJoinSeriesMetadata:
    """_join_series_metadata left-joins LASTACTUALDATE/NOTES/COUNTRY_UPDATE_DATE
    from the series metadata sidecar onto an already-_align_schema'd frame
    (REF_AREA_CODE/CONCEPT_CODE/FREQ_CODE, not the sidecar's own
    COUNTRY/INDICATOR/FREQUENCY), and degrades to null metadata columns
    (never raising) on any sidecar problem."""

    def test_populates_metadata_columns_from_sidecar(self, monkeypatch):
        df = _observation_frame([{"REF_AREA_CODE": "USA", "CONCEPT_CODE": "NGDP_RPCH"}])
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

        result = api._join_series_metadata(df, FlowRef("WEO", "9.0.0"))
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
        df = _observation_frame([{"REF_AREA_CODE": "USA", "CONCEPT_CODE": "NGDP_RPCH"}])
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

        result = api._join_series_metadata(df, FlowRef("WEO", "9.0.0"))

        assert result["LASTACTUALDATE"].dtype == "Int64"
        value = result.iloc[0]["LASTACTUALDATE"]
        if expected_year is None:
            assert pd.isna(value)
        else:
            assert value == expected_year

    def test_sidecar_failure_degrades_to_null_columns(self, monkeypatch):
        df = _observation_frame([{"REF_AREA_CODE": "USA", "CONCEPT_CODE": "NGDP_RPCH"}])

        def _raise(ref):
            raise ConnectionError("sidecar unreachable")

        monkeypatch.setattr(api, "_fetch_series_metadata", _raise)

        with patch("imf_reader.weo.api.logger.warning") as mock_warning:
            result = api._join_series_metadata(df, FlowRef("WEO", "9.0.0"))

        assert len(result) == 1
        assert pd.isna(result.iloc[0]["LASTACTUALDATE"])
        assert pd.isna(result.iloc[0]["NOTES"])
        assert pd.isna(result.iloc[0]["COUNTRY_UPDATE_DATE"])
        assert result["LASTACTUALDATE"].dtype == "Int64"
        assert result["NOTES"].dtype == "string"
        assert result["COUNTRY_UPDATE_DATE"].dtype == "datetime64[us]"
        assert mock_warning.called

    def test_duplicated_sidecar_key_drops_sidecar_entirely(self, monkeypatch):
        df = _observation_frame(
            [
                {"REF_AREA_CODE": "USA", "CONCEPT_CODE": "NGDP_RPCH"},
                {"REF_AREA_CODE": "BEL", "CONCEPT_CODE": "NGDP_RPCH"},
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
            result = api._join_series_metadata(df, FlowRef("WEO", "9.0.0"))

        # Row count unchanged: the sidecar was dropped, not merged and fanned out.
        assert len(result) == 2
        assert result["LASTACTUALDATE"].isna().all()
        assert mock_warning.called

    def test_sidecar_column_collision_drops_main_frame_copy(self, monkeypatch):
        """A warm parquet entry carrying the full 16 legacy-named columns
        under an unchanged cache key can leave ``df`` already holding
        LASTACTUALDATE/NOTES/COUNTRY_UPDATE_DATE columns (coincidentally the
        same names the sidecar's own columns carry, once renamed) by the
        time this runs. The join must drop those copies before merging
        rather than let pandas suffix them as _x/_y, and the sidecar's
        values must be the ones that survive -- see _join_series_metadata's
        docstring."""
        df = _observation_frame(
            [
                {
                    "REF_AREA_CODE": "USA",
                    "CONCEPT_CODE": "NGDP_RPCH",
                    # Stale values already on the frame -- must lose to the
                    # sidecar's, not merge into suffixed columns.
                    "LASTACTUALDATE": 2000,
                    "NOTES": "stale note",
                    "COUNTRY_UPDATE_DATE": "1/1/2000",
                }
            ]
        )
        meta = _sidecar_frame(
            [
                {
                    "COUNTRY": "USA",
                    "INDICATOR": "NGDP_RPCH",
                    "LATEST_ACTUAL_ANNUAL_DATA": "2024",
                    "METHODOLOGY_NOTES": "fresh note",
                    "COUNTRY_UPDATE_DATE": "9/19/2025",
                }
            ]
        )
        monkeypatch.setattr(api, "_fetch_series_metadata", lambda ref: meta)

        result = api._join_series_metadata(df, FlowRef("WEO", "9.0.0"))

        assert not any("_x" in c or "_y" in c for c in result.columns)
        row = result.iloc[0]
        assert row["LASTACTUALDATE"] == 2024
        assert row["NOTES"] == "fresh note"
        assert row["COUNTRY_UPDATE_DATE"] == pd.Timestamp("2025-09-19")

    def test_row_count_invariant_across_merge(self, monkeypatch):
        df = _observation_frame(
            [
                {"REF_AREA_CODE": "USA", "CONCEPT_CODE": "NGDP_RPCH"},
                {"REF_AREA_CODE": "BEL", "CONCEPT_CODE": "NGDP_RPCH"},
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

        result = api._join_series_metadata(df, FlowRef("WEO", "9.0.0"))

        assert len(result) == 2


class TestGetWeoDataSidecarCaching:
    """_get_weo_data_cached's observations cache and
    _fetch_series_metadata's sidecar cache are independent, so a transient
    sidecar failure costs only the call that hit it, not seven days of null
    metadata served from a warm observations cache that never touches the
    sidecar again."""

    @patch("imf_reader.weo.api._fetch_codelist")
    @patch("imf_reader.weo.api._fetch_flow_mapping")
    def test_sidecar_recovery_is_visible_on_a_warm_observations_cache(
        self, mock_mapping, mock_fetch_codelist, tmp_cache_root
    ):
        ref = FlowRef("WEO", "9.0.0")
        mock_mapping.return_value = {("October", 2025): ref}
        mock_fetch_codelist.return_value = {}

        main_csv = (
            "COUNTRY,INDICATOR,UNIT,FREQUENCY,SCALE,TIME_PERIOD,OBS_VALUE\n"
            "USA,NGDP_RPCH,XDC,A,0,2024,1.5\n"
        )
        sidecar_csv = (
            "COUNTRY,INDICATOR,FREQUENCY,LATEST_ACTUAL_ANNUAL_DATA,"
            "METHODOLOGY_NOTES,COUNTRY_UPDATE_DATE\n"
            "USA,NGDP_RPCH,A,2024,a note,9/19/2025\n"
        )
        call_counts = {"main": 0, "sidecar": 0}

        def fake_get(url, **kwargs):
            if "attributes=series" in url:
                call_counts["sidecar"] += 1
                if call_counts["sidecar"] == 1:
                    raise ConnectionError("sidecar unreachable")
                return _MockResponse(text=sidecar_csv)
            call_counts["main"] += 1
            return _MockResponse(text=main_csv)

        with patch("imf_reader.weo.api.make_get_request", side_effect=fake_get):
            first = api.get_weo_data(("October", 2025))
            second = api.get_weo_data(("October", 2025))

        assert pd.isna(first.iloc[0]["LASTACTUALDATE"])
        assert pd.isna(first.iloc[0]["NOTES"])
        assert pd.isna(first.iloc[0]["COUNTRY_UPDATE_DATE"])

        assert second.iloc[0]["LASTACTUALDATE"] == 2024
        assert second.iloc[0]["NOTES"] == "a note"
        assert second.iloc[0]["COUNTRY_UPDATE_DATE"] == pd.Timestamp("2025-09-19")

        # The sidecar comes off pd.read_csv with the default StringDtype
        # (na_value=nan); _align_schema's frame carries the StringDtype
        # _align_schema casts to (na_value=pd.NA). Unequal StringDtypes make
        # pandas' merge machinery fall through to casting both sides' join
        # keys to object, which would silently change get_weo_data's public
        # schema -- so the merge must keep these "string", not "object".
        for col in ("REF_AREA_CODE", "CONCEPT_CODE", "FREQ_CODE"):
            assert second[col].dtype == "string"

        # The main observations CSV is fetched once: the second call is a
        # cache hit on _get_weo_data_cached. The sidecar, which has no
        # successful cache entry to serve after failing on the first call, is
        # fetched on both calls -- a single shared cache would instead treat
        # the second call as a full cache hit and keep showing null metadata.
        assert call_counts["main"] == 1
        assert call_counts["sidecar"] == 2


class TestOutputColumnsAppended:
    """COUNTRY_UPDATE_DATE must be appended: positional access on the first
    15 columns is live in the wild."""

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
