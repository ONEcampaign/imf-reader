"""Module to read SDR interest and exchange rates from the IMF website

"""

import requests
import pandas as pd
import io
from functools import lru_cache

from imf_reader.config import logger


BASE_URL: str = "https://www.imf.org/external/np/fin/data/sdr_ir.aspx"


def get_interest_rates_data():
    """Read the data from the IMF website"""

    data = {
        "__EVENTTARGET": "lbnTSV",
    }

    try:
        response = requests.post(BASE_URL, data=data)
        response.raise_for_status()

    except requests.exceptions.RequestException as e:
        raise ConnectionError(f"Could not connect to {BASE_URL}. Error: {str(e)}")

    try:
        return pd.read_csv(
            io.BytesIO(response.content), delimiter="/t", engine="python"
        )

    except pd.errors.ParserError as e:
        raise ValueError(f"Could not parse data. Error: {str(e)}")


def preprocess_data(df: pd.DataFrame):
    """
    Preprocess the input DataFrame by splitting columns and setting headers.
    """
    df = df.iloc[:, 0].str.split("\t", expand=True)
    df.columns = df.iloc[0]
    df = df.iloc[1:]

    # Ensure required columns are present
    columns = {
        "Effective from": "effective_from",
        "Effective to": "effective_to",
    }
    for column in columns:
        if column not in df.columns:
            raise KeyError(f"Missing required column: {column}")

    return (
        df.rename(columns=columns)
        .loc[:, columns.values()]
        .dropna(subset=["effective_to"])
    )


def _filter_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter the DataFrame to separate rows for dates and SDR interest rates.
    """
    return df.loc[
        lambda d: ~d["effective_from"].isin(["Total", "Floor for SDR Interest Rate"])
    ].reset_index(drop=True)


def _format_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Format the filtered DataFrame into a clean DataFrame with interest rates and dates.
    """
    dates_df = (
        df.loc[lambda d: d["effective_from"] != "SDR Interest Rate"]
        .drop_duplicates()
        .reset_index(drop=True)
    )

    sdr_df = (
        df.loc[lambda d: d["effective_from"] == "SDR Interest Rate"]
        .iloc[:, 1:2]
        .reset_index(drop=True)
    )

    sdr_df.columns = ["interest_rate"]

    return sdr_df.join(dates_df)


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """Cleaning/parsing steps for the data. split tab separated value into separate columns, rename columns, assign types, and additional formatting"""

    df = preprocess_data(df)
    return (
        df.pipe(_filter_data)
        .pipe(_format_data)
        .assign(
            interest_rate=lambda d: pd.to_numeric(d.interest_rate, errors="coerce"),
            effective_from=lambda d: pd.to_datetime(d.effective_from),
            effective_to=lambda d: pd.to_datetime(d.effective_to),
        )
    )


@lru_cache
def fetch_interest_rates() -> pd.DataFrame:
    """Fetch the historic SDR interest rates from the IMF

    The SDR interest rate is based on the sum of the multiplicative products in SDR terms of the currency
    amounts in the SDR valuation basket, the level of the interest rate on the financial
    instrument of each component currency in the basket, and the exchange rate of each currency
    against the SDR. The SDR interest rate for the current week is released on Sunday morning, Washington D.C. time.

    returns:
        A DataFrame with the  historical SDR interest rates
    """

    logger.info("Fetching SDR interest rates")

    df = get_interest_rates_data()
    df = clean_data(df)

    return df


def clear_cache():
    """Clear the cache for all lru_cache-decorated functions."""
    fetch_interest_rates.cache_clear()
    logger.info("Cache cleared")
