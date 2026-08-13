"""Main interface to the WEO database."""

from datetime import datetime, timedelta

import pandas as pd

from imf_reader.cache.dataframe import dataframe_cache
from imf_reader.cache.legacy import _legacy_weo_clear_cache as clear_cache  # noqa: F401
from imf_reader.config import NoDataError, logger
from imf_reader.weo import Version
from imf_reader.weo.api import get_weo_data, get_weo_versions
from imf_reader.weo.parser import SDMXParser
from imf_reader.weo.scraper import SDMXScraper
from imf_reader.weo.translate import to_api_vocabulary


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

    current_year = datetime.now().year
    current_month = datetime.now().month

    if current_month < 4:
        return "October", current_year - 1
    elif current_month < 10:
        return "April", current_year
    else:
        return "October", current_year


def roll_back_version(version: Version) -> Version:
    """Roll back version to the expected previous version.

    e.g. April 2024 rolls back to October 2023, and October 2023 rolls back to April 2023.

    Args:
        version: The version to roll back

    Returns:
        The rolled back version
    """

    if version[0] == "October":
        logger.debug(f"Rolling back version to April {version[1]}")
        return "April", version[1]

    elif version[0] == "April":
        logger.debug(f"Rolling back version to October {version[1] - 1}")
        return "October", version[1] - 1

    else:
        raise ValueError(f"Invalid version: {version}")


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

    if version is not None:
        try:
            version = validate_version(version)
        except Exception as e:
            raise NoDataError(
                f"Could not fetch data for version: {version[0]} {version[1]}. {e!s}"
            ) from e
    else:
        version = get_weo_versions()[0]

    try:
        df = get_weo_data(version)

    except (NoDataError, ValueError):
        try:
            df = _fetch(version)
        except NoDataError:
            logger.info(
                f"No data found for expected latest version: {version[0]} {version[1]}."
                f" Rolling back version..."
            )
            latest_version = roll_back_version(version)
            return fetch_data(latest_version)

    fetch_data.last_version_fetched = version  # ty: ignore[unresolved-attribute]

    return df
