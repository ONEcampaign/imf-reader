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
from pathlib import Path
from typing import Literal

from readerkit import ArtifactCache

from imf_reader.cache.config import (
    _set_enabled,
    get_active_root,
)
from imf_reader.cache.config import (
    close_session as _close_session,
)
from imf_reader.cache.config import (
    get_bulk_cache_dir as get_bulk_cache_dir,
)
from imf_reader.cache.config import (
    get_dataframe_cache_dir as get_dataframe_cache_dir,
)
from imf_reader.cache.config import (
    get_http_cache_path as get_http_cache_path,
)
from imf_reader.cache.config import (
    reset_cache_dir as reset_cache_dir,
)
from imf_reader.cache.config import (
    set_cache_dir as set_cache_dir,
)
from imf_reader.config import BulkPayloadCorruptError as BulkPayloadCorruptError

# Expose get_cache_dir as the public name, mirroring oda_reader._cache.config.
get_cache_dir = get_active_root

# The bulk artifact-cache namespaces reachable from each scope. Cleared through
# ArtifactCache.clear() rather than rmtree, since it takes each entry's own lock
# and so can't half-delete a concurrent process's in-flight download.
_SCOPE_TO_BULK_NAMESPACES: dict[str, tuple[str, ...]] = {
    "weo": ("weo_sdmx",),
}

# The plain cache-root subdirectories reachable from each scope. These have no
# readerkit object to delegate to, so they stay a directory rmtree.
_SCOPE_TO_SUBLAYERS: dict[str, tuple[str, ...]] = {
    "weo": ("weo_sdmx_parsed", "weo_api"),
    "sdr": ("sdr",),
    "http": ("http",),
}


def _clear_bulk_namespace(root: Path, namespace: str) -> None:
    """Empty one bulk artifact-cache namespace under *root*.

    Built against the root directly rather than through the memoised factory: while caching is
    disabled that factory hands back a bypass instance whose clear() touches no disk at all,
    which would leave the payloads a later enable_cache() re-serves. Clearing is maintenance on
    the cache root, so it must work whatever the enabled flag says.
    """
    ArtifactCache(cache_dir=root, namespace=namespace).clear()


def clear_cache(scope: Literal["all", "weo", "sdr", "http"] = "all") -> None:
    """Clear cached data for the named scope.

    Args:
        scope: Which sublayers to remove.

            - ``"all"`` (default) — remove every immediate subdir of the cache root.
              Uses a filesystem walk so future sublayers are automatically included,
              rather than a hardcoded list that would silently miss a sublayer added later.
            - ``"weo"`` — remove ``weo_sdmx``, ``weo_sdmx_parsed``, and ``weo_api``.
            - ``"sdr"`` — remove the ``sdr`` sublayer.
            - ``"http"`` — remove the ``http`` sublayer.
    """
    root = get_active_root()

    # Close the HTTP session before rmtree-ing its SQLite file: on Windows the
    # open file would block deletion, and on Unix a stale connection can keep
    # serving rows from the deleted DB until the process exits. Only the session
    # is closed. An artifact cache running in bypass mode owns a temp directory
    # whose paths the caller may still be holding.
    if scope in ("all", "http"):
        _close_session()

    if scope == "all":
        if root.exists():
            # Walk every immediate subdir rather than a hardcoded list, so a sublayer added
            # later is cleared too. This removes artifacts/ and http/ themselves, not just
            # their contents.
            for child in root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
        return

    for namespace in _SCOPE_TO_BULK_NAMESPACES.get(scope, ()):
        _clear_bulk_namespace(root, namespace)

    for sublayer in _SCOPE_TO_SUBLAYERS[scope]:
        path = root / sublayer
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)


def enable_cache() -> None:
    """Re-enable caching after a previous disable_cache() call.

    Has no effect if caching is already enabled.
    """
    _set_enabled(True)


def disable_cache() -> None:
    """Disable caching for this process.

    All decorated functions bypass both the read and write cache paths and call
    through to the underlying function directly.  Has no effect on already-cached
    data on disk, and no effect if caching is already disabled.
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
