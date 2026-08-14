"""Load-bearing merge contract between fetch_data()'s observations and
fetch_series_metadata()'s sidecar frame: a caller-side
``left.merge(right, on=[...], how="left")`` on (REF_AREA_CODE, CONCEPT_CODE,
FREQ_CODE) must never fan rows out, fall back to object dtype, or produce
_x/_y suffixed columns.

The two fixture frames below are built through the real dtype-coercion each
side actually applies -- _align_schema's ``.astype("string")`` for the left
frame, ``_series_metadata_for_ref``'s own ``.astype("string")`` for the right
-- rather than straight from dict literals. A dict-built frame gets matching
inferred dtypes for free and would skip the exact coercion this test exists
to pin.
"""

from unittest.mock import Mock, patch

import pandas as pd
import pytest

from imf_reader.config import VersionNotAvailableError
from imf_reader.weo import api, reader
from imf_reader.weo.api import FlowRef

_JOIN_KEYS = ["REF_AREA_CODE", "CONCEPT_CODE", "FREQ_CODE"]


def _fetch_data_frame(rows: list[dict]) -> pd.DataFrame:
    """A minimal fetch_data-shaped frame: the join keys are cast to
    "string" (StringDtype) the same way _align_schema's own string_columns
    loop casts them, so this frame's join-key dtype is the real dtype
    fetch_data hands a caller -- not whatever dtype a dict literal happens to
    infer on its own."""
    df = pd.DataFrame(rows)
    for key in _JOIN_KEYS:
        df[key] = df[key].astype("string")
    return df


def _series_metadata_frame(monkeypatch, rows: list[dict]) -> pd.DataFrame:
    """Builds a frame through the real _series_metadata_for_ref, off a raw
    sidecar whose join keys are left at pandas' default object dtype -- the
    input shape a widened sidecar carries before _series_metadata_for_ref's
    own ``.astype("string")`` runs. Routing through the real function, rather
    than casting the fixture directly, is what makes the merge under test
    exercise that coercion instead of one supplied for free by the fixture."""
    sidecar = pd.DataFrame(rows)
    monkeypatch.setattr(api, "_fetch_series_metadata", lambda ref: sidecar)
    return api._series_metadata_for_ref(FlowRef("WEO", "9.0.0"))


class TestFetchDataSeriesMetadataMergeability:
    """fetch_data() and fetch_series_metadata() are two independent frames a
    caller is expected to join themselves (see fetch_series_metadata's
    docstring). This pins that the join actually behaves: unchanged row
    count, string-typed join keys on both sides post-merge, and no suffixed
    column -- the three ways a dtype mismatch on either side would otherwise
    surface silently."""

    def test_left_merge_preserves_row_count_dtype_and_column_names(self, monkeypatch):
        left = _fetch_data_frame(
            [
                {
                    "REF_AREA_CODE": "USA",
                    "CONCEPT_CODE": "NGDP_RPCH",
                    "FREQ_CODE": "A",
                    "OBS_VALUE": 2.1,
                },
                {
                    "REF_AREA_CODE": "BEL",
                    "CONCEPT_CODE": "NGDP_RPCH",
                    "FREQ_CODE": "A",
                    "OBS_VALUE": 1.4,
                },
            ]
        )
        right = _series_metadata_frame(
            monkeypatch,
            [
                {
                    "COUNTRY": "USA",
                    "INDICATOR": "NGDP_RPCH",
                    "FREQUENCY": "A",
                    "TOPIC": "F32",
                }
            ],
        )

        merged = left.merge(right, on=_JOIN_KEYS, how="left")

        assert len(merged) == len(left)
        for key in _JOIN_KEYS:
            assert merged[key].dtype == "string"
        assert not any(c.endswith(("_x", "_y")) for c in merged.columns)

        # Row count, dtype and the absence of suffixes all pass even if the
        # join matched zero rows -- a key-vocabulary drift between the
        # sidecar's COUNTRY and _align_schema's REF_AREA_CODE would produce
        # exactly this shape, with every metadata cell null. Asserting both
        # directions of the left join -- a key that must match carries the
        # sidecar's value, a key that must not match is null -- is what
        # actually pins that the merge matched, and that how="left" was not
        # silently an inner join.
        matched = merged.loc[merged["REF_AREA_CODE"] == "USA"].iloc[0]
        # Compared through a null check first, so a drift that leaves this
        # cell <NA> fails on the assertion rather than on pandas raising
        # "boolean value of NA is ambiguous" from the equality itself.
        assert not pd.isna(matched["TOPIC"])
        assert matched["TOPIC"] == "F32"
        unmatched = merged.loc[merged["REF_AREA_CODE"] == "BEL"].iloc[0]
        assert pd.isna(unmatched["TOPIC"])


class TestFetchDataWithMetadata:
    """fetch_data_with_metadata encodes the merge idiom documented on
    fetch_series_metadata so a caller cannot get it wrong. The observations
    leg is mocked via reader._fetch_data_resolved -- the private resolver
    fetch_data_with_metadata calls directly, rather than reader.fetch_data
    itself, so that the version it merges metadata for is never read back off
    fetch_data.last_version_fetched (see _fetch_data_resolved's docstring for
    why that module-level attribute is unsafe to read here). The metadata leg
    itself is mocked via reader._series_metadata_for_ref -- the ref-taking
    path fetch_data_with_metadata calls directly, rather than
    reader.fetch_series_metadata, precisely so it never re-resolves the
    version through the (separately TTL'd) flow mapping. That re-resolution
    risk, and the sidecar-retry repair it motivates, are pinned by
    TestMetadataLegSharesTheObservationsRef and TestRejoinsADegradedSidecar
    below. The merge contract itself is pinned by
    TestFetchDataSeriesMetadataMergeability above."""

    def test_merges_fetch_data_and_series_metadata(self, monkeypatch):
        served_version = ("October", 2025)
        ref = FlowRef("WEO", "9.0.0")
        left = _fetch_data_frame(
            [
                {
                    "REF_AREA_CODE": "USA",
                    "CONCEPT_CODE": "NGDP_RPCH",
                    "FREQ_CODE": "A",
                    "OBS_VALUE": 2.1,
                },
                {
                    "REF_AREA_CODE": "BEL",
                    "CONCEPT_CODE": "NGDP_RPCH",
                    "FREQ_CODE": "A",
                    "OBS_VALUE": 1.4,
                },
            ]
        )
        right = _series_metadata_frame(
            monkeypatch,
            [
                {
                    "COUNTRY": "USA",
                    "INDICATOR": "NGDP_RPCH",
                    "FREQUENCY": "A",
                    "TOPIC": "F32",
                }
            ],
        )
        monkeypatch.setattr(
            reader,
            "_fetch_data_resolved",
            Mock(return_value=(served_version, left, ref)),
        )
        monkeypatch.setattr(
            reader, "_series_metadata_for_ref", Mock(return_value=right)
        )
        monkeypatch.setattr(
            reader, "_rejoin_series_metadata_if_degraded", lambda df, ref: df
        )

        merged = reader.fetch_data_with_metadata()

        assert len(merged) == len(left)
        for key in _JOIN_KEYS:
            assert merged[key].dtype == "string"
        assert not any(c.endswith(("_x", "_y")) for c in merged.columns)

        # As above: row count, dtype and no-suffix all pass on a zero-match
        # join too. Asserting both directions of the left join is what pins
        # that the merge actually matched.
        matched = merged.loc[merged["REF_AREA_CODE"] == "USA"].iloc[0]
        # Compared through a null check first, so a drift that leaves this
        # cell <NA> fails on the assertion rather than on pandas raising
        # "boolean value of NA is ambiguous" from the equality itself.
        assert not pd.isna(matched["TOPIC"])
        assert matched["TOPIC"] == "F32"
        unmatched = merged.loc[merged["REF_AREA_CODE"] == "BEL"].iloc[0]
        assert pd.isna(unmatched["TOPIC"])

    def test_fetches_metadata_for_the_ref_fetch_data_actually_served(self, monkeypatch):
        """The load-bearing wiring case: the metadata leg must be called
        with the FlowRef _fetch_data_resolved's own return value names, never
        anything re-derived from the requested version. The requested
        version and the served ref are deliberately unrelated here, so a
        wrapper that (bug) re-resolved a ref from the requested version
        instead of reusing the one it was handed would be caught. The
        stronger regression -- that no re-resolution happens at all, even
        when the flow mapping itself changes between the two legs -- is
        TestMetadataLegSharesTheObservationsRef below."""
        requested_version = ("October", 2025)
        served_version = ("April", 2025)
        ref = FlowRef("WEO", "9.0.0")
        left = _fetch_data_frame(
            [
                {
                    "REF_AREA_CODE": "USA",
                    "CONCEPT_CODE": "NGDP_RPCH",
                    "FREQ_CODE": "A",
                    "OBS_VALUE": 2.1,
                }
            ]
        )
        right = _series_metadata_frame(
            monkeypatch,
            [
                {
                    "COUNTRY": "USA",
                    "INDICATOR": "NGDP_RPCH",
                    "FREQUENCY": "A",
                    "TOPIC": "F32",
                }
            ],
        )
        mock_fetch_data_resolved = Mock(return_value=(served_version, left, ref))
        monkeypatch.setattr(reader, "_fetch_data_resolved", mock_fetch_data_resolved)
        mock_series_metadata_for_ref = Mock(return_value=right)
        monkeypatch.setattr(
            reader, "_series_metadata_for_ref", mock_series_metadata_for_ref
        )
        monkeypatch.setattr(
            reader, "_rejoin_series_metadata_if_degraded", lambda df, ref: df
        )

        reader.fetch_data_with_metadata(requested_version)

        mock_fetch_data_resolved.assert_called_once_with(requested_version)
        mock_series_metadata_for_ref.assert_called_once_with(ref)

    def test_uses_the_resolved_call_version_not_fetch_data_last_version_fetched(
        self, monkeypatch
    ):
        """fetch_data_with_metadata must use the version
        _fetch_data_resolved's own return value names, never read
        fetch_data.last_version_fetched back off the module-level function
        object. That attribute is process-global -- a concurrent
        fetch_data() call elsewhere can overwrite it between this call's own
        fetch and a read of the attribute, landing the metadata leg on the
        wrong release. Setting the attribute to a stale, different release
        right before the call and confirming last_version_fetched still ends
        up as the resolved release is what pins that this function never
        reads that attribute."""
        served_version = ("October", 2025)
        stale_version = ("April", 2020)
        ref = FlowRef("WEO", "9.0.0")
        left = _fetch_data_frame(
            [
                {
                    "REF_AREA_CODE": "USA",
                    "CONCEPT_CODE": "NGDP_RPCH",
                    "FREQ_CODE": "A",
                    "OBS_VALUE": 2.1,
                }
            ]
        )
        right = _series_metadata_frame(
            monkeypatch,
            [
                {
                    "COUNTRY": "USA",
                    "INDICATOR": "NGDP_RPCH",
                    "FREQUENCY": "A",
                    "TOPIC": "F32",
                }
            ],
        )
        monkeypatch.setattr(
            reader,
            "_fetch_data_resolved",
            Mock(return_value=(served_version, left, ref)),
        )
        # Simulates a concurrent fetch_data() call elsewhere having last
        # written a different release to this module-level attribute.
        # raising=False: the attribute is only ever set the first time
        # fetch_data() actually runs, so it may not exist yet this early in
        # the suite.
        monkeypatch.setattr(
            reader.fetch_data, "last_version_fetched", stale_version, raising=False
        )
        monkeypatch.setattr(
            reader, "_series_metadata_for_ref", Mock(return_value=right)
        )
        monkeypatch.setattr(
            reader, "_rejoin_series_metadata_if_degraded", lambda df, ref: df
        )

        reader.fetch_data_with_metadata()

        assert reader.fetch_data_with_metadata.last_version_fetched == served_version

    def test_bulk_archive_release_raises_version_not_available_error(self, monkeypatch):
        """A bulk-archive release has no series metadata endpoint at all --
        signalled by _fetch_data_resolved returning ref=None (see its
        docstring) -- so this must raise rather than degrade to null
        metadata columns, which is exactly the conditional schema the
        separate-function design avoids. The message must name the served
        release and point the caller at fetch_data() for observations
        alone."""
        served_version = ("April", 2020)
        left = _fetch_data_frame(
            [
                {
                    "REF_AREA_CODE": "USA",
                    "CONCEPT_CODE": "NGDP_RPCH",
                    "FREQ_CODE": "A",
                    "OBS_VALUE": 2.1,
                }
            ]
        )
        mock_series_metadata_for_ref = Mock()
        monkeypatch.setattr(
            reader,
            "_fetch_data_resolved",
            Mock(return_value=(served_version, left, None)),
        )
        monkeypatch.setattr(
            reader, "_series_metadata_for_ref", mock_series_metadata_for_ref
        )

        with pytest.raises(VersionNotAvailableError) as excinfo:
            reader.fetch_data_with_metadata()

        message = str(excinfo.value)
        assert "April" in message
        assert "2020" in message
        assert "fetch_data" in message
        # No series metadata endpoint exists for a bulk-archive release, so
        # the ref-taking path must never even be attempted.
        mock_series_metadata_for_ref.assert_not_called()

    def test_sets_last_version_fetched_to_the_served_version(self, monkeypatch):
        served_version = ("October", 2025)
        ref = FlowRef("WEO", "9.0.0")
        left = _fetch_data_frame(
            [
                {
                    "REF_AREA_CODE": "USA",
                    "CONCEPT_CODE": "NGDP_RPCH",
                    "FREQ_CODE": "A",
                    "OBS_VALUE": 2.1,
                }
            ]
        )
        right = _series_metadata_frame(
            monkeypatch,
            [
                {
                    "COUNTRY": "USA",
                    "INDICATOR": "NGDP_RPCH",
                    "FREQUENCY": "A",
                    "TOPIC": "F32",
                }
            ],
        )
        monkeypatch.setattr(
            reader,
            "_fetch_data_resolved",
            Mock(return_value=(served_version, left, ref)),
        )
        monkeypatch.setattr(
            reader, "_series_metadata_for_ref", Mock(return_value=right)
        )
        monkeypatch.setattr(
            reader, "_rejoin_series_metadata_if_degraded", lambda df, ref: df
        )

        reader.fetch_data_with_metadata()

        assert reader.fetch_data_with_metadata.last_version_fetched == served_version

    def test_colliding_metadata_column_drops_in_favour_of_observations(
        self, monkeypatch
    ):
        """Today's deny-lists happen to keep fetch_data's and the sidecar's
        columns disjoint, but get_series_metadata's own docstring says the
        sidecar's column set is release-dependent, so a future DSD attribute
        could collide by name with one of fetch_data's own columns (e.g.
        UNIT_LABEL). Left
        unguarded, pandas' default suffixes would rename fetch_data's own
        column to ``UNIT_LABEL_x`` rather than raise. The observations column
        must survive unrenamed, and a warning must fire naming the dropped
        column."""
        served_version = ("October", 2025)
        ref = FlowRef("WEO", "9.0.0")
        left = _fetch_data_frame(
            [
                {
                    "REF_AREA_CODE": "USA",
                    "CONCEPT_CODE": "NGDP_RPCH",
                    "FREQ_CODE": "A",
                    "OBS_VALUE": 2.1,
                    "UNIT_LABEL": "US Dollar",
                }
            ]
        )
        right = _series_metadata_frame(
            monkeypatch,
            [
                {
                    "COUNTRY": "USA",
                    "INDICATOR": "NGDP_RPCH",
                    "FREQUENCY": "A",
                    "UNIT_LABEL": "a future DSD label",
                }
            ],
        )
        monkeypatch.setattr(
            reader,
            "_fetch_data_resolved",
            Mock(return_value=(served_version, left, ref)),
        )
        monkeypatch.setattr(
            reader, "_series_metadata_for_ref", Mock(return_value=right)
        )
        monkeypatch.setattr(
            reader, "_rejoin_series_metadata_if_degraded", lambda df, ref: df
        )

        with patch("imf_reader.weo.reader.logger.warning") as mock_warning:
            merged = reader.fetch_data_with_metadata()

        assert not any(c.endswith(("_x", "_y")) for c in merged.columns)
        assert merged.iloc[0]["UNIT_LABEL"] == "US Dollar"
        assert mock_warning.called
        assert "UNIT_LABEL" in str(mock_warning.call_args)


class TestMetadataLegSharesTheObservationsRef:
    """Regression for the flow-mapping race described on
    fetch_data_with_metadata's own docstring: _fetch_flow_mapping has a
    1-hour TTL, so it can remap a release between fetch_data_with_metadata's
    two sidecar reads (the observations leg's own join, then the metadata
    leg). A metadata leg that re-resolved served_version through the mapping
    instead of reusing the observations leg's own FlowRef (the bug) would
    consult _fetch_flow_mapping a second time and could pick up a different
    FlowRef there -- landing the two legs on different dataflow versions for
    the same release label. Unlike TestFetchDataWithMetadata above, this
    exercises the real _fetch_data_resolved / _fetch_data_for_version /
    _get_weo_data_with_ref chain, mocking only the HTTP-touching leaves
    (_fetch_flow_mapping, _get_weo_data_cached, _fetch_series_metadata) --
    mocking reader._fetch_data_resolved itself would hide a real
    re-resolution happening on the observations leg."""

    def test_flow_mapping_is_consulted_once_even_though_it_would_answer_differently(
        self, monkeypatch
    ):
        version = ("October", 2025)
        first_ref = FlowRef("WEO", "9.0.0")
        second_ref = FlowRef("WEO", "9.0.1")
        mapping_calls: list[FlowRef] = []

        def fake_mapping():
            ref = first_ref if not mapping_calls else second_ref
            mapping_calls.append(ref)
            return {version: ref}

        monkeypatch.setattr(api, "_fetch_flow_mapping", fake_mapping)

        observations = _fetch_data_frame(
            [
                {
                    "REF_AREA_CODE": "USA",
                    "CONCEPT_CODE": "NGDP_RPCH",
                    "FREQ_CODE": "A",
                    "OBS_VALUE": 2.1,
                }
            ]
        )
        # Every other OUTPUT_COLUMNS entry _get_weo_data_cached would
        # normally supply, filled with null so the reindex to OUTPUT_COLUMNS
        # inside _get_weo_data_with_ref does not KeyError.
        for column in api._OBSERVATION_COLUMNS:
            if column not in observations.columns:
                observations[column] = pd.NA
        monkeypatch.setattr(
            api, "_get_weo_data_cached", lambda version, ref: observations.copy()
        )

        refs_seen = []

        def fake_fetch_series_metadata(ref):
            refs_seen.append(ref)
            return pd.DataFrame(
                [
                    {
                        "COUNTRY": "USA",
                        "INDICATOR": "NGDP_RPCH",
                        "FREQUENCY": "A",
                        "TOPIC": "F32",
                    }
                ]
            )

        monkeypatch.setattr(api, "_fetch_series_metadata", fake_fetch_series_metadata)

        merged = reader.fetch_data_with_metadata(version)

        # The mapping only ever answers once: the metadata leg reused the
        # observations leg's own ref rather than re-resolving.
        assert mapping_calls == [first_ref]
        assert refs_seen and all(ref == first_ref for ref in refs_seen)
        assert merged.iloc[0]["TOPIC"] == "F32"


class TestRejoinsADegradedSidecar:
    """fetch_data_with_metadata reads the series-metadata sidecar twice for
    one call: once building its observations frame (inside
    _fetch_data_resolved), once for its own metadata frame
    (_series_metadata_for_ref). If the first read fails transiently and
    degrades LASTACTUALDATE/NOTES/COUNTRY_UPDATE_DATE to null, but the
    second read succeeds, the returned frame must not keep those three
    columns null next to a populated raw metadata column for the same
    series -- api._rejoin_series_metadata_if_degraded repairs them using the
    now-warm sidecar cache. Exercises the real fetch chain, as
    TestMetadataLegSharesTheObservationsRef does, so the "first read" really
    is the observations leg's own join, not a fabricated stand-in."""

    def test_retries_a_degraded_sidecar_read_once_the_second_read_succeeds(
        self, monkeypatch
    ):
        version = ("October", 2025)
        ref = FlowRef("WEO", "9.0.0")
        monkeypatch.setattr(api, "_fetch_flow_mapping", lambda: {version: ref})

        observations = _fetch_data_frame(
            [
                {
                    "REF_AREA_CODE": "USA",
                    "CONCEPT_CODE": "NGDP_RPCH",
                    "FREQ_CODE": "A",
                    "OBS_VALUE": 2.1,
                }
            ]
        )
        for column in api._OBSERVATION_COLUMNS:
            if column not in observations.columns:
                observations[column] = pd.NA
        monkeypatch.setattr(
            api, "_get_weo_data_cached", lambda version, ref: observations.copy()
        )

        sidecar = pd.DataFrame(
            [
                {
                    "COUNTRY": "USA",
                    "INDICATOR": "NGDP_RPCH",
                    "FREQUENCY": "A",
                    "LATEST_ACTUAL_ANNUAL_DATA": "2024",
                    "METHODOLOGY_NOTES": "a note",
                    "COUNTRY_UPDATE_DATE": "9/19/2025",
                    "TOPIC": "F32",
                }
            ]
        )
        calls = {"n": 0}

        def flaky_fetch_series_metadata(ref):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("transient")
            return sidecar.copy()

        monkeypatch.setattr(api, "_fetch_series_metadata", flaky_fetch_series_metadata)

        merged = reader.fetch_data_with_metadata(version)

        # 1: the observations leg's own join (fails). 2: the metadata leg
        # (succeeds, proving the cache is warm). 3+: the repair's re-join.
        assert calls["n"] >= 3

        # Observation column order is unchanged by the repair path -- the
        # repair drops and re-adds the three sidecar-supplied columns, and
        # must restore their original positions rather than leaving them
        # appended at the end.
        assert list(merged.columns[: len(api.OUTPUT_COLUMNS)]) == api.OUTPUT_COLUMNS

        row = merged.iloc[0]
        assert not pd.isna(row["LASTACTUALDATE"])
        assert row["LASTACTUALDATE"] == 2024
        assert not pd.isna(row["NOTES"])
        assert row["NOTES"] == "a note"
        assert not pd.isna(row["COUNTRY_UPDATE_DATE"])
        assert row["TOPIC"] == "F32"


class TestNaLikeLiteralsPreservedVerbatimButNormalisedInNotes:
    """The IMF's sidecar carries literal "N/A"/"n/a" cells on some columns
    (e.g. METHODOLOGY_NOTES, BASIS_OF_PROJECTIONS) distinct from a
    genuinely empty cell. _fetch_series_metadata's raw frame must preserve
    that literal verbatim (see its docstring), while fetch_data's derived
    NOTES column must still normalise it to null alongside a genuinely
    empty cell -- a caller filtering df[df.NOTES.notna()] must not get back
    a row whose note is the literal word for "no note"."""

    # COUNTRY, INDICATOR, FREQUENCY are the sidecar's own join-key columns
    # (pre-rename). Three rows: a real note, a literal NA-like token (upper
    # and lower case, spread across two columns to pin that both are
    # preserved/normalised, not just one), and a genuinely empty cell.
    _SIDECAR_CSV = (
        "COUNTRY,INDICATOR,FREQUENCY,METHODOLOGY_NOTES,BASIS_OF_PROJECTIONS,"
        "LATEST_ACTUAL_ANNUAL_DATA,COUNTRY_UPDATE_DATE\n"
        "USA,NGDP_RPCH,A,A real note,n/a,2024,9/19/2025\n"
        "BEL,NGDP_RPCH,A,N/A,Government budget and projected nominal GDP,2024,9/19/2025\n"
        "DEU,NGDP_RPCH,A,,,2024,9/19/2025\n"
    )

    def test_fetch_series_metadata_raw_frame_preserves_literal_na_but_nulls_empty_cell(
        self, cache_disabled
    ):
        """Pins _fetch_series_metadata's own contract: verbatim except for a
        genuinely empty cell. Also covers BASIS_OF_PROJECTIONS, a
        metadata-frame-only column (not in _SIDECAR_RAW_COLUMNS), so it is
        never touched by fetch_data's own NOTES normalisation."""
        response = Mock(text=self._SIDECAR_CSV)
        with patch("imf_reader.weo.api.make_get_request", return_value=response):
            meta = api._fetch_series_metadata(FlowRef("WEO", "9.0.0"))
        meta = meta.set_index("COUNTRY")

        assert meta.loc["USA", "METHODOLOGY_NOTES"] == "A real note"
        assert meta.loc["BEL", "METHODOLOGY_NOTES"] == "N/A"
        assert pd.isna(meta.loc["DEU", "METHODOLOGY_NOTES"])

        assert meta.loc["USA", "BASIS_OF_PROJECTIONS"] == "n/a"
        assert (
            meta.loc["BEL", "BASIS_OF_PROJECTIONS"]
            == "Government budget and projected nominal GDP"
        )
        assert pd.isna(meta.loc["DEU", "BASIS_OF_PROJECTIONS"])

    def test_fetch_data_notes_column_nulls_both_the_literal_na_and_the_empty_cell(
        self, monkeypatch, cache_disabled
    ):
        """The same fixture, this time through fetch_data(): NOTES must be
        null for both the literal "N/A" row and the genuinely empty row, and
        must carry the real note for the third -- the guard against the
        verbatim-preservation fix leaking into the shipped NOTES column.
        Routed through the real, decorated _fetch_series_metadata (only
        make_get_request is mocked, via cache_disabled) rather than
        monkeypatching _fetch_series_metadata itself, so this exercises the
        NA normalisation this test exists to pin end to end -- from the raw
        CSV text through to the NOTES column fetch_data hands a caller."""
        version = ("October", 2025)
        ref = FlowRef("WEO", "9.0.0")
        monkeypatch.setattr(api, "_fetch_flow_mapping", lambda: {version: ref})

        observations = _fetch_data_frame(
            [
                {
                    "REF_AREA_CODE": "USA",
                    "CONCEPT_CODE": "NGDP_RPCH",
                    "FREQ_CODE": "A",
                    "OBS_VALUE": 1.0,
                },
                {
                    "REF_AREA_CODE": "BEL",
                    "CONCEPT_CODE": "NGDP_RPCH",
                    "FREQ_CODE": "A",
                    "OBS_VALUE": 2.0,
                },
                {
                    "REF_AREA_CODE": "DEU",
                    "CONCEPT_CODE": "NGDP_RPCH",
                    "FREQ_CODE": "A",
                    "OBS_VALUE": 3.0,
                },
            ]
        )
        for column in api._OBSERVATION_COLUMNS:
            if column not in observations.columns:
                observations[column] = pd.NA
        monkeypatch.setattr(
            api, "_get_weo_data_cached", lambda version, ref: observations.copy()
        )

        response = Mock(text=self._SIDECAR_CSV)
        with patch("imf_reader.weo.api.make_get_request", return_value=response):
            merged = reader.fetch_data(version)

        merged = merged.set_index("REF_AREA_CODE")
        assert pd.isna(merged.loc["BEL", "NOTES"])
        assert pd.isna(merged.loc["DEU", "NOTES"])
        assert merged.loc["USA", "NOTES"] == "A real note"


class TestOtherDerivedColumnsTolerateNaLikeLiterals:
    """LASTACTUALDATE and COUNTRY_UPDATE_DATE, like NOTES, are derived from
    sidecar columns that can carry a preserved NA-like literal
    (LATEST_ACTUAL_ANNUAL_DATA, COUNTRY_UPDATE_DATE itself). Both collapse
    such a literal to <NA>/NaT exactly as a genuinely empty cell does -- see
    _parse_latest_actual_annual_data's and _parse_country_update_date's own
    docstrings for why."""

    @pytest.mark.parametrize("na_like", ["N/A", "n/a"])
    def test_na_like_literal_in_latest_actual_annual_data_becomes_na(
        self, monkeypatch, na_like
    ):
        df = _fetch_data_frame(
            [
                {
                    "REF_AREA_CODE": "USA",
                    "CONCEPT_CODE": "NGDP_RPCH",
                    "FREQ_CODE": "A",
                    "OBS_VALUE": 1.0,
                }
            ]
        )
        meta = pd.DataFrame(
            [
                {
                    "COUNTRY": "USA",
                    "INDICATOR": "NGDP_RPCH",
                    "FREQUENCY": "A",
                    "LATEST_ACTUAL_ANNUAL_DATA": na_like,
                    "METHODOLOGY_NOTES": pd.NA,
                    "COUNTRY_UPDATE_DATE": "9/19/2025",
                }
            ]
        )
        monkeypatch.setattr(api, "_fetch_series_metadata", lambda ref: meta)

        result = api._join_series_metadata(df, FlowRef("WEO", "9.0.0"))

        assert result["LASTACTUALDATE"].dtype == "Int64"
        assert pd.isna(result.iloc[0]["LASTACTUALDATE"])

    @pytest.mark.parametrize("na_like", ["N/A", "n/a"])
    def test_na_like_literal_in_country_update_date_becomes_nat(
        self, monkeypatch, na_like
    ):
        df = _fetch_data_frame(
            [
                {
                    "REF_AREA_CODE": "USA",
                    "CONCEPT_CODE": "NGDP_RPCH",
                    "FREQ_CODE": "A",
                    "OBS_VALUE": 1.0,
                }
            ]
        )
        meta = pd.DataFrame(
            [
                {
                    "COUNTRY": "USA",
                    "INDICATOR": "NGDP_RPCH",
                    "FREQUENCY": "A",
                    "LATEST_ACTUAL_ANNUAL_DATA": "2024",
                    "METHODOLOGY_NOTES": pd.NA,
                    "COUNTRY_UPDATE_DATE": na_like,
                }
            ]
        )
        monkeypatch.setattr(api, "_fetch_series_metadata", lambda ref: meta)

        result = api._join_series_metadata(df, FlowRef("WEO", "9.0.0"))

        assert result["COUNTRY_UPDATE_DATE"].dtype == "datetime64[us]"
        assert pd.isna(result.iloc[0]["COUNTRY_UPDATE_DATE"])
