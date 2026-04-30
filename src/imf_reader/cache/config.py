"""CacheConfig singleton for imf_reader.

Resolution order for the cache root (precedence rule I4):
1. The most recent set_cache_dir(...) call (programmatic override) until reset_cache_dir() clears it.
2. The IMF_READER_CACHE_DIR env var if no programmatic override is active.
3. platformdirs.user_cache_dir("imf_reader", appauthor=False).

The resolved base is always followed by /<package_version> so every package
upgrade gets a fresh cache directory automatically (F2/F17).
"""

import os
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path

import platformdirs

ENV_VAR: str = "IMF_READER_CACHE_DIR"

# Programmatic override — set by set_cache_dir(), cleared by reset_cache_dir().
_programmatic_override: Path | None = None

# Callbacks fired with the new root whenever set_cache_dir/reset_cache_dir runs.
_listeners: list[Callable[[Path], None]] = []

# Callbacks fired by cache.clear_cache() after disk teardown — for in-memory state cleanup.
# Each entry is (sublayer, callback): the umbrella only fires callbacks whose sublayer
# matches the requested scope, so e.g. clear_cache(scope="sdr") never wipes weo_api state.
_clear_listeners: list[tuple[str, Callable[[], None]]] = []

# Global cache-enabled toggle. Flipped by enable_cache() / disable_cache() in the umbrella.
_cache_enabled: bool = True


def get_active_root() -> Path:
    """Return the resolved cache root, version-segmented. No I/O.

    Resolution order (precedence rule I4):
    1. The most recent set_cache_dir(...) call until reset_cache_dir() clears it.
    2. The IMF_READER_CACHE_DIR env var if no programmatic override is active.
    3. platformdirs.user_cache_dir("imf_reader", appauthor=False).

    Always followed by /<imf_reader package version>.
    """
    if _programmatic_override is not None:
        base = _programmatic_override
    elif env_val := os.environ.get(ENV_VAR):
        base = Path(env_val)
    else:
        base = Path(platformdirs.user_cache_dir("imf_reader", appauthor=False))

    pkg_version = version("imf_reader")
    return base / pkg_version


def get_http_cache_path() -> Path:
    """Return the HTTP-layer (requests-cache) sublayer directory."""
    return get_active_root() / "http"


def get_bulk_cache_dir() -> Path:
    """Return the WEO bulk-download (SDMX zip) sublayer directory."""
    return get_active_root() / "weo_sdmx"


def get_dataframe_cache_dir() -> Path:
    """Return the parsed-DataFrame sublayer directory.

    Note: imf_reader writes parsed DataFrames into per-domain sublayers
    (``sdr``, ``weo_api``, ``weo_sdmx_parsed``). This helper returns the
    SDR sublayer for parity with ``oda_reader._cache.config``; use
    ``get_active_root() / "<sublayer>"`` for the WEO variants.
    """
    return get_active_root() / "sdr"


def set_cache_dir(path: str | Path) -> None:
    """Override the cache root for this process.

    Triggers all registered listeners with the new root. No I/O at the old
    path. Overrides any IMF_READER_CACHE_DIR env-var setting until
    reset_cache_dir() runs.

    Args:
        path: New cache root base (version segment is appended automatically).
    """
    global _programmatic_override
    _programmatic_override = Path(path)
    _fire_listeners()


def reset_cache_dir() -> None:
    """Clear any programmatic override, restoring env-var or platformdirs default.

    Triggers all registered listeners with the restored root.
    """
    global _programmatic_override
    _programmatic_override = None
    _fire_listeners()


def register_listener(cb: Callable[[Path], None]) -> None:
    """Register a callback fired with the new root whenever set_cache_dir or reset_cache_dir runs.

    Args:
        cb: Callable that receives the new resolved root Path.
    """
    _listeners.append(cb)


def unregister_listener(cb: Callable[[Path], None]) -> None:
    """Remove a previously registered path-change listener.

    Args:
        cb: The callback to remove. No-op if not registered.
    """
    try:
        _listeners.remove(cb)
    except ValueError:
        pass


def register_clear_listener(cb: Callable[[], None], *, sublayer: str) -> None:
    """Register a callback fired by cache.clear_cache() after disk teardown.

    Used for in-memory state cleanup (e.g. LRU caches that mirror disk state).
    The umbrella only fires callbacks whose sublayer is part of the cleared
    scope, so a scope='sdr' clear cannot reach into weo_api or http state.

    Args:
        cb: Zero-arg callable called when the cache is cleared.
        sublayer: Sublayer name this callback belongs to (e.g. "sdr", "weo_api",
            "http"). Must match one of the sublayers registered in the umbrella's
            scope mapping.
    """
    _clear_listeners.append((sublayer, cb))


def is_cache_enabled() -> bool:
    """Return True if caching is currently enabled (the global toggle is on).

    Returns:
        True when caching is active, False when disable_cache() has been called.
    """
    return _cache_enabled


def _set_enabled(flag: bool) -> None:
    """Flip the global cache-enabled toggle.

    Called by cache.enable_cache() / cache.disable_cache() in the umbrella.
    Not part of the public surface — use the umbrella functions instead.

    Args:
        flag: True to enable, False to disable.
    """
    global _cache_enabled
    _cache_enabled = flag


def _fire_listeners() -> None:
    """Call every registered path-change listener with the current resolved root."""
    new_root = get_active_root()
    for cb in list(_listeners):
        cb(new_root)
