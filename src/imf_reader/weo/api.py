"""IMF World Economic Outlook (WEO) API client."""

from datetime import datetime, timedelta
from io import StringIO

import pandas as pd
import requests

from imf_reader.config import logger
from imf_reader.weo import ValidMonths, Version
from imf_reader.cache.dataframe import dataframe_cache
from imf_reader.cache.legacy import _legacy_weo_api_clear_cache as clear_cache  # noqa: F401
from imf_reader.utils import make_get_request

# Standard scale labels
SCALE_LABELS = {
    0: "Units",
    6: "Millions",
    9: "Billions",
}

# Map scale exponents to multipliers (for converting to legacy format)
SCALE_MULTIPLIERS = {
    0: 1,
    6: 1_000_000,
    9: 1_000_000_000,
}


@dataframe_cache(ttl=timedelta(hours=1), sublayer="weo_api")
def _fetch_version_mapping() -> dict[Version, str]:
    """Fetch mapping of Version tuples to API version strings.

    Results are cached for 1 hour to avoid redundant HTTP calls (F10).

    Returns:
        Dict mapping (month, year) tuples to API version strings.
        e.g. {("October", 2025): "9.0.0", ("April", 2025): "6.0.0"}
    """
    url = "https://api.imf.org/external/sdmx/3.0/structure/dataflow/IMF.RES/WEO/*?detail=full"
    response = make_get_request(url)

    data = response.json()
    mapping: dict[Version, str] = {}

    for df in data.get("data", {}).get("dataflows", []):
        api_version = df["version"]
        last_updated = None

        for ann in df.get("annotations", []):
            if ann.get("id") == "lastUpdatedAt":
                try:
                    last_updated = datetime.fromisoformat(
                        ann["value"].replace("Z", "+00:00")
                    )
                except (ValueError, KeyError):
                    pass

        if last_updated:
            year = last_updated.year
            month: ValidMonths = "April" if last_updated.month < 7 else "October"
            mapping[(month, year)] = api_version

    return mapping


def get_weo_versions() -> list[Version]:
    """Fetch all available WEO versions from the IMF API.

    Returns:
        List of Version tuples (month, year) sorted newest first.
        e.g. [("October", 2025), ("April", 2025)]
    """
    mapping = _fetch_version_mapping()
    versions = list(mapping.keys())
    versions.sort(key=lambda v: (v[1], 0 if v[0] == "April" else 1), reverse=True)
    return versions


@dataframe_cache(ttl=timedelta(days=7), sublayer="weo_api")
def _fetch_codelist(agency: str, codelist_id: str) -> dict[str, str]:
    """Fetch a codelist from the IMF API and return as a code->label mapping.

    Results are cached locally to avoid repeated API calls.

    Args:
        agency: The agency ID (e.g., "IMF", "IMF.RES")
        codelist_id: The codelist ID (e.g., "CL_UNIT", "CL_WEO_COUNTRY")

    Returns:
        Dict mapping codes to their labels.
    """
    url = f"https://api.imf.org/external/sdmx/3.0/structure/codelist/{agency}/{codelist_id}"
    response = make_get_request(url)

    data = response.json()
    codelists = data.get("data", {}).get("codelists", [])
    if not codelists:
        return {}

    # Use the latest version
    cl = codelists[-1]
    # F9 fix: filter out None keys so missing "id" fields don't pollute the cache.
    result = {
        code.get("id"): code.get("name", code.get("names", {}).get("en", ""))
        for code in cl.get("codes", [])
        if code.get("id") is not None
    }

    return result


def _align_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Align the schema of the DataFrame to match the old SDMX format.

    Renames columns, adds label columns for codes, and fixes data types.

    Args:
        df: DataFrame from API.

    Returns:
        DataFrame with old-style column names, labels, and correct data types.
    """
    # Fetch codelists for labels (with caching)
    country_labels = _fetch_codelist("IMF.RES", "CL_WEO_COUNTRY")
    indicator_labels = _fetch_codelist("IMF.RES", "CL_WEO_INDICATOR")
    unit_labels = _fetch_codelist("IMF", "CL_UNIT")
    freq_labels = _fetch_codelist("IMF", "CL_FREQ")

    # Rename columns to match old format
    df = df.rename(
        columns={
            "COUNTRY": "REF_AREA_CODE",
            "INDICATOR": "CONCEPT_CODE",
            "UNIT": "UNIT_CODE",
            "FREQUENCY": "FREQ_CODE",
            "SCALE": "SCALE_CODE",
        }
    )

    # Add label columns
    df["REF_AREA_LABEL"] = df["REF_AREA_CODE"].map(country_labels)
    df["CONCEPT_LABEL"] = df["CONCEPT_CODE"].map(indicator_labels)
    df["UNIT_LABEL"] = df["UNIT_CODE"].map(unit_labels)
    df["FREQ_LABEL"] = df["FREQ_CODE"].map(freq_labels)
    df["SCALE_LABEL"] = df["SCALE_CODE"].map(SCALE_LABELS)

    # Add missing columns with empty data for backward compatibility
    df["LASTACTUALDATE"] = pd.array([pd.NA] * len(df), dtype="Int64")
    df["NOTES"] = pd.array([pd.NA] * len(df), dtype="string")

    # Convert values to match legacy format:
    # - Legacy format stores OBS_VALUE "in scale" (e.g., 447.416 for 447.416 billion)
    # - New API returns OBS_VALUE in units (e.g., 447416000000.0)
    # - Legacy SCALE_CODE is the multiplier (e.g., 1000000000), not the exponent (e.g., 9)

    # First, convert OBS_VALUE from units to "in scale" by dividing by 10^SCALE_CODE
    # Only apply where SCALE_CODE is present and > 0
    scale_exponent = pd.to_numeric(df["SCALE_CODE"], errors="coerce")
    has_scale = scale_exponent.notna() & (scale_exponent > 0)
    df.loc[has_scale, "OBS_VALUE"] = pd.to_numeric(
        df.loc[has_scale, "OBS_VALUE"], errors="coerce"
    ) / (10 ** scale_exponent[has_scale])

    # Convert SCALE_CODE from exponent to multiplier to match legacy format
    df["SCALE_CODE"] = scale_exponent.map(SCALE_MULTIPLIERS)

    # Fix data types to match old parser
    # Numeric columns
    df["OBS_VALUE"] = df["OBS_VALUE"].astype("Float64")
    df["SCALE_CODE"] = df["SCALE_CODE"].astype("Int64")
    df["TIME_PERIOD"] = pd.to_numeric(df["TIME_PERIOD"], errors="coerce").astype(
        "Int64"
    )

    # String columns
    string_columns = [
        "UNIT_CODE",
        "CONCEPT_CODE",
        "REF_AREA_CODE",
        "FREQ_CODE",
        "UNIT_LABEL",
        "CONCEPT_LABEL",
        "REF_AREA_LABEL",
        "FREQ_LABEL",
        "SCALE_LABEL",
    ]
    for col in string_columns:
        df[col] = df[col].astype("string")

    # Select and order columns to match old format
    output_columns = [
        "UNIT_CODE",
        "CONCEPT_CODE",
        "REF_AREA_CODE",
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

    return df[output_columns]


@dataframe_cache(ttl=timedelta(days=7), sublayer="weo_api")
def _get_weo_data_cached(version: Version) -> pd.DataFrame:
    """Inner cached fetch — keyed on a *resolved* (month, year) tuple.

    Splitting the cache from the public ``get_weo_data`` ensures that
    ``version=None`` is mapped to the current latest release before the cache
    lookup. Otherwise the wrapper would cache under ``None`` for 7 days and
    keep serving the previous release even after the version-mapping TTL
    (1 hour) sees a new one.
    """
    mapping = _fetch_version_mapping()

    if version not in mapping:
        raise ValueError(
            f"Version {version} not available. Available: {list(mapping.keys())}"
        )

    logger.info(f"Fetching WEO data from API: {version[0]} {version[1]}")
    api_version = mapping[version]
    url = f"https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES/WEO/{api_version}/*"

    # The data endpoint requires Accept: text/csv — make_get_request does not support
    # custom headers, so we call requests.get directly for this one call site.
    response = requests.get(url, headers={"Accept": "text/csv"})
    response.raise_for_status()

    df = pd.read_csv(StringIO(response.text), low_memory=False)
    return _align_schema(df)


def get_weo_data(version: Version | None = None) -> pd.DataFrame:
    """Fetch WEO data for a specific version.

    Data is cached locally to avoid repeated API calls. Use `clear_cache()` to clear.

    Args:
        version: Version tuple (month, year) e.g. ("April", 2025). If None, uses latest.

    Returns:
        DataFrame with WEO data.
    """
    if version is None:
        # Resolve to the concrete latest version BEFORE the cache lookup, so a
        # new release picked up by the 1-hour version-mapping TTL takes effect
        # immediately instead of being shadowed by a 7-day-TTL entry under None.
        mapping = _fetch_version_mapping()
        versions = list(mapping.keys())
        versions.sort(key=lambda v: (v[1], 0 if v[0] == "April" else 1), reverse=True)
        version = versions[0]

    return _get_weo_data_cached(version)


# Preserve the .cache_clear attribute on the public symbol so any caller that
# relied on get_weo_data.cache_clear() (the dataframe_cache contract) keeps
# working after the wrapper-vs-resolver split.
get_weo_data.cache_clear = _get_weo_data_cached.cache_clear  # type: ignore[attr-defined]
