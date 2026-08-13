"""Deprecation-warned shims for old cache-clear symbols.

Each shim emits DeprecationWarning pointing at imf_reader.cache.clear_cache and
then delegates to the umbrella.  The old symbols stay at their existing import
paths verbatim — only the implementation is replaced.
"""

import warnings

_MSGS = {
    "weo": (
        "imf_reader.weo.clear_cache is deprecated and will be removed in 3.0. "
        "Use imf_reader.cache.clear_cache() instead."
    ),
    "weo_api": (
        "imf_reader.weo.api.clear_cache is deprecated and will be removed in 3.0. "
        "Use imf_reader.cache.clear_cache() instead."
    ),
    "sdr": (
        "imf_reader.sdr.clear_cache is deprecated and will be removed in 3.0. "
        "Use imf_reader.cache.clear_cache() instead."
    ),
}


def _legacy_weo_clear_cache() -> None:
    """Clear cached WEO data.

    .. deprecated:: 1.5.0
       Use :func:`imf_reader.cache.clear_cache` instead.
    """
    warnings.warn(_MSGS["weo"], DeprecationWarning, stacklevel=2)
    # Imported here, not at module level, so a caller who patches
    # imf_reader.cache.clear_cache (the supported umbrella entry point) still
    # affects this shim — a top-level import would bind our own frozen
    # reference at import time instead of looking it up per call.
    from imf_reader.cache import clear_cache  # noqa: PLC0415

    clear_cache(scope="weo")


def _legacy_weo_api_clear_cache() -> None:
    """Clear the local disk cache for WEO API data.

    .. deprecated:: 1.5.0
       Use :func:`imf_reader.cache.clear_cache` instead.
    """
    warnings.warn(_MSGS["weo_api"], DeprecationWarning, stacklevel=2)
    from imf_reader.cache import clear_cache  # noqa: PLC0415

    clear_cache(scope="weo")


def _legacy_sdr_clear_cache() -> None:
    """Clear the cache for all SDR data.

    .. deprecated:: 1.5.0
       Use :func:`imf_reader.cache.clear_cache` instead.
    """
    warnings.warn(_MSGS["sdr"], DeprecationWarning, stacklevel=2)
    from imf_reader.cache import clear_cache  # noqa: PLC0415

    clear_cache(scope="sdr")
