"""Translate legacy SDMX WEO output into the api.imf.org identifier vocabulary.

The bulk SDMX archive (April 2019 - April 2025) and api.imf.org (April 2025
onward) agree on observation values but use different area, unit, and label
vocabularies. This module maps the SDMX side forward onto the API side, so
frames from any two releases can be concatenated.
"""

import pandas as pd

from imf_reader.weo._shared import _drop_empty_observations
from imf_reader.weo.api import OUTPUT_COLUMNS, _fetch_codelist
from imf_reader.weo.vocabulary import (
    LEGACY_AREA_TO_API,
    LEGACY_ONLY_AREA_LABELS,
    LEGACY_UNIT_TO_API,
    UNIT_PAIRS_WITH_NO_API_UNIT,
)


def to_api_vocabulary(df: pd.DataFrame) -> pd.DataFrame:
    """Translate a legacy SDMX WEO frame into the api.imf.org vocabulary.

    Maps ``REF_AREA_CODE`` and ``UNIT_CODE`` onto the api.imf.org vocabulary
    and re-derives ``REF_AREA_LABEL``, ``UNIT_LABEL`` and ``CONCEPT_LABEL``
    from the same codelists the API path reads, so the two paths cannot
    drift. ``OBS_VALUE`` and ``SCALE_CODE`` are untouched -- this is confined
    to identifier columns.

    Adds ``REF_AREA_IMF_CODE``, carrying the pre-translation legacy area code
    for each row. It is a compatibility column, slated for removal in 3.0.

    Args:
        df: A DataFrame as returned by ``SDMXParser.parse``, in the legacy
            SDMX vocabulary.

    Returns:
        The DataFrame translated into the api.imf.org vocabulary.

    Raises:
        ValueError: A ``REF_AREA_CODE`` or ``(CONCEPT_CODE, UNIT_CODE)`` pair
            has no entry in the generated vocabulary tables.
    """
    df = _drop_empty_observations(df)

    df["REF_AREA_IMF_CODE"] = df["REF_AREA_CODE"].astype("Int64")
    df["REF_AREA_CODE"] = _translate_area_code(df["REF_AREA_CODE"])
    df["UNIT_CODE"] = _translate_unit_code(df["CONCEPT_CODE"], df["UNIT_CODE"])

    country_labels = _fetch_codelist("IMF.RES", "CL_WEO_COUNTRY")
    indicator_labels = _fetch_codelist("IMF.RES", "CL_WEO_INDICATOR")
    unit_labels = _fetch_codelist("IMF", "CL_UNIT")

    # The codelist has no entry for the four legacy-only aggregates (e.g.
    # G406); fall back to their zip-derived labels for those.
    df["REF_AREA_LABEL"] = (
        df["REF_AREA_CODE"]
        .map(country_labels)
        .fillna(df["REF_AREA_CODE"].map(LEGACY_ONLY_AREA_LABELS))
        .astype("string")
    )
    df["UNIT_LABEL"] = df["UNIT_CODE"].map(unit_labels).astype("string")
    df["CONCEPT_LABEL"] = df["CONCEPT_CODE"].map(indicator_labels).astype("string")

    # The bulk XML's series attributes are exactly UNIT, CONCEPT, REF_AREA,
    # FREQ, LASTACTUALDATE, SCALE, NOTES -- there is no per-country revision
    # date to carry, so this column is always null on the bulk path. dtype is
    # pinned to datetime64[us] (not left to pandas' inferred default) so it
    # stays byte-identical to the API path's parsed COUNTRY_UPDATE_DATE column.
    df["COUNTRY_UPDATE_DATE"] = pd.Series(
        pd.NaT, index=df.index, dtype="datetime64[us]"
    )

    return df[OUTPUT_COLUMNS]


def _translate_area_code(area_codes: pd.Series) -> pd.Series:
    """Map legacy numeric area codes onto the api.imf.org vocabulary.

    Does not ``dropna()`` before checking, unlike a plain set difference would
    tempt: a null area code would otherwise map silently to ``<NA>`` in a key
    column, which is the failure this module exists to prevent (see
    ``_translate_unit_code``, which raises on a null pair for the same reason).

    Raises:
        ValueError: An area code is null, or has no entry in
            ``LEGACY_AREA_TO_API``.
    """
    unmapped = set(area_codes) - set(LEGACY_AREA_TO_API)
    if unmapped:
        raise ValueError(
            f"No API area mapping for legacy REF_AREA_CODE values: {sorted(unmapped, key=str)}"
        )
    return area_codes.map(LEGACY_AREA_TO_API).astype("string")


def _translate_unit_code(concept_codes: pd.Series, unit_codes: pd.Series) -> pd.Series:
    """Map legacy ``(CONCEPT_CODE, UNIT_CODE)`` pairs onto the api.imf.org vocabulary.

    Keyed on the pair, not the unit letter alone, since the same legacy
    letter means different things in different concepts (``LE``'s ``C`` and
    ``N`` are both "Index"-adjacent legacy units but land on different API
    units). A pair with no API unit at all (``UNIT_PAIRS_WITH_NO_API_UNIT``)
    becomes ``pd.NA``; any other unmapped pair raises, since silently
    emitting ``<NA>`` for an unknown pair would corrupt a key column instead
    of failing loudly.

    Raises:
        ValueError: A pair is in neither ``LEGACY_UNIT_TO_API`` nor
            ``UNIT_PAIRS_WITH_NO_API_UNIT``.
    """
    pairs = pd.Series(
        list(zip(concept_codes, unit_codes, strict=True)), index=concept_codes.index
    )
    known = set(LEGACY_UNIT_TO_API) | set(UNIT_PAIRS_WITH_NO_API_UNIT)
    unmapped = set(pairs) - known
    if unmapped:
        raise ValueError(
            "No API unit mapping for (CONCEPT_CODE, UNIT_CODE) pairs: "
            f"{sorted(unmapped)}"
        )
    return pairs.map(LEGACY_UNIT_TO_API).astype("string")
