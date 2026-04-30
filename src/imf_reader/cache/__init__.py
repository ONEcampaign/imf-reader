"""Public API for the imf_reader cache subpackage.

Provides a unified interface for cache management across all imf_reader
sub-modules (WEO, SDR).

Usage::

    import imf_reader.cache as cache

    cache.clear_cache()                # clear everything
    cache.clear_cache(scope="weo")     # clear only WEO sublayers
    cache.set_cache_dir("/tmp/my_cache")
    cache.reset_cache_dir()
    print(cache.get_cache_dir())
    cache.disable_cache()
    cache.enable_cache()
"""

import shutil
from typing import Literal

from imf_reader.config import BulkPayloadCorruptError as BulkPayloadCorruptError
from imf_reader.config import logger
from imf_reader.cache.config import (
    _clear_listeners,
    _set_enabled,
    get_active_root,
    get_bulk_cache_dir as get_bulk_cache_dir,
    get_dataframe_cache_dir as get_dataframe_cache_dir,
    get_http_cache_path as get_http_cache_path,
    reset_cache_dir as reset_cache_dir,
    set_cache_dir as set_cache_dir,
)

# Expose get_cache_dir as the public name (I3 — mirrors oda_reader._cache.config).
get_cache_dir = get_active_root

_SCOPE_TO_SUBLAYERS: dict[str, tuple[str, ...]] = {
    "weo": ("weo_sdmx", "weo_sdmx_parsed", "weo_api"),
    "sdr": ("sdr",),
    "http": ("http",),
}


def clear_cache(scope: Literal["all", "weo", "sdr", "http"] = "all") -> None:
    """Clear cached data for the named scope.

    Args:
        scope: Which sublayers to remove.

            - ``"all"`` (default) — remove every immediate subdir of the cache root.
              Uses a filesystem walk so future sublayers are automatically included
              (avoids the F1 failure mode of silently leaking newly-added sublayers).
            - ``"weo"`` — remove ``weo_sdmx``, ``weo_sdmx_parsed``, and ``weo_api``.
            - ``"sdr"`` — remove the ``sdr`` sublayer.
            - ``"http"`` — remove the ``http`` sublayer.
    """
    root = get_active_root()
    target_sublayers: set[str] | None = (
        None if scope == "all" else set(_SCOPE_TO_SUBLAYERS[scope])
    )

    # Close the HTTP session before rmtree-ing its SQLite file: on Windows the
    # open file would block deletion, and on Unix a stale connection can keep
    # serving rows from the deleted DB until the process exits.
    if target_sublayers is None or "http" in target_sublayers:
        from imf_reader.cache import http as _http

        _http._on_http_clear()

    if root.exists():
        if scope == "all":
            # Walk every immediate subdir — no hardcoded list (I5 / decision 17).
            for child in root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
        else:
            for sublayer in _SCOPE_TO_SUBLAYERS[scope]:
                path = root / sublayer
                if path.exists():
                    shutil.rmtree(path, ignore_errors=True)

    # Fire listeners (even when disk was empty) so in-memory state is reset —
    # but only for sublayers in scope, so a scope='sdr' clear can't wipe weo_api.
    _fire_clear_listeners(target_sublayers)


def _fire_clear_listeners(target_sublayers: set[str] | None) -> None:
    for sublayer, cb in list(_clear_listeners):
        if target_sublayers is not None and sublayer not in target_sublayers:
            continue
        try:
            cb()
        except Exception as exc:
            logger.warning("clear-listener %r raised: %s", cb, exc)


def enable_cache() -> None:
    """Re-enable caching after a previous disable_cache() call.

    Has no effect if caching is already enabled.
    """
    _set_enabled(True)


def disable_cache() -> None:
    """Disable caching for this process.

    All decorated functions bypass both the read and write cache paths and call
    through to the underlying function directly.  Has no effect on already-cached
    data on disk.
    """
    _set_enabled(False)


__all__ = [
    "BulkPayloadCorruptError",
    "clear_cache",
    "disable_cache",
    "enable_cache",
    "get_bulk_cache_dir",
    "get_cache_dir",
    "get_dataframe_cache_dir",
    "get_http_cache_path",
    "reset_cache_dir",
    "set_cache_dir",
]
