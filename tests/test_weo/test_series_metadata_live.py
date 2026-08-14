"""Live acceptance tests for the series-metadata feature against the real IMF
API: schema shape on both the bare WEO flow (latest) and an archival
WEO_YYYY_MON_VINTAGE flow, and the merge contract against a live fetch_data()
frame.

Unit tests (test_series_metadata.py, test_reader.py, test_api.py) patch every
HTTP boundary, so none of them can see a real DSD drift -- a renamed column,
a widened attribute set, a codelist rename. This file is what would catch
that.
"""

import os

import pandas as pd
import pytest

from imf_reader.weo.reader import (
    fetch_data,
    fetch_data_with_metadata,
    fetch_series_metadata,
)

# A lower bound, never an exact count: the IMF adding an attribute to the DSD
# must not break this suite. Against the live API, the bare flow's sidecar is
# 8,200 x 49 and the vintage flow's is 8,208 x 49 with an identical column
# set, both yielding 41 columns after _SIDECAR_ENVELOPE_COLUMNS and
# _SERIES_METADATA_EXCLUDED are dropped.
_MIN_COLUMN_COUNT = 35

# Envelope/observation artefacts and columns _SERIES_METADATA_EXCLUDED drops
# -- see api._SIDECAR_ENVELOPE_COLUMNS and api._SERIES_METADATA_EXCLUDED.
# None of these belong on the public series-metadata frame.
_DENIED_COLUMNS = frozenset(
    {
        "STRUCTURE",
        "STRUCTURE_ID",
        "ACTION",
        "TIME_PERIOD",
        "OBS_VALUE",
        "COUNTRY_UPDATE_DATE",
        "UNIT",
        "SCALE",
    }
)

_JOIN_KEYS = ["REF_AREA_CODE", "CONCEPT_CODE", "FREQ_CODE"]


def _assert_series_metadata_schema(meta: pd.DataFrame) -> None:
    """Shared schema contract, checked against both the bare WEO flow and a
    WEO_YYYY_MON_VINTAGE flow: both must satisfy it regardless of which
    dataflow actually serves the release."""
    assert not meta.duplicated(subset=_JOIN_KEYS).any()
    assert all(dtype == "string" for dtype in meta.dtypes)
    assert not any("[" in c or "]" in c for c in meta.columns)
    assert _DENIED_COLUMNS.isdisjoint(meta.columns)
    assert len(meta.columns) >= _MIN_COLUMN_COUNT


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("IMF_READER_LIVE_TESTS") != "1",
    reason="hits the real IMF API and CDN; set IMF_READER_LIVE_TESTS=1 to run",
)
def test_series_metadata_latest_release_shape_and_schema(tmp_cache_root):
    """The bare WEO flow's sidecar, resolved as 'latest', must satisfy the
    deny-list-only schema contract: no duplicate join keys, every column
    "string", no bracket-suffixed header left over from the SDMX-CSV writer,
    and none of the envelope/excluded columns present."""
    meta = fetch_series_metadata()

    _assert_series_metadata_schema(meta)


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("IMF_READER_LIVE_TESTS") != "1",
    reason="hits the real IMF API and CDN; set IMF_READER_LIVE_TESTS=1 to run",
)
def test_fetch_data_and_fetch_series_metadata_merge_cleanly_for_same_version(
    tmp_cache_root,
):
    """The documented idiom from fetch_series_metadata's own docstring --
    resolving both calls to the same concrete version via
    fetch_data.last_version_fetched -- must actually produce a clean left
    merge: unchanged row count, no _x/_y suffixed columns."""
    df = fetch_data()
    resolved_version = fetch_data.last_version_fetched
    meta = fetch_series_metadata(resolved_version)

    merged = df.merge(meta, on=_JOIN_KEYS, how="left")

    assert len(merged) == len(df)
    assert not any(c.endswith(("_x", "_y")) for c in merged.columns)
    # Row count, dtype and no suffixed column all pass even if the join
    # matched zero rows -- a key-vocabulary drift between the sidecar's
    # COUNTRY and _align_schema's REF_AREA_CODE would produce exactly this
    # shape, with every metadata cell null. METHODOLOGY_NOTES is broadly
    # populated across the live sidecar, so a majority match rate is what
    # actually pins that the join keys matched.
    assert merged["METHODOLOGY_NOTES"].notna().mean() > 0.5


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("IMF_READER_LIVE_TESTS") != "1",
    reason="hits the real IMF API and CDN; set IMF_READER_LIVE_TESTS=1 to run",
)
def test_fiscal_year_reporting_columns_present_and_populated(tmp_cache_root):
    """Regression guard: START_END_MONTHS_OF_REPORTING_YEAR and
    LATEST_ACTUAL_ANNUAL_DATA must both be present and non-empty in the live
    sidecar. CHANGELOG.md and docs/docs/weo-coverage.md document the
    releases where either can be missing; this pins that the current release
    is not one of them."""
    meta = fetch_series_metadata()

    for col in ("START_END_MONTHS_OF_REPORTING_YEAR", "LATEST_ACTUAL_ANNUAL_DATA"):
        assert col in meta.columns
        assert meta[col].notna().any()


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("IMF_READER_LIVE_TESTS") != "1",
    reason="hits the real IMF API and CDN; set IMF_READER_LIVE_TESTS=1 to run",
)
def test_series_metadata_vintage_flow_shape_and_schema(tmp_cache_root):
    """October 2025 resolves to the WEO_2025_OCT_VINTAGE flow rather than the
    bare WEO flow (see FlowRef and _resolve_flow_ref) -- the same schema
    contract asserted above against 'latest' must hold here too."""
    meta = fetch_series_metadata(("October", 2025))

    _assert_series_metadata_schema(meta)


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("IMF_READER_LIVE_TESTS") != "1",
    reason="hits the real IMF API and CDN; set IMF_READER_LIVE_TESTS=1 to run",
)
def test_fetch_data_with_metadata_merges_observations_and_metadata(tmp_cache_root):
    """The one-call wrapper must produce the same clean merge the documented
    two-call idiom does: unchanged row count against fetch_data() alone, more
    than fetch_data()'s own 16 columns, and no _x/_y suffixed column."""
    merged = fetch_data_with_metadata()
    observations = fetch_data()

    assert len(merged) == len(observations)
    assert len(merged.columns) > 16
    assert not any(c.endswith(("_x", "_y")) for c in merged.columns)
    # As above: this is what actually pins that the merge matched rather than
    # merely leaving the shape undamaged by a zero-match join.
    assert merged["METHODOLOGY_NOTES"].notna().mean() > 0.5
