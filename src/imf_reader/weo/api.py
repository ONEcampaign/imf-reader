"""IMF World Economic Outlook (WEO) API client."""

import re
from datetime import timedelta
from io import StringIO
from typing import Literal, NamedTuple

import pandas as pd

from imf_reader.cache.dataframe import dataframe_cache
from imf_reader.cache.legacy import (
    _legacy_weo_api_clear_cache as clear_cache,  # noqa: F401
)
from imf_reader.config import DataflowDiscoveryError, VersionNotAvailableError, logger
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
    # New columns are appended: positional access on the first 15 columns is
    # live in the wild, so a new column only ever goes on the end.
    "COUNTRY_UPDATE_DATE",
]

# The three columns _join_series_metadata supplies from the series metadata
# sidecar.
_SIDECAR_SUPPLIED_COLUMNS = ["LASTACTUALDATE", "NOTES", "COUNTRY_UPDATE_DATE"]

# The rest of OUTPUT_COLUMNS: what _align_schema alone can produce from the
# main observations fetch. Derived from OUTPUT_COLUMNS rather than
# hand-maintained separately, so the two lists cannot drift apart. This is
# what _get_weo_data_cached returns and caches -- the sidecar-supplied
# columns are joined on afterwards, outside that 7-day cache, so a sidecar
# failure costs only the call that hit it. See _get_weo_data_cached and
# _join_series_metadata.
_OBSERVATION_COLUMNS = [c for c in OUTPUT_COLUMNS if c not in _SIDECAR_SUPPLIED_COLUMNS]


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

    The ``lastUpdatedAt`` structure annotation is inverted on live flows --
    the source of the version mislabelling this probe exists to fix -- so
    probing ``PUBLICATION_DATE`` avoids it. The probe is a single-observation
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
    itself does not parse. And a catalogue response that carries no bare
    ``WEO`` flow at all -- an empty ``dataflows`` list, a renamed envelope
    key, a schema change that drops ``id`` -- raises ``DataflowDiscoveryError``
    rather than returning an empty (or vintage-only) mapping: the IMF has
    always published a bare ``WEO`` flow, so its absence means the catalogue
    response itself is unusable, distinct from there being no data to serve.

    Results are cached for 1 hour to avoid redundant HTTP calls.

    Returns:
        Dict mapping (month, year) tuples to FlowRef(dataflow_id, version).
        e.g. {("October", 2025): FlowRef("WEO_2025_OCT_VINTAGE", "1.0.0"),
              ("April", 2026): FlowRef("WEO", "9.0.0")}
    """
    url = "https://api.imf.org/external/sdmx/3.0/structure/dataflow/IMF.RES/*/*?detail=allstubs"
    response = make_get_request(url)
    data = response.json()

    dataflows = data.get("data", {}).get("dataflows", []) or []
    candidates: list[tuple[str, str]] = []
    for df_stub in dataflows:
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

    # Raising here, rather than returning the empty or vintage-only mapping,
    # is load-bearing: @dataframe_cache only persists a return value, so
    # raising is what keeps an unusable mapping out of the 1-hour cache.
    # A vintage-only mapping still cannot resolve "latest", so it is checked
    # for specifically rather than just checking that mapping is non-empty.
    if not any(ref.dataflow_id == "WEO" for ref in mapping.values()):
        raise DataflowDiscoveryError(
            f"Dataflow catalogue at {url} returned no usable WEO dataflow "
            f"({len(candidates)} matching stub(s) found among "
            f"{len(dataflows)} total)"
        )

    return mapping


def get_weo_versions() -> list[Version]:
    """Fetch all WEO versions this package can serve.

    This is the union of the API's dataflow mapping and the discontinued SDMX
    bulk archive (``scraper.SDMX_RELEASES``), minus the two releases that are
    corrupt in the IMF's own published archive (``scraper.KNOWN_CORRUPT_RELEASES``).
    ``get_weo_data(version=None)`` resolves "latest" against the API mapping
    alone, so the SDMX-only releases in this list are reachable only through
    ``fetch_data``'s scraper fallback.

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


# The rename _align_schema applies to the API's raw column names. Also drives
# _METADATA_JOIN_KEY_RENAME below, so the two cannot drift apart.
_API_COLUMN_RENAME = {
    "COUNTRY": "REF_AREA_CODE",
    "INDICATOR": "CONCEPT_CODE",
    "UNIT": "UNIT_CODE",
    "FREQUENCY": "FREQ_CODE",
    "SCALE": "SCALE_CODE",
}

# Columns pulled off the sidecar CSV as-is, before any renaming.
_METADATA_JOIN_KEYS = ["COUNTRY", "INDICATOR", "FREQUENCY"]
_SIDECAR_RAW_COLUMNS = [
    *_METADATA_JOIN_KEYS,
    "LATEST_ACTUAL_ANNUAL_DATA",
    "METHODOLOGY_NOTES",
    "COUNTRY_UPDATE_DATE",
]

# Derived from _API_COLUMN_RENAME rather than hand-duplicated, so a key
# vanishing from that dict fails at import rather than at the merge in
# _join_series_metadata.
_METADATA_JOIN_KEY_RENAME = {
    key: value
    for key, value in _API_COLUMN_RENAME.items()
    if key in _METADATA_JOIN_KEYS
}

# Public: the columns get_series_metadata's and get_weo_data's frames share,
# for a caller merging the two themselves. Derived from
# _METADATA_JOIN_KEY_RENAME rather than hand-duplicated, so the two cannot
# drift apart.
SERIES_METADATA_JOIN_KEYS: tuple[str, ...] = tuple(_METADATA_JOIN_KEY_RENAME.values())

# LATEST_ACTUAL_ANNUAL_DATA is either a plain year ("2024") or a fiscal-year
# form ("FY2023/24", 10.7% of populated series -- the bulk archive has no FY
# forms at all). Group 1 catches the FY form's leading year, group 2 the
# plain form; anything else matches neither and becomes <NA>.
_LATEST_ACTUAL_ANNUAL_DATA_RE = re.compile(r"^(?:FY(\d{4})/\d{2}|(\d{4}))$")

# Bumped whenever _fetch_series_metadata's returned column set or dtypes
# change. Threaded through as a cache-key discriminator (see below) because a
# warm 7-day parquet written under an older schema would otherwise be served
# to code that expects the new one -- the version-scoped cache root does not
# save this, since editable and git installs stay inside the same version
# segment (see CHANGELOG.md).
_SIDECAR_SCHEMA = "3"

# Matches the SDMX-CSV writer's multi-value-delimiter marker on a header,
# e.g. "TOPIC[]" or "STRUCTURE[;]". The marker names the writer's own
# intra-cell delimiter, not the DSD component id, so stripping it makes the
# column name attribute-accessible, usable in df.query(), and joinable to
# the codelist by its real id.
_MULTI_VALUE_SUFFIX_RE = re.compile(r"\[[^\]]*\]$")

# SDMX envelope columns and firstNObservations=1 artefacts, dropped from the
# sidecar before caching -- never data this package or its callers can use.
# Matched post-normalisation, since the literal header is "STRUCTURE[;]".
_SIDECAR_ENVELOPE_COLUMNS = frozenset(
    {"STRUCTURE", "STRUCTURE_ID", "ACTION", "TIME_PERIOD", "OBS_VALUE"}
)

# Dropped from the public series-metadata frame only (get_series_metadata),
# kept in the cached artefact because _join_series_metadata still needs
# them. COUNTRY_UPDATE_DATE collides by name with a fetch_data column
# sourced identically, so a user merge would produce _x/_y. UNIT and SCALE
# duplicate UNIT_CODE/SCALE_CODE, and SCALE is actively dangerous, since the
# sidecar carries the bare exponent (e.g. 9) while fetch_data's SCALE_CODE
# carries the multiplier (1000000000) that exponent is converted to in
# _align_schema.
_SERIES_METADATA_EXCLUDED = frozenset({"COUNTRY_UPDATE_DATE", "UNIT", "SCALE"})


def _normalise_sidecar_columns(columns: pd.Index) -> dict[str, str]:
    """Map each raw sidecar header to its normalised name, stripping a
    trailing multi-value-delimiter marker such as ``[]`` or ``[;]``.

    Raises:
        ValueError: two columns normalise to the same name.
    """
    normalised: dict[str, str] = {}
    seen: dict[str, str] = {}
    for original in columns:
        stripped = _MULTI_VALUE_SUFFIX_RE.sub("", original)
        colliding = seen.get(stripped)
        if colliding is not None:
            raise ValueError(
                f"Sidecar columns {colliding!r} and {original!r} both "
                f"normalise to {stripped!r}"
            )
        seen[stripped] = original
        normalised[original] = stripped
    return normalised


@dataframe_cache(ttl=timedelta(days=7), sublayer="weo_api")
def _fetch_series_metadata(ref: FlowRef, schema: str = _SIDECAR_SCHEMA) -> pd.DataFrame:
    """Fetch series-level metadata for one dataflow: one row per (country,
    indicator, frequency).

    Uses the ``attributes=series&firstNObservations=1`` sidecar (~300 KB on
    the wire) rather than reading metadata off the main data CSV: the main
    fetch's default attribute set moves release to release as the IMF's DSD
    changes, so every metadata column this package publishes comes from this
    sidecar uniformly.

    Returns every sidecar column except the SDMX envelope and
    ``firstNObservations=1`` artefacts (``_SIDECAR_ENVELOPE_COLUMNS``): a
    deny-list, not an allow-list, since an allow-list would silently drop
    every attribute the IMF adds to the DSD and ``KeyError`` on every one it
    removes, as the API's attribute set changes across dataflow versions.
    Column names are normalised first (bracket suffix stripped, see
    ``_normalise_sidecar_columns``), so the cached artefact and every
    deny-list downstream are written against normalised names.

    ``schema`` is a cache-key discriminator (``@dataframe_cache`` bakes its
    default into the key via ``bind().apply_defaults()``), bumped whenever
    this function's returned column set or dtypes change. Callers must not
    pass it explicitly.

    Every column is read as ``string`` rather than left to type inference:
    inference would give e.g. ``BASE_YEAR`` ``float64`` (``1990.0``),
    ``DECIMALS_DISPLAYED`` ``int64``, ``KEY_INDICATOR`` possibly ``bool``,
    and those inferences move between releases and across the pandas support
    range.

    NA recognition is also explicit rather than left to ``read_csv``'s
    default: pandas' default NA-token list treats a literal ``N/A`` or
    ``n/a`` cell -- values the IMF actually publishes, on
    ``METHODOLOGY_NOTES`` and ``BASIS_OF_PROJECTIONS`` among others -- as
    missing, indistinguishable from a genuinely empty cell. This frame is
    meant to expose what the IMF publishes verbatim, so only a truly empty
    cell (``keep_default_na=False, na_values=[""]``) is treated as missing
    here; every other column stays free to carry whatever literal text the
    sidecar sends, NA-like tokens included. A caller that wants "no note"
    normalised to null -- e.g. ``fetch_data``'s ``NOTES`` column -- does that
    normalisation itself, downstream of this function (see
    ``_join_series_metadata`` and ``_NA_LIKE_TOKENS``).

    Results are cached for 7 days, matching the primary data fetch's TTL.
    Checking for a column a caller relies on (e.g.
    ``LATEST_ACTUAL_ANNUAL_DATA``) belongs to the callers that need those
    specific columns, so a sidecar missing one gets cached once rather than
    re-fetched on every call for a condition that will not resolve until the
    next release. A transient network failure still writes nothing, since
    ``make_get_request`` raising means there is no return value to cache.
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
    df = pd.read_csv(
        StringIO(response.text),
        low_memory=False,
        dtype="string",
        keep_default_na=False,
        na_values=[""],
    )
    df = df.rename(columns=_normalise_sidecar_columns(df.columns))
    return df.drop(columns=[c for c in _SIDECAR_ENVELOPE_COLUMNS if c in df.columns])


# NA-like literal tokens the sidecar's free-text columns carry for "not
# applicable", distinct from a genuinely empty cell -- see
# _fetch_series_metadata's docstring for why its own read preserves these
# as literal text rather than folding them into <NA> automatically. Matched
# case-insensitively (see
# _null_na_like_tokens): the live sidecar has been observed to emit both
# "N/A" (METHODOLOGY_NOTES) and "n/a" (BASIS_OF_PROJECTIONS) for the same
# meaning, and no sidecar column is known to use casing to carry information,
# so folding case here catches any other casing variant (e.g. "N/a") without
# hand-listing it.
_NA_LIKE_TOKENS = frozenset({"N/A"})


def _null_na_like_tokens(text: pd.Series) -> pd.Series:
    """Null out cells matching _NA_LIKE_TOKENS (case-insensitively), leaving
    already-null cells and everything else untouched."""
    return text.mask(text.str.upper().isin(_NA_LIKE_TOKENS), pd.NA)


def _parse_latest_actual_annual_data(raw: pd.Series) -> pd.Series:
    """Parse LATEST_ACTUAL_ANNUAL_DATA to the leading year, as an Int64.

    A fiscal-year form (``FY2023/24``) and a plain year (``2024``) both parse
    to the same integer, since the bulk XML's LASTACTUALDATE this column
    feeds has no FY forms at all -- collapsing the distinction is what makes
    the two paths semantically identical. Anything else becomes <NA>,
    including an NA-like literal such as ``N/A``/``n/a`` (see
    _NA_LIKE_TOKENS) -- normalised away before the unparsed-token check below
    so a genuinely unrecognised token doesn't get lost in the noise of an
    expected one.
    """
    text = _null_na_like_tokens(raw.astype("string"))
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

    No explicit NA-like-token handling is needed here (unlike
    ``_parse_latest_actual_annual_data``): ``errors="coerce"`` already turns
    anything that doesn't match ``%m/%d/%Y`` -- an NA-like literal such as
    ``N/A``/``n/a`` included -- into ``NaT``.
    """
    return pd.to_datetime(raw, format="%m/%d/%Y", errors="coerce").astype(
        "datetime64[us]"
    )


def _with_null_metadata_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Fill LASTACTUALDATE/NOTES/COUNTRY_UPDATE_DATE with nulls of the
    correct dtype -- what ships when the metadata sidecar can't be trusted.

    This is the same null result existing callers of the API path already
    see for the first two columns, so degrading here leaves that behaviour
    unchanged.
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

    Series metadata and observations are cached independently: this call
    sits outside ``_get_weo_data_cached``'s 7-day cache (the caller is
    ``get_weo_data``, after that cache lookup has already returned), while
    ``_fetch_series_metadata`` above has its own 7-day cache. So a sidecar
    failure -- a transient network blip -- costs only the call that hit it.

    ``df`` has already been through ``_align_schema``'s rename by the time it
    gets here, so it carries REF_AREA_CODE/CONCEPT_CODE/FREQ_CODE rather than
    the sidecar's own COUNTRY/INDICATOR/FREQUENCY -- the merge maps the
    sidecar's join keys onto their renamed equivalents.

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
        # _fetch_series_metadata returns the whole widened sidecar (see its
        # docstring). This narrows it back to the six columns this function
        # uses. Placement inside the try is load-bearing: a DSD change that
        # drops one of these columns raises KeyError here, which this except
        # degrades to null metadata rather than exploding -- never a
        # "fixable" regression, since get_series_metadata is the place a
        # caller who wants the raw widened frame should use instead.
        meta = meta[_SIDECAR_RAW_COLUMNS]
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

    # The main fetch's own default attribute set changes across dataflow
    # versions (WEO 6.0.0's DSD carries LATEST_ACTUAL_ANNUAL_DATA, WEO
    # 9.0.0's carries COUNTRY_UPDATE_DATE, neither carries both) -- so
    # ``df`` may already have a raw copy of one of the sidecar's columns.
    # Drop it before merging: every metadata value this package publishes
    # must come from the sidecar uniformly, and left unmerged that copy
    # would collide with the sidecar's during the join and pandas would
    # suffix both instead of leaving a plain COUNTRY_UPDATE_DATE column. This
    # also covers a warm parquet entry carrying the full 16 legacy-named
    # columns under an unchanged cache key: COUNTRY_UPDATE_DATE in that entry
    # happens to collide by name with the sidecar's own column, so this drop
    # keeps the join tolerant of that too.
    sidecar_value_columns = [c for c in meta.columns if c not in _METADATA_JOIN_KEYS]
    df = df.drop(columns=[c for c in sidecar_value_columns if c in df.columns])

    # meta's join keys are the sidecar's own COUNTRY/INDICATOR/FREQUENCY;
    # df's are already renamed to REF_AREA_CODE/CONCEPT_CODE/FREQ_CODE by
    # _align_schema, so the sidecar's keys are renamed to match before the
    # merge rather than merging on two differently-named key sets.
    meta = meta.rename(columns=_METADATA_JOIN_KEY_RENAME)

    # meta comes straight off pd.read_csv, so its join keys carry the
    # default StringDtype (na_value=nan); df's carry the StringDtype
    # _align_schema casts to (na_value=pd.NA). The two StringDtypes are
    # unequal, so without this cast pandas' merge machinery falls through to
    # its last-resort branch and silently casts both sides' join keys to
    # object -- which becomes the dtype of the public return value.
    join_keys = list(_METADATA_JOIN_KEY_RENAME.values())
    meta[join_keys] = meta[join_keys].astype("string")

    df = df.merge(meta, on=join_keys, how="left")
    df["LASTACTUALDATE"] = _parse_latest_actual_annual_data(
        df.pop("LATEST_ACTUAL_ANNUAL_DATA")
    )
    # NOTES normalises an NA-like literal (e.g. "N/A") to null same as a
    # genuinely empty cell, unlike _fetch_series_metadata's own raw frame,
    # which preserves it verbatim (see that function's docstring and
    # _NA_LIKE_TOKENS): a caller filtering df[df.NOTES.notna()] must not get
    # back a row whose "note" is the literal word for "no note".
    df["NOTES"] = _null_na_like_tokens(df.pop("METHODOLOGY_NOTES").astype("string"))
    df["COUNTRY_UPDATE_DATE"] = _parse_country_update_date(df["COUNTRY_UPDATE_DATE"])
    return df


def _rejoin_series_metadata_if_degraded(df: pd.DataFrame, ref: FlowRef) -> pd.DataFrame:
    """Retry the series-metadata join once, if ``df`` carries
    ``_with_null_metadata_columns``'s degrade signature: LASTACTUALDATE,
    NOTES and COUNTRY_UPDATE_DATE all entirely null.

    Exists for ``reader.fetch_data_with_metadata``, which reads the same
    cached sidecar twice for one call -- once via ``get_weo_data`` while
    building its observations frame, once via ``_series_metadata_for_ref``
    for its own metadata frame. If the first read failed transiently and the
    second succeeded, ``df`` would otherwise carry a populated
    LATEST_ACTUAL_ANNUAL_DATA-derived metadata frame sitting beside its own
    null LASTACTUALDATE, and a null COUNTRY_UPDATE_DATE with no counterpart
    at all (it is excluded from the metadata frame, see
    ``_SERIES_METADATA_EXCLUDED``) -- internally inconsistent data, not
    merely missing data. The caller is expected to call this only after a
    metadata fetch has already succeeded, since that is what proves the
    sidecar cache is warm: the retry here is then a cache hit, not a second
    HTTP round trip.

    The all-null check is a sufficient-not-necessary signature for a
    degrade: a legitimate merge that matched no rows at all produces the
    same all-null shape. Re-running the join in that case is harmless --
    the sidecar is cached, so it costs one cache hit and reproduces the same
    (correctly empty) result -- so this does not try to tell the two cases
    apart.

    Retries at most once; never loops.
    """
    if not all(df[column].isna().all() for column in _SIDECAR_SUPPLIED_COLUMNS):
        return df

    original_columns = df.columns.tolist()
    rejoined = _join_series_metadata(df.drop(columns=_SIDECAR_SUPPLIED_COLUMNS), ref)
    # _join_series_metadata appends its three columns at the end; restoring
    # the caller's original column order keeps this transparent to a caller
    # that already reindexed (e.g. reader.fetch_data_with_metadata, whose
    # observations frame is already OUTPUT_COLUMNS-ordered).
    rejoined = rejoined[original_columns]

    if not all(rejoined[column].isna().all() for column in _SIDECAR_SUPPLIED_COLUMNS):
        logger.info(
            "Series metadata for %s %s recovered on retry; LASTACTUALDATE, "
            "NOTES and COUNTRY_UPDATE_DATE are now populated",
            ref.dataflow_id,
            ref.version,
        )

    return rejoined


def _align_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Align the schema of the DataFrame to match the old SDMX format.

    Renames columns, adds label columns for codes, and fixes data types.
    Series metadata (LASTACTUALDATE/NOTES/COUNTRY_UPDATE_DATE) is joined on
    separately by the caller (``get_weo_data``, via ``_join_series_metadata``)
    once this function's result is out from under ``_get_weo_data_cached``'s
    7-day cache -- see that function's docstring for why.

    Adds ``REF_AREA_IMF_CODE``, a compatibility column carrying the legacy IMF
    numeric area code for each row (null for areas with no legacy code, e.g.
    ``LIE``). It exists so code migrating off the numeric ``REF_AREA_CODE``
    has a one-line path to it; it is slated for removal in 3.0.

    Args:
        df: DataFrame from API.

    Returns:
        DataFrame with old-style column names, correct data types, and every
        ``OUTPUT_COLUMNS`` entry this function alone can produce (i.e.
        ``OUTPUT_COLUMNS`` minus the three series-metadata columns).
    """
    df = _drop_empty_observations(df)

    # Fetch codelists for labels (with caching)
    country_labels = _fetch_codelist("IMF.RES", "CL_WEO_COUNTRY")
    indicator_labels = _fetch_codelist("IMF.RES", "CL_WEO_INDICATOR")
    unit_labels = _fetch_codelist("IMF", "CL_UNIT")
    freq_labels = _fetch_codelist("IMF", "CL_FREQ")

    df = df.rename(columns=_API_COLUMN_RENAME)

    df["REF_AREA_IMF_CODE"] = (
        df["REF_AREA_CODE"].map(API_AREA_TO_LEGACY).astype("Int64")
    )

    df["REF_AREA_LABEL"] = df["REF_AREA_CODE"].map(country_labels)
    df["CONCEPT_LABEL"] = df["CONCEPT_CODE"].map(indicator_labels)
    df["UNIT_LABEL"] = df["UNIT_CODE"].map(unit_labels)
    df["FREQ_LABEL"] = df["FREQ_CODE"].map(freq_labels)
    df["SCALE_LABEL"] = df["SCALE_CODE"].map(SCALE_LABELS)

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

    return df[_OBSERVATION_COLUMNS]


@dataframe_cache(ttl=timedelta(days=7), sublayer="weo_api")
def _get_weo_data_cached(version: Version, ref: FlowRef) -> pd.DataFrame:
    """Inner cached fetch -- keyed on a *resolved* (month, year) tuple AND the
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
    becomes an orphan that is never looked up again.

    Splitting the cache from the public ``get_weo_data`` ensures that
    ``version=None`` is mapped to the current latest release before the cache
    lookup. Otherwise the wrapper would cache under ``None`` for 7 days and
    keep serving the previous release even after the version-mapping TTL
    (1 hour) sees a new one.

    Caches only the observations (``_OBSERVATION_COLUMNS``), not the series
    metadata sidecar columns (LASTACTUALDATE/NOTES/COUNTRY_UPDATE_DATE):
    ``get_weo_data`` joins those on afterwards, via
    ``_join_series_metadata``, which sits under its own independent 7-day
    cache (``_fetch_series_metadata``). Observations and series metadata are
    cached independently, so a transient sidecar failure costs only the call
    that hit it.
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
    return _align_schema(df)


def _resolve_flow_ref(
    version: Version | None,
    *,
    purpose: Literal["observations", "series metadata"],
) -> tuple[Version, FlowRef]:
    """Resolve a requested (or ``None`` for "latest") version to the FlowRef
    that serves it, against the API's own dataflow mapping alone -- never
    ``get_weo_versions()``'s SDMX-inclusive union, so "latest" always
    resolves to a release the API can serve.

    Resolution happens before any cache lookup at the call site, for both
    ``version=None`` and an explicit version, so both the version-mapping
    TTL and a flow remapping take effect immediately instead of being
    shadowed by a longer-TTL cache entry keyed on a (month, year) label
    alone.

    ``purpose`` names what the caller is trying to do ("observations" or
    "series metadata"), so the ``VersionNotAvailableError`` raised for an
    unservable version can point at the right next step: ``get_weo_data``'s
    bulk-archive fallback for observations, or the API-coverage boundary and
    ``get_weo_versions()`` for series metadata, which has no bulk fallback
    at all.

    Raises:
        VersionNotAvailableError: ``version`` (explicit or resolved) is not
            in the API's dataflow mapping.
    """
    mapping = _fetch_flow_mapping()

    if version is None:
        versions = list(mapping.keys())
        versions.sort(key=lambda v: (v[1], 0 if v[0] == "April" else 1), reverse=True)
        version = versions[0]

    if version not in mapping:
        if purpose == "series metadata":
            raise VersionNotAvailableError(
                f"Version {version} not available from the API. Series "
                "metadata has no bulk-archive fallback, so it is only "
                "served for versions the API itself carries. "
                f"Available: {list(mapping.keys())}"
            )
        raise VersionNotAvailableError(
            f"Version {version} not available from the API. "
            f"Available: {list(mapping.keys())}"
        )

    return version, mapping[version]


def _get_weo_data_with_ref(
    version: Version | None = None,
) -> tuple[pd.DataFrame, FlowRef]:
    """``get_weo_data``'s real body, also returning the FlowRef that served
    the request.

    Split out for ``reader._fetch_data_for_version``, which needs that ref
    to pin ``fetch_data_with_metadata``'s series-metadata leg to the same
    dataflow/version its observations leg resolved to -- re-resolving the
    version a second time (the naive approach) risks landing on a different
    FlowRef if the 1-hour flow-mapping cache expires between the two calls.

    Args:
        version: Version tuple (month, year) e.g. ("April", 2025). If None, uses latest.

    Returns:
        The (frame, ref) pair: frame carries every ``OUTPUT_COLUMNS`` entry,
        ref is the FlowRef that served it.
    """
    version, ref = _resolve_flow_ref(version, purpose="observations")
    # The observations cache (_get_weo_data_cached) and the series metadata
    # sidecar (_join_series_metadata -> _fetch_series_metadata) are cached
    # independently, joined here rather than inside the cached function, so a
    # transient sidecar failure only ever costs this one call. See
    # _get_weo_data_cached's docstring.
    df = _get_weo_data_cached(version, ref)
    df = _join_series_metadata(df, ref)
    return df[OUTPUT_COLUMNS], ref


def get_weo_data(version: Version | None = None) -> pd.DataFrame:
    """Fetch WEO data for a specific version.

    Data is cached locally to avoid repeated API calls. Use
    ``imf_reader.cache.clear_cache(scope="weo")`` to clear it.

    Args:
        version: Version tuple (month, year) e.g. ("April", 2025). If None, uses latest.

    Returns:
        DataFrame with WEO data.
    """
    df, _ref = _get_weo_data_with_ref(version)
    return df


# Preserve the .cache_clear attribute on the public symbol (the
# dataframe_cache contract) for callers that rely on
# get_weo_data.cache_clear(): get_weo_data is an undecorated wrapper around
# _get_weo_data_cached, so it does not inherit the attribute automatically.
get_weo_data.cache_clear = _get_weo_data_cached.cache_clear  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]


def _series_metadata_for_ref(ref: FlowRef) -> pd.DataFrame:
    """Build the public series-metadata frame for one resolved release: the
    sidecar minus ``_SERIES_METADATA_EXCLUDED``, join keys renamed and moved
    to the front, every column cast to ``string``.

    Uncached at this layer: it sits directly on top of
    ``_fetch_series_metadata``'s own 7-day cache, so a second cache here
    would buy nothing and would also swallow ``get_series_metadata``'s
    ``version=None`` resolution, which must stay live on every call -- see
    that function's docstring.

    Raises:
        ValueError: the sidecar carries a duplicated join key. This frame
            *is* the caller's request in full, unlike
            ``_join_series_metadata``, which drops a duplicated sidecar and
            degrades to null columns because the caller still keeps their
            observations: a duplicated key here has nothing to fall back to,
            and the frame is about to be merged onto the caller's own
            observations, where a duplicated key would fabricate rows
            silently.
    """
    meta = _fetch_series_metadata(ref)
    meta = meta.drop(
        columns=[c for c in _SERIES_METADATA_EXCLUDED if c in meta.columns]
    )
    meta = meta.rename(columns=_METADATA_JOIN_KEY_RENAME)

    join_keys = list(_METADATA_JOIN_KEY_RENAME.values())
    value_columns = [c for c in meta.columns if c not in join_keys]
    meta = meta[[*join_keys, *value_columns]]

    # Unconditional even though _fetch_series_metadata already reads the CSV
    # as "string": pd.read_parquet can hand back plain object or an
    # Arrow-backed string dtype depending on the pandas/pyarrow pair, so
    # without this cast a warm cache and a cold cache would return different
    # dtypes and the merge trap at _join_series_metadata (see its docstring)
    # would re-arm on cache hits only.
    meta = meta.astype("string")

    duplicated = meta.duplicated(subset=join_keys)
    if duplicated.any():
        raise ValueError(
            f"Series metadata sidecar for {ref.dataflow_id} {ref.version} has "
            f"{int(duplicated.sum())} row(s) with a duplicated {join_keys} key"
        )

    return meta


def get_series_metadata(version: Version | None = None) -> pd.DataFrame:
    """Fetch series-level metadata for one WEO release: one row per
    ``SERIES_METADATA_JOIN_KEYS`` (REF_AREA_CODE, CONCEPT_CODE, FREQ_CODE),
    covering every sidecar attribute beyond the three join keys.

    This function and ``fetch_data`` share one HTTP fetch and one 7-day
    cache entry (``_fetch_series_metadata``), but return separate frames:
    this one a series-constant, dimension-table frame -- not a fact table --
    rather than broadcasting dozens of free-text columns across
    ``fetch_data``'s per-observation rows.

    Resolves ``version=None`` against the *current* flow mapping (1-hour
    TTL) on every call, so this function is left uncached at this layer:
    caching it would bake that resolution into a 7-day key under the
    literal value ``None``, and go on serving whatever release was latest on
    the first call long after the mapping has moved past it -- the same
    trap ``get_weo_data`` avoids by keeping its own resolution outside
    ``_get_weo_data_cached``.

    Merging the result onto the main observations frame is a caller-side
    join on ``SERIES_METADATA_JOIN_KEYS`` (REF_AREA_CODE, CONCEPT_CODE,
    FREQ_CODE). See ``imf_reader.weo.reader.fetch_series_metadata`` for the
    idiom that avoids merging metadata from one release onto observations
    from another.

    Args:
        version: Version tuple (month, year), e.g. ("October", 2025). If
            None, uses latest as resolved against the API's own dataflow
            mapping, not ``get_weo_versions()``'s SDMX-inclusive union: the
            SDMX bulk archive has no series metadata endpoint at all.

    Returns:
        DataFrame with every column typed ``string`` (StringDtype),
        including the three join keys. Only those three are guaranteed
        present release to release -- the rest of the column set is
        release-dependent by design, since the sidecar's own columns move as
        the IMF's DSD changes.

    Raises:
        VersionNotAvailableError: the requested (or resolved) version is not
            served by the API. There is no bulk-archive fallback here.
        ConnectionError: the sidecar fetch failed. Propagated as-is rather
            than degraded to null columns, unlike ``fetch_data``'s
            null-and-warn behaviour: here the frame is the entire product,
            so there is nothing left to hand back.
        ValueError: the sidecar has a duplicated join key, or two of its
            columns collide once their bracket suffix is stripped.
    """
    _, ref = _resolve_flow_ref(version, purpose="series metadata")
    return _series_metadata_for_ref(ref)
