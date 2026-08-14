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
    why that module-level attribute is unsafe to read here). The merge
    contract itself is pinned by TestFetchDataSeriesMetadataMergeability
    above."""

    def test_merges_fetch_data_and_series_metadata(self, monkeypatch):
        served_version = ("October", 2025)
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
            reader, "_fetch_data_resolved", Mock(return_value=(served_version, left))
        )
        monkeypatch.setattr(reader, "fetch_series_metadata", Mock(return_value=right))

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

    def test_fetches_metadata_for_the_version_fetch_data_actually_served(
        self, monkeypatch
    ):
        """The load-bearing case: fetch_data can roll back to a release
        different from the one the caller requested (or from 'latest'
        resolved independently). fetch_series_metadata must be called with
        that *served* release, never with the caller's own requested version
        -- resolving both independently is exactly what could land them on
        different releases if the flow mapping's 1-hour TTL lapses between
        the two calls. The requested and served versions are deliberately
        different tuples here, so a wrapper that (bug) passed the requested
        version straight through would be caught."""
        requested_version = ("October", 2025)
        served_version = ("April", 2025)
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
        mock_fetch_data_resolved = Mock(return_value=(served_version, left))
        monkeypatch.setattr(reader, "_fetch_data_resolved", mock_fetch_data_resolved)
        mock_fetch_series_metadata = Mock(return_value=right)
        monkeypatch.setattr(reader, "fetch_series_metadata", mock_fetch_series_metadata)

        reader.fetch_data_with_metadata(requested_version)

        mock_fetch_data_resolved.assert_called_once_with(requested_version)
        mock_fetch_series_metadata.assert_called_once_with(served_version)

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
        right before the call and confirming the metadata leg still requests
        the resolved release is what pins that this function never reads
        that attribute."""
        served_version = ("October", 2025)
        stale_version = ("April", 2020)
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
            reader, "_fetch_data_resolved", Mock(return_value=(served_version, left))
        )
        # Simulates a concurrent fetch_data() call elsewhere having last
        # written a different release to this module-level attribute.
        # raising=False: the attribute is only ever set the first time
        # fetch_data() actually runs, so it may not exist yet this early in
        # the suite.
        monkeypatch.setattr(
            reader.fetch_data, "last_version_fetched", stale_version, raising=False
        )
        mock_fetch_series_metadata = Mock(return_value=right)
        monkeypatch.setattr(reader, "fetch_series_metadata", mock_fetch_series_metadata)

        reader.fetch_data_with_metadata()

        mock_fetch_series_metadata.assert_called_once_with(served_version)

    def test_bulk_archive_release_raises_version_not_available_error(self, monkeypatch):
        """A bulk-archive release has no series metadata endpoint at all, so
        this must raise rather than degrade to null metadata columns -- a
        conditional schema is exactly what the separate-function design
        avoids. The re-raised message must name the served release and point
        the caller at fetch_data() for observations alone."""
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
        monkeypatch.setattr(
            reader, "_fetch_data_resolved", Mock(return_value=(served_version, left))
        )
        monkeypatch.setattr(
            reader,
            "fetch_series_metadata",
            Mock(side_effect=VersionNotAvailableError("no series metadata")),
        )

        with pytest.raises(VersionNotAvailableError) as excinfo:
            reader.fetch_data_with_metadata()

        message = str(excinfo.value)
        assert "April" in message
        assert "2020" in message
        assert "fetch_data" in message
        assert excinfo.value.__cause__ is not None

    def test_sets_last_version_fetched_to_the_served_version(self, monkeypatch):
        served_version = ("October", 2025)
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
            reader, "_fetch_data_resolved", Mock(return_value=(served_version, left))
        )
        monkeypatch.setattr(reader, "fetch_series_metadata", Mock(return_value=right))

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
            reader, "_fetch_data_resolved", Mock(return_value=(served_version, left))
        )
        monkeypatch.setattr(reader, "fetch_series_metadata", Mock(return_value=right))

        with patch("imf_reader.weo.reader.logger.warning") as mock_warning:
            merged = reader.fetch_data_with_metadata()

        assert not any(c.endswith(("_x", "_y")) for c in merged.columns)
        assert merged.iloc[0]["UNIT_LABEL"] == "US Dollar"
        assert mock_warning.called
        assert "UNIT_LABEL" in str(mock_warning.call_args)
