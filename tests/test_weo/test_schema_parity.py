"""Live acceptance test that the API and SDMX paths agree on April 2025.

April 2025 is the one release both paths can serve: the bulk SDMX archive's
last release, and the API's earliest. design-schema.md §4.8 calls this out as
the only test that would catch the IMF renaming a codelist entry -- unit tests
patch ``_fetch_codelist``, so they can't see a real rename; this test can't,
because it fetches both.
"""

import os

import pandas as pd
import pytest

from imf_reader.weo.api import OUTPUT_COLUMNS, get_weo_data
from imf_reader.weo.reader import _fetch

# Columns whose values place a real-world observation: shared identity across
# both paths, established independently of the translation logic under test.
KEY_COLUMNS = ["REF_AREA_CODE", "CONCEPT_CODE", "FREQ_CODE", "TIME_PERIOD"]

# NOTES and LASTACTUALDATE are a documented divergence (design-schema.md §1.10):
# the API never populates observation-level notes or last-actual-date, so the
# SDMX path always has data there that the API path never does. Comparing them
# would fail on every run for a reason unrelated to what this test guards.
UNCOMPARABLE_COLUMNS = ["NOTES", "LASTACTUALDATE"]

# UNIT_CODE/UNIT_LABEL are compared only where the API's own raw CSV populates
# UNIT. For seven concepts whose unit is implicit (LE, LP, LUR, NGDPRPPPPC,
# PPPEX, PPPGDP, PPPPC -- population counts, percentages, PPP conversions), the
# API leaves UNIT null on ~54k rows even though OBS_VALUE is present. Verified
# against the raw API CSV, so it is the API's own data rather than something
# _align_schema or to_api_vocabulary drops.
#
# LE, LP and LUR therefore carry a unit on the SDMX side (PE, PT) and none on
# the API side. That is an accepted divergence between the two paths, not an
# oversight: the exact fill would need a (concept, area) table derived from the
# frozen SDMX archive, which would go stale for every area a future API release
# adds. It is documented in the changelog and the README's coverage notes, and
# this exclusion is what lets the rest of the parity assertion stay strict.
UNIT_COLUMNS = ["UNIT_CODE", "UNIT_LABEL"]

VALUE_COLUMNS = [
    c
    for c in OUTPUT_COLUMNS
    if c not in KEY_COLUMNS and c not in UNCOMPARABLE_COLUMNS and c not in UNIT_COLUMNS
]


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("IMF_READER_LIVE_TESTS") != "1",
    reason="hits the real IMF API and CDN; set IMF_READER_LIVE_TESTS=1 to run",
)
def test_april_2025_matches_across_both_paths(tmp_cache_root):
    """Fetch April 2025 through the API and the SDMX-then-translate pipeline,
    and assert they describe the same 353,544 observations."""
    api_df = get_weo_data(("April", 2025))
    sdmx_df = _fetch(("April", 2025))  # scrape -> parse -> to_api_vocabulary

    assert api_df.shape == sdmx_df.shape == (353_544, len(OUTPUT_COLUMNS))
    assert list(api_df.columns) == list(sdmx_df.columns) == OUTPUT_COLUMNS
    for col in OUTPUT_COLUMNS:
        assert api_df[col].dtype == sdmx_df[col].dtype, f"{col} dtype mismatch"

    # Row order is incidental (API return order vs. the SDMX grid's own order),
    # so match observations by key rather than trust row position.
    assert not api_df.duplicated(subset=KEY_COLUMNS).any()
    assert not sdmx_df.duplicated(subset=KEY_COLUMNS).any()

    merged = api_df.merge(
        sdmx_df,
        on=KEY_COLUMNS,
        how="outer",
        suffixes=("_api", "_sdmx"),
        indicator=True,
    )
    only_one_side = merged.loc[merged["_merge"] != "both", [*KEY_COLUMNS, "_merge"]]
    assert only_one_side.empty, (
        f"paths disagree on which observations exist:\n{only_one_side}"
    )

    for col in VALUE_COLUMNS:
        pd.testing.assert_series_equal(
            merged[f"{col}_api"],
            merged[f"{col}_sdmx"],
            check_names=False,
            check_index_type=False,
        )

    # See UNIT_COLUMNS above: restricted to rows where the API itself supplies a
    # unit, since a null there reflects the API's own data, not a translation gap.
    api_has_unit = merged["UNIT_CODE_api"].notna()
    for col in UNIT_COLUMNS:
        pd.testing.assert_series_equal(
            merged.loc[api_has_unit, f"{col}_api"],
            merged.loc[api_has_unit, f"{col}_sdmx"],
            check_names=False,
            check_index_type=False,
        )
