"""Module to read exchange rate data from the IMF's Special Drawing Rights (SDR) Valuation dataset.

Read about SDR valuation at: https://www.imf.org/external/np/fin/data/rms_sdrv.aspx
"""

import requests
import pandas as pd
import io
from functools import lru_cache
from typing import Literal

from imf_reader.config import logger


BASE_URL = "https://www.imf.org/external/np/fin/data/rms_sdrv.aspx"


def get_exchange_rates_data():
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
    df = df.iloc[1:].reset_index(drop=True)

    # Ensure required columns are present
    required_columns = ["Report date"]
    for column in required_columns:
        if column not in df.columns:
            raise KeyError(f"Missing required column: {column}")

    return df


def extract_exchange_series(df: pd.DataFrame, col_val: str):
    """
    Extract the exchange rate series for the given column value.
    """
    return (
        df.loc[lambda d: d["Report date"] == col_val].iloc[:, 1].reset_index(drop=True)
    )


def extract_dates_series(df: pd.DataFrame):
    """
    Extract the dates series from the DataFrame.
    """
    return (
        df.dropna(subset=df.columns[3])
        .iloc[:, 0]
        .drop_duplicates()
        .reset_index(drop=True)
    )


def parse_data(df: pd.DataFrame, unit_basis: Literal["SDR", "USD"]):
    """Parse the data from the IMF website"""

    # Validate unit basis
    if unit_basis == "USD":
        col_val = "U.S.$1.00 = SDR"
    elif unit_basis == "SDR":
        col_val = "SDR1 = US$"
    else:
        raise ValueError("unit_basis must be either 'SDR' or 'USD'")

    # Preprocess dataframe and extract relevant columns
    df = preprocess_data(df)
    exchange_series = extract_exchange_series(df, col_val)
    dates_series = extract_dates_series(df)

    return pd.DataFrame(
        {"date": dates_series, "exchange_rate": exchange_series}
    ).assign(
        date=lambda d: pd.to_datetime(d.date),
        exchange_rate=lambda d: pd.to_numeric(d.exchange_rate, errors="coerce"),
    )


@lru_cache
def fetch_exchange_rates(unit_basis: Literal["SDR", "USD"] = "SDR") -> pd.DataFrame:
    """Fetch the historic SDR exchange rates from the IMF

    The currency value of the SDR is determined by summing the values in U.S. dollars, based on market exchange rates, of a basket of major currencies (the U.S. dollar, Euro, Japanese yen, pound sterling and the Chinese renminbi). The SDR currency value is calculated daily except on IMF holidays, or whenever the IMF is closed for business, or on an ad-hoc basis to facilitate unscheduled IMF operations. The SDR valuation basket is reviewed and adjusted every five years.

    Read more at: https://www.imf.org/en/About/Factsheets/Sheets/2023/special-drawing-rights-sdr

    Args:
        unit_basis: The unit basis for the exchange rate. Default is "SDR" i.e. 1 SDR in USD. Other option is "USD" i.e. 1 USD in SDR

    Returns:
        A DataFrame with the exchange rate data
    """

    logger.info("Fetching exchange rate data")

    df = get_exchange_rates_data()
    return parse_data(df, unit_basis)
