"""Tests for weo translate module."""

import pandas as pd
import pytest

from imf_reader.weo import translate
from imf_reader.weo.api import OUTPUT_COLUMNS
from imf_reader.weo.vocabulary import API_AREA_TO_LEGACY

COUNTRY_LABELS = {"USA": "United States", "BEL": "Belgium"}
INDICATOR_LABELS = {"NGDP": "Gross domestic product (GDP), Current prices"}
UNIT_LABELS_API = {"XDC": "Domestic currency", "IX": "Index", "PE": "Persons"}

_CODELISTS = {
    ("IMF.RES", "CL_WEO_COUNTRY"): COUNTRY_LABELS,
    ("IMF.RES", "CL_WEO_INDICATOR"): INDICATOR_LABELS,
    ("IMF", "CL_UNIT"): UNIT_LABELS_API,
}


def _fake_fetch_codelist(agency: str, codelist_id: str) -> dict[str, str]:
    return _CODELISTS[(agency, codelist_id)]


def _legacy_frame(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal legacy SDMX-shaped frame.

    Fills the columns translation leaves untouched with defaults, so each
    test only needs to spell out the columns it's exercising.
    """
    defaults = {
        "FREQ_CODE": "A",
        "LASTACTUALDATE": pd.NA,
        "SCALE_CODE": 0,
        "NOTES": pd.NA,
        "TIME_PERIOD": 2024,
        "OBS_VALUE": 1.0,
        "UNIT_LABEL": "zip unit label",
        "CONCEPT_LABEL": "zip concept label",
        "REF_AREA_LABEL": "zip area label",
        "FREQ_LABEL": "Annual",
        "SCALE_LABEL": "Units",
    }
    df = pd.DataFrame([{**defaults, **row} for row in rows])
    df["REF_AREA_CODE"] = df["REF_AREA_CODE"].astype("Int64")
    df["OBS_VALUE"] = df["OBS_VALUE"].astype("Float64")
    return df


@pytest.fixture(autouse=True)
def _patch_codelists(monkeypatch):
    monkeypatch.setattr(translate, "_fetch_codelist", _fake_fetch_codelist)


class TestToApiVocabulary:
    """`to_api_vocabulary` translates identifier columns, leaving values alone."""

    def test_translates_codes_labels_and_dtypes(self):
        df = _legacy_frame(
            [{"REF_AREA_CODE": 111, "UNIT_CODE": "E", "CONCEPT_CODE": "NGDP"}]
        )

        result = translate.to_api_vocabulary(df)
        row = result.iloc[0]

        assert row["REF_AREA_CODE"] == "USA"
        assert row["UNIT_CODE"] == "XDC"
        assert row["REF_AREA_LABEL"] == "United States"
        assert row["CONCEPT_LABEL"] == "Gross domestic product (GDP), Current prices"
        assert row["UNIT_LABEL"] == "Domestic currency"
        assert row["REF_AREA_IMF_CODE"] == 111

        assert result["REF_AREA_CODE"].dtype == "string"
        assert result["UNIT_CODE"].dtype == "string"
        assert result["REF_AREA_IMF_CODE"].dtype == "Int64"

    @pytest.mark.parametrize(
        "legacy_code, api_code",
        [(111, "USA"), (123, "GX123"), (1, "G001"), (511, "G511")],
    )
    def test_pinned_area_code_literals(self, legacy_code, api_code):
        df = _legacy_frame(
            [{"REF_AREA_CODE": legacy_code, "UNIT_CODE": "E", "CONCEPT_CODE": "NGDP"}]
        )

        result = translate.to_api_vocabulary(df)

        assert result.iloc[0]["REF_AREA_CODE"] == api_code

    def test_le_letters_land_on_different_api_units(self):
        """A concept-keyed table would collapse these two; the pair-keyed table doesn't."""
        df = _legacy_frame(
            [
                {"REF_AREA_CODE": 111, "UNIT_CODE": "C", "CONCEPT_CODE": "LE"},
                {"REF_AREA_CODE": 111, "UNIT_CODE": "N", "CONCEPT_CODE": "LE"},
            ]
        )

        result = translate.to_api_vocabulary(df)

        assert result.iloc[0]["UNIT_CODE"] == "IX"
        assert result.iloc[1]["UNIT_CODE"] == "PE"

    def test_unit_pair_with_no_api_unit_becomes_na(self):
        df = _legacy_frame(
            [{"REF_AREA_CODE": 111, "UNIT_CODE": "O", "CONCEPT_CODE": "PSUGAEEC"}]
        )

        result = translate.to_api_vocabulary(df)

        assert pd.isna(result.iloc[0]["UNIT_CODE"])
        assert pd.isna(result.iloc[0]["UNIT_LABEL"])

    def test_unknown_unit_pair_raises(self):
        df = _legacy_frame(
            [{"REF_AREA_CODE": 111, "UNIT_CODE": "Z", "CONCEPT_CODE": "NOTREAL"}]
        )

        with pytest.raises(ValueError, match="NOTREAL"):
            translate.to_api_vocabulary(df)

    def test_unmapped_area_code_raises(self):
        df = _legacy_frame(
            [{"REF_AREA_CODE": 999999, "UNIT_CODE": "E", "CONCEPT_CODE": "NGDP"}]
        )

        with pytest.raises(ValueError, match="999999"):
            translate.to_api_vocabulary(df)

    def test_null_area_code_raises(self):
        """A null REF_AREA_CODE must raise, not silently map to <NA> in a key
        column -- the same failure mode an unmapped code raises for, and the one
        this module exists to prevent (see _translate_unit_code, its sibling,
        which already raises on a null (concept, unit) pair)."""
        df = _legacy_frame(
            [{"REF_AREA_CODE": pd.NA, "UNIT_CODE": "E", "CONCEPT_CODE": "NGDP"}]
        )

        with pytest.raises(ValueError, match="REF_AREA_CODE"):
            translate.to_api_vocabulary(df)

    def test_ref_area_imf_code_round_trips(self):
        df = _legacy_frame(
            [
                {"REF_AREA_CODE": 111, "UNIT_CODE": "E", "CONCEPT_CODE": "NGDP"},
                {"REF_AREA_CODE": 1, "UNIT_CODE": "E", "CONCEPT_CODE": "NGDP"},
            ]
        )

        result = translate.to_api_vocabulary(df)

        recovered = result["REF_AREA_CODE"].map(API_AREA_TO_LEGACY).astype("Int64")
        pd.testing.assert_series_equal(
            recovered, result["REF_AREA_IMF_CODE"], check_names=False
        )

    def test_legacy_only_aggregate_falls_back_to_generated_label_not_zip_column(self):
        """The fallback is LEGACY_ONLY_AREA_LABELS, not whatever the input frame's
        own REF_AREA_LABEL happened to say -- that value is deliberately different
        here to prove it isn't the one used."""
        df = _legacy_frame(
            [
                {
                    "REF_AREA_CODE": 511,
                    "UNIT_CODE": "E",
                    "CONCEPT_CODE": "NGDP",
                    "REF_AREA_LABEL": "some other label",
                }
            ]
        )

        result = translate.to_api_vocabulary(df)

        assert result.iloc[0]["REF_AREA_LABEL"] == "ASEAN-5"

    def test_drops_null_obs_value_rows(self):
        df = _legacy_frame(
            [
                {
                    "REF_AREA_CODE": 111,
                    "UNIT_CODE": "E",
                    "CONCEPT_CODE": "NGDP",
                    "OBS_VALUE": 1.0,
                },
                {
                    "REF_AREA_CODE": 111,
                    "UNIT_CODE": "E",
                    "CONCEPT_CODE": "NGDP",
                    "OBS_VALUE": pd.NA,
                },
            ]
        )

        result = translate.to_api_vocabulary(df)

        assert len(result) == 1

    def test_series_entirely_null_disappears(self):
        df = _legacy_frame(
            [
                {
                    "REF_AREA_CODE": 111,
                    "UNIT_CODE": "E",
                    "CONCEPT_CODE": "NGDP",
                    "OBS_VALUE": pd.NA,
                },
                {
                    "REF_AREA_CODE": 111,
                    "UNIT_CODE": "E",
                    "CONCEPT_CODE": "NGDP",
                    "OBS_VALUE": pd.NA,
                },
            ]
        )

        result = translate.to_api_vocabulary(df)

        assert result.empty

    def test_output_columns_match_api_path(self):
        df = _legacy_frame(
            [{"REF_AREA_CODE": 111, "UNIT_CODE": "E", "CONCEPT_CODE": "NGDP"}]
        )

        result = translate.to_api_vocabulary(df)

        assert list(result.columns) == OUTPUT_COLUMNS
