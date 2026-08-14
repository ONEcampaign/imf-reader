"""Main interface to the WEO database."""

from datetime import UTC, datetime, timedelta

import pandas as pd

from imf_reader.cache.dataframe import dataframe_cache
from imf_reader.cache.legacy import _legacy_weo_clear_cache as clear_cache  # noqa: F401
from imf_reader.config import (
    DataflowDiscoveryError,
    NoDataError,
    VersionNotAvailableError,
    logger,
)
from imf_reader.weo import Version
from imf_reader.weo.api import (
    SERIES_METADATA_JOIN_KEYS,
    _resolve_flow_ref,
    get_series_metadata,
    get_weo_data,
    get_weo_versions,
)
from imf_reader.weo.parser import SDMXParser
from imf_reader.weo.scraper import SDMXScraper
from imf_reader.weo.translate import to_api_vocabulary

# Bound on how many published versions roll_back will try, newest-first from
# get_weo_versions(), before giving up on an unresolved version=None request.
_MAX_ROLLBACK_ATTEMPTS = 3


def validate_version(version: tuple) -> Version:
    """Validate the version

    Make sure that it is a tuple of month and year and the month is either April or October.

    Args:
        version: The version to validate

    Returns:
        A tuple of the month and year
    """

    if not isinstance(version, tuple) or len(version) != 2:
        raise TypeError(
            "Invalid version. Must be a tuple of month ('April' or 'October') and year"
        )

    month = version[0].strip().capitalize()
    if month not in ["April", "October"]:
        raise TypeError("Invalid month. Must be `April` or `October`")

    year = version[1]
    if not isinstance(year, int):
        try:
            year = int(year)
        except ValueError as e:
            raise TypeError("Invalid year. Must be an integer") from e

    return month, year


def gen_latest_version() -> Version:
    """Generates the latest expected version based on the current date as a tuple of month and year

    Returns:
        A tuple of the latest month and year
    """

    # A single reading, because two now() calls can straddle midnight on 31
    # December and pair a year with the following year's month. UTC keeps the
    # answer independent of the caller's location, since what is inferred here
    # is the IMF's publication schedule.
    now = datetime.now(tz=UTC)
    current_year = now.year
    current_month = now.month

    if current_month < 4:
        return "October", current_year - 1
    elif current_month < 10:
        return "April", current_year
    else:
        return "October", current_year


@dataframe_cache(ttl=timedelta(days=7), sublayer="weo_sdmx_parsed")
def _fetch(version: Version) -> pd.DataFrame:
    """Scrape, parse, and translate WEO SDMX data for one version, with disk-backed caching.

    Args:
        version: The version of the WEO data to fetch

    Returns:
        A pandas DataFrame containing the WEO data, in the api.imf.org vocabulary
    """

    folder = SDMXScraper.scrape(*version)
    df = SDMXParser.parse(folder)
    df = to_api_vocabulary(df)
    logger.info(f"Data fetched successfully for version: {version[0]} {version[1]}")
    return df


def _fetch_data_resolved(
    version: Version | None = None,
) -> tuple[Version, pd.DataFrame]:
    """Resolve ``version`` (or "latest") and fetch it, returning the
    (version, data) pair actually served.

    Shared by ``fetch_data`` and ``fetch_data_with_metadata`` so the served
    version is threaded through as a return value rather than read back off
    ``fetch_data.last_version_fetched`` afterwards. That module-level
    attribute is process-global state: across threads, thread A calling this
    function and thread B calling ``fetch_data()`` can interleave, with B's
    assignment landing between A's call and a read of the attribute -- A
    would then merge B's resolved release's metadata onto A's observations,
    silent wrong information. Returning the version directly closes that
    window; a fetch can take tens of seconds on a bulk release, so the
    window a read-back would leave open is wide.

    Args:
        version: The version of the WEO data to fetch as a tuple eg
                 `("April", 2023)`. By default, the latest version is
                 resolved and fetched.

    Returns:
        The (version, data) pair actually served -- may differ from
        ``version`` if an unresolved ``version=None`` request rolled back to
        an older release.
    """
    # Track this before validate_version reassigns `version`: the bounded
    # roll-back below may only kick in for an unresolved "latest" request. An
    # explicit version that cannot be served must raise rather than quietly
    # return a different release under the caller's requested label.
    resolve_latest = version is None

    if version is not None:
        try:
            version = validate_version(version)
        except Exception as e:
            raise NoDataError(
                f"Could not fetch data for version: {version!r}. {e!s}"
            ) from e
    else:
        version = get_weo_versions()[0]

    try:
        df = _fetch_data_for_version(version)
    except NoDataError as original_error:
        if not resolve_latest:
            raise
        version, df = _roll_back_and_fetch(version, original_error)

    return version, df


def fetch_data(version: Version | None = None) -> pd.DataFrame:
    """Fetch WEO data

    By default, this function fetches data for the latest WEO publication. If a specific publication version
    is required, the version can be passed as a tuple of month and year. WEO data is released in April and October
    each year. For the version month, the month must be either "April" or "October"
    This function caches the data for faster access and to prevent multiple requests to the IMF website. To clear the
    cache, use ``imf_reader.cache.clear_cache(scope="weo")``.

    For series-level metadata beyond this function's own columns (methodology
    notes, topic and classification codes, fiscal-year reporting
    conventions), see ``fetch_series_metadata`` and, for the two merged in
    one call, ``fetch_data_with_metadata``.

    e.g.
    >>> fetch_data() # fetches the latest data
    >>> fetch_data(("April", 2024)) # fetches the data for April 2024

    Args:
        version: The version of the WEO data to fetch as a tuple eg `("April", 2023)`.
                 By default, the latest version is fetched.

    Returns:
        A pandas DataFrame containing the WEO data
    """
    version, df = _fetch_data_resolved(version)
    fetch_data.last_version_fetched = version  # ty: ignore[unresolved-attribute]

    return df


def fetch_series_metadata(version: Version | None = None) -> pd.DataFrame:
    """Fetch series-level metadata for one WEO release: one row per series,
    covering dozens of sidecar attributes -- methodology notes, topic and
    classification codes, fiscal-year reporting conventions -- beyond what
    ``fetch_data`` returns.

    A version the API cannot serve raises ``VersionNotAvailableError`` here,
    rather than rolling back or falling back to the bulk archive the way
    ``fetch_data`` does, because the SDMX bulk archive has no series
    metadata endpoint at all.

    The result is a separate, series-constant frame -- a dimension table,
    not a fact table -- meant to be merged onto ``fetch_data()``'s output on
    (REF_AREA_CODE, CONCEPT_CODE, FREQ_CODE). Because ``version=None``
    resolves against the *current* dataflow mapping on every call (1-hour
    TTL), two independent calls can resolve to different releases if a new
    one is published between them -- merging metadata from one release onto
    observations from another is silent wrong information, not just stale
    data. Resolve both calls to the same release explicitly to avoid it:

    >>> df = weo.fetch_data()
    >>> meta = weo.fetch_series_metadata(weo.fetch_data.last_version_fetched)

    If ``fetch_data`` rolled back to a bulk-archive release,
    ``last_version_fetched`` names that release and this call then raises
    ``VersionNotAvailableError`` -- the correct outcome, since the bulk
    archive itself has no series metadata to serve.

    Args:
        version: The version of the WEO series metadata to fetch, as a tuple
                 e.g. ``("April", 2023)``. By default, the latest version
                 available from the API is fetched.

    Returns:
        A pandas DataFrame with every column typed ``string``, including the
        three join keys REF_AREA_CODE/CONCEPT_CODE/FREQ_CODE. Only those
        three are guaranteed present release to release. Numeric-looking
        columns such as BASE_YEAR and DECIMALS_DISPLAYED are ``string`` too,
        rather than left to native inference, because that inference is
        unstable release to release.
    """
    if version is not None:
        try:
            version = validate_version(version)
        except Exception as e:
            raise NoDataError(
                f"Could not fetch series metadata for version: {version!r}. {e!s}"
            ) from e

    # Resolved here, against the API mapping alone, so last_version_fetched
    # always names the concrete release actually served -- even for an
    # unresolved version=None request. Re-resolving the same (now concrete)
    # version inside get_series_metadata is a lookup against the same
    # 1-hour-cached flow mapping, not a second HTTP round trip.
    resolved_version, _ref = _resolve_flow_ref(version, purpose="series metadata")
    df = get_series_metadata(resolved_version)

    fetch_series_metadata.last_version_fetched = resolved_version  # ty: ignore[unresolved-attribute]

    return df


def fetch_data_with_metadata(version: Version | None = None) -> pd.DataFrame:
    """Fetch WEO observations merged with series-level metadata in one call.

    Encodes the merge idiom documented on ``fetch_series_metadata``, so a
    caller cannot get it wrong: ``fetch_data``'s 16 columns, left-merged with
    ``fetch_series_metadata``'s columns on ``SERIES_METADATA_JOIN_KEYS``
    (REF_AREA_CODE, CONCEPT_CODE, FREQ_CODE). Only those three join keys are
    guaranteed present release to release -- the rest of the metadata column
    set is release-dependent, since it follows whatever the IMF's DSD carries
    for that release.

    Only API-served releases are supported. If ``fetch_data`` rolls back to a
    bulk-archive release, this raises ``VersionNotAvailableError``: the bulk
    archive has no series metadata endpoint at all, so there is nothing to
    merge, and returning null metadata columns instead would make the
    returned schema conditional on which release happened to be served --
    exactly what having two separate functions is meant to avoid.

    Memory cost: measured against the live April 2026 release, ``fetch_data``
    alone is about 150 MB while this merged frame is about 400 MB, because
    the series-constant metadata is broadcast across every year of every
    series. Callers who only need a few metadata columns should call
    ``fetch_series_metadata`` directly and merge in just those columns
    themselves.

    Args:
        version: The version of the WEO data to fetch as a tuple, e.g.
                 ``("April", 2023)``. By default, the latest version is
                 fetched.

    Returns:
        A pandas DataFrame: ``fetch_data``'s columns plus the series
        metadata columns.

    Raises:
        VersionNotAvailableError: the release ``fetch_data`` served is a
            bulk-archive release, which has no series metadata to merge.
    """
    # Fetches through _fetch_data_resolved directly, rather than calling
    # fetch_data() and reading fetch_data.last_version_fetched back off it
    # afterwards: that module-level attribute is process-global state, and a
    # concurrent fetch_data() call elsewhere could overwrite it between this
    # call and the read. Using the version this call's own resolution
    # returns keeps the two legs on the same release regardless of what else
    # is running. See _fetch_data_resolved's docstring.
    served_version, df = _fetch_data_resolved(version)

    try:
        meta = fetch_series_metadata(served_version)
    except VersionNotAvailableError as exc:
        raise VersionNotAvailableError(
            f"fetch_data served {served_version[0]} {served_version[1]}, a "
            "bulk-archive release with no series metadata. Use fetch_data() "
            "instead if observations alone are enough."
        ) from exc

    join_keys = list(SERIES_METADATA_JOIN_KEYS)

    # A future DSD attribute could name a metadata column identically to one
    # of fetch_data's own (e.g. a new UNIT_LABEL or NOTES attribute): today's
    # deny-lists happen to keep the two sides disjoint, but that is not
    # guaranteed release to release (see get_series_metadata's docstring).
    # Left uncaught, pandas would suffix both columns _x/_y rather than raise,
    # silently breaking every downstream consumer of the unsuffixed name.
    # The observations column wins, the same rule _join_series_metadata
    # already applies to the sidecar join inside fetch_data itself.
    colliding = (set(meta.columns) - set(join_keys)) & set(df.columns)
    if colliding:
        logger.warning(
            "Series metadata columns %s collide with fetch_data's own "
            "columns; dropping the metadata copies so the observations "
            "columns win",
            sorted(colliding),
        )
        meta = meta.drop(columns=list(colliding))

    df = df.merge(meta, on=join_keys, how="left")

    fetch_data_with_metadata.last_version_fetched = served_version  # ty: ignore[unresolved-attribute]

    return df


def _fetch_data_for_version(version: Version) -> pd.DataFrame:
    """Fetch one version through the API, falling back to the bulk scraper
    only when the API cannot serve that version at all.

    ``VersionNotAvailableError`` and ``DataflowDiscoveryError`` (both
    ``NoDataError`` subclasses) are the only signals that mean "try the bulk
    archive instead" -- every other failure inside the API path (a parse bug,
    an ``_align_schema`` bug, a codelist problem) must surface as-is rather
    than being mistaken for a missing version and silently rerouted.

    An unusable dataflow catalogue (``DataflowDiscoveryError``) means the API
    cannot serve *any* version, not just this one, but for an explicit
    version the bulk archive is still the correct source: it returns the
    requested release under its own correct label. An unresolved
    ``version=None`` request never reaches this line, because ``fetch_data``
    resolves "latest" through ``get_weo_versions()`` first, which raises the
    same error and fails loudly rather than silently degrading to an
    archive release mislabelled as latest -- that asymmetry is deliberate:
    degrade to the archive when the label stays right, fail loudly when it
    would not.
    """
    try:
        return get_weo_data(version)
    except (VersionNotAvailableError, DataflowDiscoveryError) as exc:
        logger.warning(
            "API path failed for %s %s (%s: %s); falling back to the bulk archive",
            version[0],
            version[1],
            type(exc).__name__,
            exc,
        )
        return _fetch(version)


def _roll_back_and_fetch(
    version: Version, original_error: NoDataError
) -> tuple[Version, pd.DataFrame]:
    """Bounded roll-back for an unresolved ``version=None`` request.

    Reached only when the caller asked for "latest" and neither the API nor
    the bulk scraper could serve the version ``get_weo_versions()`` named as
    newest. Walks the rest of that already-published, newest-first list --
    rather than guessing a previous release from the calendar -- so this
    cannot invent a release that was never published. Capped at
    ``_MAX_ROLLBACK_ATTEMPTS``; re-raises ``original_error`` if every
    candidate also fails.

    Returns:
        The (version, data) pair that was actually served.
    """
    versions = get_weo_versions()
    start = versions.index(version) + 1 if version in versions else 0

    for candidate in versions[start : start + _MAX_ROLLBACK_ATTEMPTS]:
        logger.warning(
            f"No data found for expected latest version: {version[0]} {version[1]}."
            f" Rolling back to {candidate[0]} {candidate[1]}..."
        )
        try:
            return candidate, _fetch_data_for_version(candidate)
        except NoDataError:
            version = candidate
            continue

    raise original_error
