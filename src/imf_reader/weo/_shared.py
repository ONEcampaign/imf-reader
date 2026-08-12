"""Helpers shared by both WEO paths (api.py and translate.py).

Neither ``api.py`` nor ``translate.py`` imports the other at this module's own
level (``translate.py`` imports ``api.py`` for ``OUTPUT_COLUMNS`` and
``_fetch_codelist``), so anything both need has to live somewhere neither of
them is: importing it from either sibling at module level would risk a cycle
depending on which of ``reader.py`` / ``weo/__init__.py`` happens to import
first.
"""

import pandas as pd


def _drop_empty_observations(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with a null ``OBS_VALUE``.

    Called from both WEO paths so they return identical frames for the same
    release.
    """
    return df.dropna(subset=["OBS_VALUE"]).reset_index(drop=True)
