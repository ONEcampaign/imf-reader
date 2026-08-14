"""Configuration for the IMF reader."""

import logging


class NoDataError(Exception):
    """This is a custom exception that is raised when no UIS data exists"""

    pass


class VersionNotAvailableError(NoDataError):
    """The requested WEO version is not served by the API. The bulk archive may
    still have it."""

    pass


class DataflowDiscoveryError(NoDataError):
    """The IMF's dataflow catalogue responded successfully but carried no
    usable WEO dataflow, so no release can be resolved."""

    pass


class UnexpectedFileError(Exception):
    """This is a custom exception that is raised when an unexpected file is found in the zip folder
    or if there is an issue with the file structure"""

    pass


class BulkPayloadCorruptError(Exception):
    """Raised when a cached or freshly-downloaded bulk payload (e.g., the WEO SDMX zip) fails
    integrity validation. The corrupt cache entry is removed before this is raised, so the next
    call re-downloads cleanly.

    ``key`` and ``reason`` are optional so existing single-message call sites keep working;
    readerkit's ``ArtifactCorruptError`` supplies both when this is raised from a translated
    cache failure.
    """

    is_retryable: bool = True

    def __init__(
        self,
        message: str,
        *,
        key: str | None = None,
        reason: str | None = None,
    ) -> None:
        self.key = key
        self.reason = reason
        super().__init__(message)


# Configure Logging
logger = logging.getLogger(__name__)
shell_handler = logging.StreamHandler()  # Create terminal handler
logger.setLevel(logging.INFO)  # Set levels for the logger, shell and file
shell_handler.setLevel(logging.INFO)  # Set levels for the logger, shell and file

# Format the outputs   "%(levelname)s (%(asctime)s): %(message)s"
fmt_file = "%(levelname)s: %(message)s"
fmt_shell = "%(levelname)s: %(message)s"

shell_formatter = logging.Formatter(fmt_shell)  # Create formatters
shell_handler.setFormatter(shell_formatter)  # Add formatters to handlers
logger.addHandler(shell_handler)  # Add handlers to the logger
logger.propagate = False  # Prevent duplicate logs when user configures root logger
