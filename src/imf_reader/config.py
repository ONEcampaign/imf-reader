"""Configuration for the IMF reader."""

import logging
import warnings


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


# Named after this module until 3.0 so code that configures `imf_reader.config` keeps working.
_logger = logging.getLogger(__name__)


def __getattr__(name: str) -> logging.Logger:
    if name == "logger":
        warnings.warn(
            "imf_reader.config.logger is deprecated and will be removed in 3.0; "
            'configure logging.getLogger("imf_reader") instead.',
            DeprecationWarning,
            stacklevel=2,
        )
        return _logger
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
