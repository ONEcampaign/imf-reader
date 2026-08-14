"""IMF World Economic Outlook (WEO) API client."""

import re
from datetime import timedelta
from io import StringIO
from typing import NamedTuple

import pandas as pd

from imf_reader.cache.dataframe import dataframe_cache
from imf_reader.cache.legacy import (
    _legacy_weo_api_clear_cache as clear_cache,  # noqa: F401
)
from imf_reader.config import VersionNotAvailableError, logger
from imf_reader.utils import make_get_request
from imf_reader.weo import ValidMonths, Version
from imf_reader.weo._shared import _drop_empty_observations
from imf_reader.weo.scraper import KNOWN_CORRUPT_RELEASES, SDMX_RELEASES
from imf_reader.weo.vocabulary import API_AREA_TO_LEGACY

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

# Column order both WEO paths (this module and weo/translate.py) return, so
# frames from either can be concatenated without reindexing.
OUTPUT_COLUMNS = [
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
    # Appended, not inserted: positional access on the first 15 columns is
    # live in the wild, so a new column only ever goes on the end.
    "COUNTRY_UPDATE_DATE",
]


class FlowRef(NamedTuple):
    """Which dataflow serves a WEO release: the bare ``WEO`` flow, or an
    archival ``WEO_YYYY_MON_VINTAGE`` flow, and which of its versions."""

    dataflow_id: str  # "WEO" or "WEO_2025_OCT_VINTAGE"
    version: str  # "9.0.0"


# Matches archival vintage dataflow ids, e.g. "WEO_2025_OCT_VINTAGE".
# Group 1 is the year, group 2 is the 3-letter month code.
_VINTAGE_ID_RE = re.compile(r"^WEO_(\d{4})_([A-Z]{3})_VINTAGE$")
_VINTAGE_MONTH_CODES: dict[str, ValidMonths] = {"APR": "April", "OCT": "October"}


def _version_sort_key(api_version: str) -> tuple[int, ...]:
    """Parse a dotted version string ("9.0.0") into a tuple that sorts
    numerically rather than lexicographically ("10.0.0" > "9.0.0")."""
    try:
        return tuple(int(part) for part in api_version.split("."))
    except ValueError:
        return (0,)


def _flow_precedence(ref: FlowRef) -> tuple[bool, tuple[int, ...]]:
    """Collision-resolution sort key: a bare WEO flow outranks a vintage,
    then a higher dataflow version outranks a lower one. Old bare versions
    stay live and serving data, so preferring them keeps behaviour stable as
    vintages accumulate."""
    return (ref.dataflow_id == "WEO", _version_sort_key(ref.version))


def _probe_publication_date(dataflow_id: str, api_version: str) -> Version:
    """Label one dataflow version by probing its ``PUBLICATION_DATE`` attribute.

    The ``lastUpdatedAt`` structure annotation is deliberately not used here:
    it is inverted on live flows, which is the source of the version
    mislabelling this probe exists to fix. The probe is a single-observation
    request (~0.5s) and sits under the same 1-hour mapping cache and 1-day
    HTTP cache as the rest of this module, so the cost is nil.

    Raises:
        ConnectionError: network/HTTP failure (via ``make_get_request``).
        ValueError: a 200 response with no rows or no ``PUBLICATION_DATE``
            column -- also counts as a probe failure.
    """
    url = (
        "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES/"
        f"{dataflow_id}/{api_version}/USA.NGDP_RPCH.A"
        "?attributes=dataset&lastNObservations=1"
    )
    response = make_get_request(url, headers={"Accept": "text/csv"})
    probe_df = pd.read_csv(StringIO(response.text))

    if probe_df.empty or "PUBLICATION_DATE" not in probe_df.columns:
        raise ValueError(
            f"PUBLICATION_DATE probe returned no usable data for "
            f"{dataflow_id} {api_version}"
        )

    published = pd.to_datetime(probe_df["PUBLICATION_DATE"].iloc[0])
    month: ValidMonths = "April" if published.month < 7 else "October"
    return (month, published.year)


@dataframe_cache(ttl=timedelta(hours=1), sublayer="weo_api")
def _fetch_flow_mapping() -> dict[Version, FlowRef]:
    """Fetch mapping of Version tuples to the FlowRef that serves them.

    Discovers every version of every ``WEO`` and ``WEO_YYYY_MON_VINTAGE``
    dataflow under ``IMF.RES``, then labels each by probing its
    ``PUBLICATION_DATE`` attribute (see ``_probe_publication_date``) rather
    than trusting the ``lastUpdatedAt`` annotation, which is inverted on live
    flows.

    Failure policy is deliberately asymmetric: a bare ``WEO`` flow determines
    "latest", so a probe failure on one raises -- silently dropping it would
    make ``fetch_data()`` return an older release with no signal. A vintage
    flow is an archival extra, so a probe failure on one falls back to an
    id-derived label, and only skips the flow (with a warning) if the id
    itself does not parse.

    Results are cached for 1 hour to avoid redundant HTTP calls.

    Returns:
        Dict mapping (month, year) tuples to FlowRef(dataflow_id, version).
        e.g. {("October", 2025): FlowRef("WEO_2025_OCT_VINTAGE", "1.0.0"),
              ("April", 2026): FlowRef("WEO", "9.0.0")}
    """
    url = "https://api.imf.org/external/sdmx/3.0/structure/dataflow/IMF.RES/*/*?detail=allstubs"
    response = make_get_request(url)
    data = response.json()

    candidates: list[tuple[str, str]] = []
    for df_stub in data.get("data", {}).get("dataflows", []):
        flow_id = df_stub.get("id", "")
        if flow_id == "WEO" or _VINTAGE_ID_RE.match(flow_id):
            candidates.append((flow_id, df_stub.get("version", "")))

    mapping: dict[Version, FlowRef] = {}

    for flow_id, api_version in candidates:
        is_bare = flow_id == "WEO"
        try:
            key = _probe_publication_date(flow_id, api_version)
        except Exception:
            if is_bare:
                raise

            match = _VINTAGE_ID_RE.match(flow_id)
            month = _VINTAGE_MONTH_CODES.get(match.group(2)) if match else None
            if match is None or month is None:
                logger.warning(
                    "Skipping WEO vintage flow %s %s: PUBLICATION_DATE probe "
                    "failed and its id does not parse into a label",
                    flow_id,
                    api_version,
                )
                continue

            key = (month, int(match.group(1)))
            logger.warning(
                "PUBLICATION_DATE probe failed for vintage flow %s %s; "
                "falling back to its id-derived label %s",
                flow_id,
                api_version,
                key,
            )

        candidate_ref = FlowRef(flow_id, api_version)
        incumbent = mapping.get(key)
        if incumbent is not None:
            winner, loser = sorted(
                (incumbent, candidate_ref), key=_flow_precedence, reverse=True
            )
            logger.debug("Version collision at %s: %s wins over %s", key, winner, loser)
            candidate_ref = winner
        mapping[key] = candidate_ref

    return mapping


def get_weo_versions() -> list[Version]:
    """Fetch all WEO versions this package can serve.

    This is the union of the API's dataflow mapping and the discontinued SDMX
    bulk archive (``scraper.SDMX_RELEASES``), minus the two releases that are
    corrupt in the IMF's own published archive (``scraper.KNOWN_CORRUPT_RELEASES``).
    It is not merely what the API reports: ``get_weo_data(version=None)`` resolves
    "latest" against the API mapping alone, so a version appearing here is not a
    guarantee that ``get_weo_data`` can fetch it — the SDMX-only releases go
    through ``fetch_data``'s scraper fallback instead.

    Returns:
        List of Version tuples (month, year) sorted newest first.
        e.g. [("October", 2025), ("April", 2025), ..., ("April", 2019)]
    """
    mapping = _fetch_flow_mapping()
    versions = (set(mapping.keys()) | set(SDMX_RELEASES)) - KNOWN_CORRUPT_RELEASES
    result = list(versions)
    result.sort(key=lambda v: (v[1], 0 if v[0] == "April" else 1), reverse=True)
    return result


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
        logger.warning(
            "Codelist %s/%s returned no codelists (empty response or a "
            "renamed codelist id); every column that maps through it will "
            "come back null",
            agency,
            codelist_id,
        )
        return {}

    # Use the latest version
    cl = codelists[-1]
    # Filter out None keys so missing "id" fields don't pollute the cache.
    result = {
        code.get("id"): code.get("name", code.get("names", {}).get("en", ""))
        for code in cl.get("codes", [])
        if code.get("id") is not None
    }

    return result


# Columns pulled from the series metadata sidecar and the key that joins
# them onto the main data frame.
_METADATA_JOIN_KEYS = ["COUNTRY", "INDICATOR", "FREQUENCY"]
_METADATA_COLUMNS = [
    *_METADATA_JOIN_KEYS,
    "LATEST_ACTUAL_ANNUAL_DATA",
    "METHODOLOGY_NOTES",
    "COUNTRY_UPDATE_DATE",
]

# LATEST_ACTUAL_ANNUAL_DATA is either a plain year ("2024") or a fiscal-year
# form ("FY2023/24", 10.7% of populated series -- the bulk archive has no FY
# forms at all). Group 1 catches the FY form's leading year, group 2 the
# plain form; anything else matches neither and becomes <NA>.
_LATEST_ACTUAL_ANNUAL_DATA_RE = re.compile(r"^(?:FY(\d{4})/\d{2}|(\d{4}))$")


@dataframe_cache(ttl=timedelta(days=7), sublayer="weo_api")
def _fetch_series_metadata(ref: FlowRef) -> pd.DataFrame:
    """Fetch series-level metadata for one dataflow: one row per (country,
    indicator, frequency).

    Uses the ``attributes=series&firstNObservations=1`` sidecar (~300 KB on
    the wire) rather than reading metadata off the main data CSV: the main
    fetch's default attribute set is not a stable column set across dataflow
    versions -- it moves release to release as the IMF's DSD changes -- so
    every metadata column this package publishes comes from this sidecar
    uniformly, never from whatever the primary fetch happens to carry.

    Returns only the columns this package uses, so the cached parquet stays
    small; the caller (``_align_schema``) is responsible for parsing and
    renaming them.

    Results are cached for 7 days, matching the primary data fetch's TTL.
    """
    url = (
        "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES/"
        f"{ref.dataflow_id}/{ref.version}/*"
        "?attributes=series&firstNObservations=1"
    )
    # use_http_cache=False: this CSV already sits under the 7-day parquet
    # cache above, so a second copy in the HTTP cache is waste.
    response = make_get_request(
        url, headers={"Accept": "text/csv"}, use_http_cache=False
    )
    df = pd.read_csv(StringIO(response.text), low_memory=False)
    return df[_METADATA_COLUMNS]


def _parse_latest_actual_annual_data(raw: pd.Series) -> pd.Series:
    """Parse LATEST_ACTUAL_ANNUAL_DATA to the leading year, as an Int64.

    A fiscal-year form (``FY2023/24``) and a plain year (``2024``) both parse
    to the same integer, since the bulk XML's LASTACTUALDATE this column
    feeds has no FY forms at all -- collapsing the distinction is what makes
    the two paths semantically identical. Anything else becomes <NA>.
    """
    text = raw.astype("string")
    extracted = text.str.extract(_LATEST_ACTUAL_ANNUAL_DATA_RE)
    year = extracted[0].fillna(extracted[1])

    unparsed = text[year.isna() & text.notna()]
    if not unparsed.empty:
        logger.debug(
            "LATEST_ACTUAL_ANNUAL_DATA: %d values matched neither the plain-"
            "year nor fiscal-year form and became <NA>; distinct tokens: %s",
            len(unparsed),
            sorted(unparsed.unique()),
        )

    return pd.to_numeric(year, errors="coerce").astype("Int64")


def _parse_country_update_date(raw: pd.Series) -> pd.Series:
    """Parse the sidecar's US-format COUNTRY_UPDATE_DATE strings (e.g.
    ``9/19/2025``).

    The format is explicit rather than inferred, and the result is pinned to
    ``datetime64[us]`` rather than left to whatever resolution
    ``pd.to_datetime`` defaults to: on pandas 3 that default is already
    ``[us]``, but pinning it explicitly keeps this column byte-identical to
    the bulk path's all-null ``datetime64[us]`` column (``translate.py``)
    even if a future pandas release changes its default.
    """
    return pd.to_datetime(raw, format="%m/%d/%Y", errors="coerce").astype(
        "datetime64[us]"
    )


def _with_null_metadata_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Fill LASTACTUALDATE/NOTES/COUNTRY_UPDATE_DATE with nulls of the
    correct dtype -- what ships when the metadata sidecar can't be trusted.

    This is the same null result existing callers of the API path already
    see for the first two columns, so degrading here does not regress
    anything they depend on.
    """
    df["LASTACTUALDATE"] = pd.array([pd.NA] * len(df), dtype="Int64")
    df["NOTES"] = pd.array([pd.NA] * len(df), dtype="string")
    df["COUNTRY_UPDATE_DATE"] = pd.Series(
        pd.NaT, index=df.index, dtype="datetime64[us]"
    )
    return df


def _join_series_metadata(df: pd.DataFrame, ref: FlowRef) -> pd.DataFrame:
    """Left-join LASTACTUALDATE/NOTES/COUNTRY_UPDATE_DATE from the series
    metadata sidecar onto ``df``, on (COUNTRY, INDICATOR, FREQUENCY).

    Degrades to null columns of the right dtype -- logging a warning, never
    raising -- on any sidecar failure (network, parse, missing columns) or on
    a duplicated join key. A duplicated key would fan ``df`` out and
    fabricate observations, which is a worse failure than missing metadata,
    so the sidecar is dropped entirely rather than merged with
    ``merge(validate=...)``: that raises, which would fail the whole call for
    an annotation. The caller wants its observations; an annotation sidecar
    must never be allowed to take that down.
    """
    try:
        meta = _fetch_series_metadata(ref)
    except Exception as exc:
        logger.warning(
            "Failed to fetch series metadata for %s %s: %s; LASTACTUALDATE, "
            "NOTES and COUNTRY_UPDATE_DATE will be null",
            ref.dataflow_id,
            ref.version,
            exc,
        )
        return _with_null_metadata_columns(df)

    if meta.duplicated(subset=_METADATA_JOIN_KEYS).any():
        logger.warning(
            "Series metadata sidecar for %s %s has duplicate %s keys; "
            "dropping it entirely rather than merging, since a duplicated "
            "key would fan out observations",
            ref.dataflow_id,
            ref.version,
            _METADATA_JOIN_KEYS,
        )
        return _with_null_metadata_columns(df)

    # The main fetch's own default attribute set is not a stable column set
    # across dataflow versions (WEO 6.0.0's DSD carries
    # LATEST_ACTUAL_ANNUAL_DATA, WEO 9.0.0's carries COUNTRY_UPDATE_DATE,
    # neither carries both) -- so ``df`` may already have a raw copy of one
    # of the sidecar's columns. Drop it before merging: every metadata value
    # this package publishes must come from the sidecar uniformly, never
    # from whatever the main CSV happens to carry, and left unmerged that
    # copy would collide with the sidecar's during the join and pandas would
    # suffix both instead of leaving a plain COUNTRY_UPDATE_DATE column.
    sidecar_value_columns = [c for c in meta.columns if c not in _METADATA_JOIN_KEYS]
    df = df.drop(columns=[c for c in sidecar_value_columns if c in df.columns])

    df = df.merge(meta, on=_METADATA_JOIN_KEYS, how="left")
    df["LASTACTUALDATE"] = _parse_latest_actual_annual_data(
        df.pop("LATEST_ACTUAL_ANNUAL_DATA")
    )
    df["NOTES"] = df.pop("METHODOLOGY_NOTES").astype("string")
    df["COUNTRY_UPDATE_DATE"] = _parse_country_update_date(df["COUNTRY_UPDATE_DATE"])
    return df


def _align_schema(df: pd.DataFrame, ref: FlowRef) -> pd.DataFrame:
    """Align the schema of the DataFrame to match the old SDMX format.

    Renames columns, adds label columns for codes, joins series metadata,
    and fixes data types.

    Adds ``REF_AREA_IMF_CODE``, a compatibility column carrying the legacy IMF
    numeric area code for each row (null for areas with no legacy code, e.g.
    ``LIE``). It exists so code migrating off the numeric ``REF_AREA_CODE``
    has a one-line path to it; it is slated for removal in 3.0.

    Args:
        df: DataFrame from API.
        ref: Which dataflow served ``df`` -- threaded through to the series
            metadata sidecar fetch (``_fetch_series_metadata``).

    Returns:
        DataFrame with old-style column names, labels, and correct data types.
    """
    df = _drop_empty_observations(df)
    df = _join_series_metadata(df, ref)

    # Fetch codelists for labels (with caching)
    country_labels = _fetch_codelist("IMF.RES", "CL_WEO_COUNTRY")
    indicator_labels = _fetch_codelist("IMF.RES", "CL_WEO_INDICATOR")
    unit_labels = _fetch_codelist("IMF", "CL_UNIT")
    freq_labels = _fetch_codelist("IMF", "CL_FREQ")

    df = df.rename(
        columns={
            "COUNTRY": "REF_AREA_CODE",
            "INDICATOR": "CONCEPT_CODE",
            "UNIT": "UNIT_CODE",
            "FREQUENCY": "FREQ_CODE",
            "SCALE": "SCALE_CODE",
        }
    )

    df["REF_AREA_IMF_CODE"] = (
        df["REF_AREA_CODE"].map(API_AREA_TO_LEGACY).astype("Int64")
    )

    df["REF_AREA_LABEL"] = df["REF_AREA_CODE"].map(country_labels)
    df["CONCEPT_LABEL"] = df["CONCEPT_CODE"].map(indicator_labels)
    df["UNIT_LABEL"] = df["UNIT_CODE"].map(unit_labels)
    df["FREQ_LABEL"] = df["FREQ_CODE"].map(freq_labels)
    df["SCALE_LABEL"] = df["SCALE_CODE"].map(SCALE_LABELS)

    # LASTACTUALDATE, NOTES and COUNTRY_UPDATE_DATE are already populated by
    # _join_series_metadata above (or nulled out at the right dtype if the
    # sidecar failed) -- nothing left to do for them here.

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
    df["OBS_VALUE"] = df["OBS_VALUE"].astype("Float64")
    df["SCALE_CODE"] = df["SCALE_CODE"].astype("Int64")
    df["TIME_PERIOD"] = pd.to_numeric(df["TIME_PERIOD"], errors="coerce").astype(
        "Int64"
    )

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

    return df[OUTPUT_COLUMNS]


@dataframe_cache(ttl=timedelta(days=7), sublayer="weo_api")
def _get_weo_data_cached(version: Version, ref: FlowRef) -> pd.DataFrame:
    """Inner cached fetch — keyed on a *resolved* (month, year) tuple AND the
    FlowRef that serves it.

    ``ref`` is threaded in as a real, required argument rather than
    re-derived internally from ``version`` alone, because
    ``@dataframe_cache`` builds its key by hashing every argument passed to
    this function -- via ``bind().apply_defaults()``, so an omitted argument
    still bakes its default into the key as its own permanent bucket. A
    (month, year) label's *meaning* can change -- a flow remapping starts
    serving it from a different dataflow/version -- while the label itself
    stays byte-identical, so a cache key built from ``version`` alone would
    keep matching and silently serve a stale parquet entry written under the
    old mapping forever. Including ``ref`` in the key means that when what a
    version resolves to changes, the key changes with it, and the old entry
    becomes an orphan that is never looked up again -- no different in kind
    from why ``_fetch_flow_mapping`` itself was renamed (see its docstring).

    Splitting the cache from the public ``get_weo_data`` ensures that
    ``version=None`` is mapped to the current latest release before the cache
    lookup. Otherwise the wrapper would cache under ``None`` for 7 days and
    keep serving the previous release even after the version-mapping TTL
    (1 hour) sees a new one.
    """
    logger.info(f"Fetching WEO data from API: {version[0]} {version[1]}")
    url = (
        "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES/"
        f"{ref.dataflow_id}/{ref.version}/*"
    )

    # use_http_cache=False: this CSV already sits under a 7-day parquet cache
    # (the @dataframe_cache above), so a second copy in the HTTP cache is waste.
    response = make_get_request(
        url, headers={"Accept": "text/csv"}, use_http_cache=False
    )

    df = pd.read_csv(StringIO(response.text), low_memory=False)
    return _align_schema(df, ref)


def get_weo_data(version: Version | None = None) -> pd.DataFrame:
    """Fetch WEO data for a specific version.

    Data is cached locally to avoid repeated API calls. Use
    ``imf_reader.cache.clear_cache(scope="weo")`` to clear it.

    Args:
        version: Version tuple (month, year) e.g. ("April", 2025). If None, uses latest.

    Returns:
        DataFrame with WEO data.
    """
    # Resolve the FlowRef BEFORE the cache lookup -- not just "latest" when
    # version is None, but also which dataflow serves an explicit version --
    # so both the version-mapping TTL and a flow remapping take effect
    # immediately instead of being shadowed by a 7-day-TTL cache entry keyed
    # on a (month, year) label alone. See _get_weo_data_cached's docstring.
    mapping = _fetch_flow_mapping()

    if version is None:
        versions = list(mapping.keys())
        versions.sort(key=lambda v: (v[1], 0 if v[0] == "April" else 1), reverse=True)
        version = versions[0]

    if version not in mapping:
        raise VersionNotAvailableError(
            f"Version {version} not available from the API. "
            f"Available: {list(mapping.keys())}"
        )

    return _get_weo_data_cached(version, mapping[version])


# Preserve the .cache_clear attribute on the public symbol so any caller that
# relied on get_weo_data.cache_clear() (the dataframe_cache contract) keeps
# working after the wrapper-vs-resolver split.
get_weo_data.cache_clear = _get_weo_data_cached.cache_clear  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
