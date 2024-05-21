"""Module to read and process WEO data"""

import pandas as pd
import xml.etree.ElementTree as ET


def parse_xml(tree: ET.ElementTree) -> pd.DataFrame:
    """Parse the WEO XML tree and return a DataFrame with the data.

    Args:
        tree: The XML tree to parse.

    Returns:
        A DataFrame with the data.
    """

    rows = []  # List of dictionaries to store the data
    root = tree.getroot()
    for series in root[1]:  # Datasets are in the second element of the root
        for obs in series:
            rows.append({**series.attrib, **obs.attrib})

    return pd.DataFrame(rows)


