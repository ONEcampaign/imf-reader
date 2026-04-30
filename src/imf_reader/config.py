"""Configuration for the IMF reader."""

import logging


class NoDataError(Exception):
    """This is a custom exception that is raised when no UIS data exists"""

    pass


class UnexpectedFileError(Exception):
    """This is a custom exception that is raised when an unexpected file is found in the zip folder
    or if there is an issue with the file structure"""

    pass


class BulkPayloadCorruptError(Exception):
    """Raised when a cached or freshly-downloaded bulk payload (e.g., the WEO SDMX zip) fails
    integrity validation. The corrupt cache entry is removed before this is raised, so the next
    call re-downloads cleanly."""

    pass


# Configure Logging
logger = logging.getLogger(__name__)
shell_handler = logging.StreamHandler()  # Create terminal handler
logger.setLevel(logging.INFO)  # Set levels for the logger, shell and file
shell_handler.setLevel(logging.INFO)  # Set levels for the logger, shell and file

# Format the outputs   "%(levelname)s (%(asctime)s): %(message)s"
fmt_file = "%(levelname)s: %(message)s"

# "%(levelname)s %(asctime)s [%(filename)s:%(funcName)s:%(lineno)d] %(message)s"
fmt_shell = "%(levelname)s: %(message)s"

shell_formatter = logging.Formatter(fmt_shell)  # Create formatters
shell_handler.setFormatter(shell_formatter)  # Add formatters to handlers
logger.addHandler(shell_handler)  # Add handlers to the logger
logger.propagate = False  # Prevent duplicate logs when user configures root logger
