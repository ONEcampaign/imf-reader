"""Main interface to the WEO database."""

from datetime import datetime
from typing import Literal, Tuple
import pandas as pd

from imf_reader.weo.scraper import SDMXScraper
from imf_reader.weo.parser import SDMXParser
from imf_reader.config import logger, NoDataError


def validate_version_month(month: str) -> str:
    """Checks that the month is April or October and returns the validated month.

    Removes whitespace and converts to sentence case before validation. Any other misspellings, invalid months,
    or variations will raise a TypeError.

    Args:
        month: The month to validate

    Returns:
        The validated month
    """

    # clean string - remove whitespace and convert to sentence case
    month = month.strip().capitalize()

    if month not in ["April", "October"]:
        raise TypeError("Invalid month. Must be `April` or `October`")

    return month


def gen_latest_version() -> Tuple[Literal["April", "October"], int]:
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


def roll_back_version(version: Tuple[Literal["April", "October"], int]) -> Tuple[Literal["April", "October"], int]:
    """Roll back version to the previous version

    This function rolls back the version passed to the expected previous version. If the version is April 2024
    it will roll back to October 2023. If the version is October 2023 it will roll back to April 2023.

    Args:
        version: The version to roll back

    Returns:
        The rolled back version
    """

    if version[0] == "October":
        logger.info(f"Rolling back version to April {version[1]}")
        return "April", version[1]

    elif version[0] == "April":
        logger.info(f"Rolling back version to October {version[1] - 1}")
        return "October", version[1] - 1

    else:
        raise ValueError(f"Invalid version: {version}")


def fetch_data(version: Tuple[Literal["April", "October"]] | str = "latest") -> pd.DataFrame:
    """ """

    # if no version is provided or "latest" is passed, get the latest version
    # include roll back logic
    if version == "latest":
        version = gen_latest_version()

        # try to scrape the data for the latest version
        try:
            folder = SDMXScraper.scrape(*version)
            df = SDMXParser.parse(folder)
            logger.info(f"Data fetched successfully for the latest version {version[0]} {version[1]}")
            return df

        # if no data is found for the version, roll back and try again
        except NoDataError:
            logger.debug(f"No data found for the expected latest version {version[0]} {version[1]}."
                         f" Rolling back version")

            version = roll_back_version(version)
            folder = SDMXScraper.scrape(*version)
            df = SDMXParser.parse(folder)
            logger.info(f"Data fetched successfully for version {version[0]} {version[1]}")
            return df

    # if a version is provided, try fetch the data for that version
    version = validate_version_month(version[0]), version[1]
    folder = SDMXScraper.scrape(*version)
    df = SDMXParser.parse(folder)
    logger.info(f"Data fetched successfully for version {version[0]} {version[1]}")
    return df







