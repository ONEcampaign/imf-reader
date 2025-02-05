"""Module to get SDR data from the IMF website


info: https://www.imf.org/en/About/Factsheets/Sheets/2023/special-drawing-rights-sdr

"""

from functools import lru_cache
import pandas as pd
import calendar
from bs4 import BeautifulSoup
from datetime import datetime
import logging

from imf_reader.utils import make_request
from imf_reader.config import logger

BASE_URL = "https://www.imf.org/external/np/fin/tad/"
MAIN_PAGE_URL = "https://www.imf.org/external/np/fin/tad/extsdr1.aspx"


def read_tsv(url: str) -> pd.DataFrame:
    """Read a tsv file from url and return a dataframe"""

    try:
        return pd.read_csv(url, delimiter="/t", engine="python")

    except pd.errors.ParserError:
        raise ValueError("SDR data not available for this date")


def clean_df(df: pd.DataFrame) -> pd.DataFrame:
    """Clean the SDR dataframe"""

    df = df.iloc[3:, 0].str.split("\t", expand=True)
    df.columns = ["entity", "holdings", "allocations"]

    return df.assign(
        holdings=lambda d: pd.to_numeric(
            d.holdings.str.replace(r"[^\d.]", "", regex=True), errors="coerce"
        ),
        allocations=lambda d: pd.to_numeric(
            d.allocations.str.replace(r"[^\d.]", "", regex=True), errors="coerce"
        ),
    ).melt(
        id_vars="entity", value_vars=["holdings", "allocations"], var_name="indicator"
    )


def format_date(month: int, year: int) -> str:
    """Return a date as year-month-day where day is the last day in the month"""

    last_day = calendar.monthrange(year, month)[1]
    return f"{year}-{month}-{last_day}"


@lru_cache
def get_holdings_and_allocations_data(
    year: int,
    month: int,
):
    """Get sdr allocations and holdings data for a given month and year"""

    date = format_date(month, year)
    url = f"{BASE_URL}extsdr2.aspx?date1key={date}&tsvflag=Y"

    logger.info(f"Fetching SDR data for date: {date}")

    df = read_tsv(url)
    df = clean_df(df)
    df["date"] = pd.to_datetime(date)

    return df


@lru_cache
def fetch_latest_allocations_holdings_date() -> tuple[int, int]:
    """
    Get the latest available SDR allocation holdings date.
    Returns:
        tuple[int, int]: A tuple containing the year and month of the latest SDR data.
    """

    logger.info("Fetching latest date")

    response = make_request(MAIN_PAGE_URL)
    soup = BeautifulSoup(response.content, "html.parser")
    table = soup.find_all("table")[4]
    row = table.find_all("tr")[1]

    date = row.td.text.strip()
    date = datetime.strptime(date, "%B %d, %Y")

    return date.year, date.month


def fetch_allocations_holdings(date: tuple[int, int] | None = None) -> pd.DataFrame:
    """
    Fetch SDR holdings and allocations data for a given date. If date is not specified or exceeds the latest available
    date, it fetches data for the latest date

    Args:
        date: The year and month to get allocations and holdings data for. e.g. (2024, 11) for November 2024.
        If None, the latest announcements released are fetched

    returns:
        A dataframe with the SDR allocations and holdings data
    """

    if date is None:
        date = fetch_latest_allocations_holdings_date()
    else:
        # Temporarily disable logging while calling fetch_latest_allocations_holdings_date()
        original_logger_level = logger.level
        logger.setLevel(logging.WARNING)
        latest_date = fetch_latest_allocations_holdings_date()
        logger.setLevel(original_logger_level)

        date_obj = datetime(date[0], date[1], 1)
        latest_date_obj = datetime(latest_date[0], latest_date[1], 1)
        if date_obj > latest_date_obj:
            raise ValueError(
                f"SDR data unavailable for: ({date[0]}, {date[1]}).\nLatest available: ({latest_date[0]}, {latest_date[1]})"
            )

    return get_holdings_and_allocations_data(*date)
