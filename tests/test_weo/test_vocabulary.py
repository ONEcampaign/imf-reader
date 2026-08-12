"""Tests for the generated weo vocabulary module.

Cheap regression cover for a generated file: checks internal consistency
(the inverse is a true inverse, no synthetic code collides with a real one,
every value has the shape callers expect) rather than pinning specific
table entries, so it survives a regeneration that adds a release.
"""

import re

from imf_reader.weo.vocabulary import (
    API_AREA_TO_LEGACY,
    LEGACY_AREA_TO_API,
    LEGACY_ONLY_AREA_LABELS,
    LEGACY_UNIT_TO_API,
    UNIT_PAIRS_WITH_NO_API_UNIT,
)

# The five (CONCEPT_CODE, legacy UNIT_CODE) pairs the maintainer decided have
# no correct API unit: four PPP/"international dollar" concepts the live API
# itself never publishes a unit for, plus PSUGAEEC/O (ambiguous at the label
# level, and moot since it never carries a non-null OBS_VALUE).
_PAIRS_WITH_NO_API_UNIT = {
    ("NGDPRPPPPC", "S"),
    ("PPPEX", "F"),
    ("PPPGDP", "T"),
    ("PPPPC", "T"),
    ("PSUGAEEC", "O"),
}

# API area codes are either a plain ISO3 (country) or an aggregate: "G" or
# "GX" followed by the zero-padded 3-digit legacy numeric code.
_AREA_CODE_SHAPE = re.compile(r"^([A-Z]{3}|GX?\d{3})$")

# The 13 aggregates whose API code is algorithmically derived from the legacy
# numeric code: "G" + zero-padded 3 digits, except 123 which is "GX123".
_ALGORITHMIC_AGGREGATES = {
    1: "G001",
    110: "G110",
    119: "G119",
    123: "GX123",
    163: "G163",
    200: "G200",
    205: "G205",
    400: "G400",
    505: "G505",
    510: "G510",
    603: "G603",
    903: "G903",
    998: "G998",
}


class TestLegacyAreaToApi:
    """Tests for LEGACY_AREA_TO_API."""

    def test_not_empty(self):
        assert len(LEGACY_AREA_TO_API) > 200

    def test_keys_are_int(self):
        assert all(isinstance(k, int) for k in LEGACY_AREA_TO_API)

    def test_values_match_area_code_shape(self):
        bad = {
            k: v for k, v in LEGACY_AREA_TO_API.items() if not _AREA_CODE_SHAPE.match(v)
        }
        assert bad == {}

    def test_values_are_unique(self):
        """A 1:1 mapping: no two legacy codes should collapse onto one API code."""
        values = list(LEGACY_AREA_TO_API.values())
        assert len(values) == len(set(values))

    def test_algorithmic_aggregates_follow_the_stated_convention(self):
        for legacy_code, expected_api_code in _ALGORITHMIC_AGGREGATES.items():
            assert LEGACY_AREA_TO_API[legacy_code] == expected_api_code

    def test_legacy_only_aggregates_present_and_synthetic(self):
        """The four aggregates with no real API counterpart use the same
        "G" + zero-padded convention as the algorithmic ones, one code per
        legacy numeric code."""
        for legacy_code in (406, 440, 511, 901):
            api_code = LEGACY_AREA_TO_API[legacy_code]
            assert api_code == f"G{legacy_code:03d}"
            assert api_code in LEGACY_ONLY_AREA_LABELS


class TestApiAreaToLegacy:
    """Tests for API_AREA_TO_LEGACY as the strict inverse of LEGACY_AREA_TO_API."""

    def test_is_strict_inverse(self):
        expected = {api: legacy for legacy, api in LEGACY_AREA_TO_API.items()}
        assert API_AREA_TO_LEGACY == expected

    def test_same_length_as_forward_map(self):
        """A collision in the forward map would silently shrink the inverse."""
        assert len(API_AREA_TO_LEGACY) == len(LEGACY_AREA_TO_API)

    def test_no_synthetic_code_collides_with_a_real_one(self):
        """Each of the four synthetic aggregate codes round-trips to exactly
        the legacy code it was assigned from, never to a different one."""
        for legacy_code in (406, 440, 511, 901):
            synthetic = f"G{legacy_code:03d}"
            assert API_AREA_TO_LEGACY[synthetic] == legacy_code


class TestLegacyOnlyAreaLabels:
    """Tests for LEGACY_ONLY_AREA_LABELS."""

    def test_exactly_the_four_known_aggregates(self):
        assert set(LEGACY_ONLY_AREA_LABELS) == {"G406", "G440", "G511", "G901"}

    def test_values_are_non_empty_labels(self):
        assert all(isinstance(v, str) and v for v in LEGACY_ONLY_AREA_LABELS.values())


class TestLegacyUnitToApi:
    """Tests for LEGACY_UNIT_TO_API."""

    def test_not_empty(self):
        assert len(LEGACY_UNIT_TO_API) > 100

    def test_keys_are_concept_letter_pairs(self):
        for key in LEGACY_UNIT_TO_API:
            assert isinstance(key, tuple)
            assert len(key) == 2
            concept, letter = key
            assert isinstance(concept, str) and concept
            # Legacy unit codes in the SDMX schema are single letters.
            assert isinstance(letter, str) and len(letter) == 1 and letter.isalpha()

    def test_values_are_non_empty_api_unit_codes(self):
        assert all(isinstance(v, str) and v for v in LEGACY_UNIT_TO_API.values())

    def test_le_letters_map_to_different_api_units(self):
        """LE is keyed on (concept, letter), not concept alone: letter C
        (country groups) and letter N (countries) must land on different API
        units, the case a concept-keyed table would get wrong."""
        assert LEGACY_UNIT_TO_API[("LE", "C")] != LEGACY_UNIT_TO_API.get(("LE", "N"))

    def test_le_and_lp_persons_pairs_map_to_pe(self):
        """CL_UNIT's exact "Persons" match, picked by the maintainer for the
        two pairs where the live API never publishes a unit at all."""
        assert LEGACY_UNIT_TO_API[("LE", "N")] == "PE"
        assert LEGACY_UNIT_TO_API[("LP", "N")] == "PE"

    def test_disjoint_from_pairs_with_no_api_unit(self):
        """A pair is either translated or deliberately null, never both."""
        assert LEGACY_UNIT_TO_API.keys().isdisjoint(UNIT_PAIRS_WITH_NO_API_UNIT)


class TestUnitPairsWithNoApiUnit:
    """Tests for UNIT_PAIRS_WITH_NO_API_UNIT.

    Membership here means the IMF's own API publishes no unit for the
    concept -- a deliberate null the maintainer decided on, not a gap the
    generator failed to resolve.
    """

    def test_is_a_frozenset(self):
        assert isinstance(UNIT_PAIRS_WITH_NO_API_UNIT, frozenset)

    def test_exactly_the_five_known_pairs(self):
        assert UNIT_PAIRS_WITH_NO_API_UNIT == _PAIRS_WITH_NO_API_UNIT

    def test_absent_from_legacy_unit_to_api(self):
        for pair in UNIT_PAIRS_WITH_NO_API_UNIT:
            assert pair not in LEGACY_UNIT_TO_API
