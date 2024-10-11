"""Main interface to the WEO database."""

from datetime import datetime
from typing import Literal, Tuple, Optional
import pandas as pd
from functools import lru_cache

from imf_reader.weo.scraper import SDMXScraper
from imf_reader.weo.parser import SDMXParser
from imf_reader.config import logger, NoDataError

ValidMonths = Literal["April", "October"]  # Type hint for valid months
Version = Tuple[ValidMonths, int]  # Type hint for version as a tuple of month and year


def validate_version(version: Tuple) -> Version:
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

    # check that the month is either April or October
    month = version[0].strip().capitalize()
    if month not in ["April", "October"]:
        raise TypeError("Invalid month. Must be `April` or `October`")

    # check that the year is an integer. If it is not try to make it an integer
    year = version[1]
    if not isinstance(year, int):
        try:
            year = int(year)
        except ValueError:
            raise TypeError("Invalid year. Must be an integer")

    return month, year


def gen_latest_version() -> Version:
    """Generates the latest expected version based on the current date as a tuple of month and year

    Returns:
        A tuple of the latest month and year
    """

    current_year = datetime.now().year
    current_month = datetime.now().month

    # if month is less than 4 (April) return the version 2 (October) for the previous year
    if current_month < 4:
        return "October", current_year - 1

    # elif month is less than 10 (October) return current year and version 2 (April)
    elif current_month < 10:
        return "April", current_year

    # else (if month is more than 10 (October) return current month and version 2 (October)
    else:
        return "October", current_year


def roll_back_version(version: Version) -> Version:
    """Roll back version to the previous version

    This function rolls back the version passed to the expected previous version. If the version is April 2024
    it will roll back to October 2023. If the version is October 2023 it will roll back to April 2023.

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


@lru_cache
def _fetch(version: Version) -> pd.DataFrame:
    """Helper function which handles caching and fetching the data from the IMF website

    Args:
        version: The version of the WEO data to fetch

    Returns:
        A pandas DataFrame containing the WEO data
    """

    folder = SDMXScraper.scrape(*version)  # scrape the data and get the SDMX files
    df = SDMXParser.parse(folder)  # parse the SDMX files into a DataFrame
    logger.info(f"Data fetched successfully for version: {version[0]} {version[1]}")
    return df


def clear_cache():
    """Clears the cache for any WEO data fetched by the `fetch_data` function."""

    _fetch.cache_clear()
    logger.info("Cache cleared")


def fetch_data(version: Optional[Version] = None) -> pd.DataFrame:
    """Fetch WEO data

    By default, this function fetched data for the latest WEO publication. If a specific publication version
    is required, the version can be passed as a tuple of month and year. WEO data is released in April and October
    each year. For the version month, the month must be either "April" or "October"
    This function caches the data for faster access and to prevent multiple requests to the IMF website. To clear the
    cache, use the `clear_cache` function.

    e.g.
    >>> fetch_data() # fetches the latest data
    >>> fetch_data(("April", 2024)) # fetches the data for April 2024

    Args:
        version: The version of the WEO data to fetch as a tuple eg `("April", 2023).
                 By default, the latest version is fetched.

    Returns:
        A pandas DataFrame containing the WEO data
    """

    # if version is passed, validate it and fetch the data
    if version is not None:
        try:
            version = validate_version(version)
            df = _fetch(version)
            fetch_data.last_version_fetched = (
                version  # store the version fetched as function attribute
            )
            return df
        except Exception as e:
            raise NoDataError(
                f"Could not fetch data for version: {version[0]} {version[1]}. {str(e)}"
            )

    # if no version is passed, generate the latest version and fetch the data
    latest_version = gen_latest_version()
    try:
        return fetch_data(latest_version)

    # if no data is found for the expected latest version, roll back once and try again
    except NoDataError:
        logger.info(
            f"No data found for expected latest version: {latest_version[0]} {latest_version[1]}."
            f" Rolling back version..."
        )
        latest_version = roll_back_version(latest_version)
        return fetch_data(latest_version)
