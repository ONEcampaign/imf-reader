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
from imf_reader.weo.api import get_weo_data, get_weo_versions
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


def fetch_data(version: Version | None = None) -> pd.DataFrame:
    """Fetch WEO data

    By default, this function fetches data for the latest WEO publication. If a specific publication version
    is required, the version can be passed as a tuple of month and year. WEO data is released in April and October
    each year. For the version month, the month must be either "April" or "October"
    This function caches the data for faster access and to prevent multiple requests to the IMF website. To clear the
    cache, use ``imf_reader.cache.clear_cache(scope="weo")``.

    e.g.
    >>> fetch_data() # fetches the latest data
    >>> fetch_data(("April", 2024)) # fetches the data for April 2024

    Args:
        version: The version of the WEO data to fetch as a tuple eg `("April", 2023)`.
                 By default, the latest version is fetched.

    Returns:
        A pandas DataFrame containing the WEO data
    """

    # Track this before validate_version reassigns `version`: the bounded
    # roll-back below may only kick in for an unresolved "latest" request. An
    # explicit version that cannot be served must raise, never quietly return
    # a different release under the caller's requested label.
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

    fetch_data.last_version_fetched = version  # ty: ignore[unresolved-attribute]

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
