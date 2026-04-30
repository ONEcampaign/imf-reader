from typing import Literal

# Type definitions must come before imports to avoid circular import
ValidMonths = Literal["April", "October"]  # Type hint for valid months
Version = tuple[ValidMonths, int]  # Type hint for version as a tuple of month and year

from imf_reader.weo.reader import fetch_data as fetch_data  # noqa: E402
from imf_reader.cache.legacy import (  # noqa: E402,F401
    _legacy_weo_clear_cache as clear_cache,
)
