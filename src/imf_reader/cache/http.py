"""Shared requests-cache CachedSession for HTTP-layer caching.

All HTTP call sites in imf_reader route through get_session() when caching is
enabled, falling back to bare requests when the cache is disabled (so tests
that patch requests.get / requests.post directly keep working).
"""

from datetime import timedelta
from pathlib import Path

import requests_cache

from imf_reader.cache.config import (
    get_active_root,
    register_clear_listener,
    register_listener,
)

_session: requests_cache.CachedSession | None = None
_session_root: Path | None = None


def _build_session(root: Path) -> requests_cache.CachedSession:
    backend = requests_cache.SQLiteCache(str(root / "http" / "cache.sqlite"))
    return requests_cache.CachedSession(
        backend=backend,
        expire_after=timedelta(days=1),
        allowable_codes=(200,),
        allowable_methods=("GET", "POST"),
        # stale_if_error explicitly False (I2): a populated cache must not
        # silently mask a 5xx — callers must see ConnectionError per the F19
        # contract.
        stale_if_error=False,
    )


def get_session() -> requests_cache.CachedSession:
    """Return the shared CachedSession, rebuilding it if the cache root has changed.

    Compares the current resolved root against the one the session was built
    against. The listener pattern is an optimization; this guard ensures
    set_cache_dir() takes effect even if the listener registry was cleared
    (e.g. by a test fixture) between calls.
    """
    global _session, _session_root
    current_root = get_active_root()
    if _session is None or _session_root != current_root:
        if _session is not None:
            _session.close()
        _session = _build_session(current_root)
        _session_root = current_root
    return _session


def _on_root_change(new_root: Path) -> None:
    """Invalidate the cached session when the cache root changes."""
    global _session, _session_root
    if _session is not None:
        _session.close()
        _session = None  # rebuilt lazily on next get_session()
        _session_root = None


def _on_http_clear() -> None:
    """Close the SQLite-backed session before the cache directory is removed.

    A scope='http' or scope='all' clear deletes ``<root>/http/`` from disk; if
    the open SQLite connection survives, it can keep serving deleted cache rows
    on Unix or block the directory removal on Windows. Closing the session here
    forces a fresh connection on the next ``get_session()`` call.
    """
    global _session, _session_root
    if _session is not None:
        _session.close()
        _session = None
        _session_root = None


register_listener(_on_root_change)
register_clear_listener(_on_http_clear, sublayer="http")
