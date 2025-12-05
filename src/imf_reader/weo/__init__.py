from typing import Literal, Tuple

# Type definitions must come before imports to avoid circular import
ValidMonths = Literal["April", "October"]  # Type hint for valid months
Version = Tuple[ValidMonths, int]  # Type hint for version as a tuple of month and year

from imf_reader.weo.reader import clear_cache, fetch_data
