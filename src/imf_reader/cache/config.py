"""Cache root resolution, the enabled flag, and the memoised readerkit objects built on top.

Resolution order for the cache root:
1. The most recent set_cache_dir(...) call (programmatic override) until reset_cache_dir() clears it.
2. The IMF_READER_CACHE_DIR env var if no programmatic override is active.
3. BBLOCKS_CACHE_DIR, readerkit's family-wide fallback shared with sibling packages.
4. platformdirs.user_cache_dir("readerkit", appauthor=False).

readerkit.resolve_cache_dir also inserts a schema-version and app-slug segment ahead of the
version segment, so the resolved root is `<base>/v1/imf-reader/<imf_reader version>`.

get_session() and get_artifact_cache() are memoised against the key they were built with (the
active root, or None when caching is disabled) and rebuilt whenever that key moves.

get_uncached_session() sits outside that scheme. It is memoised against nothing, built once on
first use, and never rebuilt or closed by reset_objects(). It lives for the process.
"""

import contextlib
from datetime import timedelta
from importlib.metadata import version
from pathlib import Path

import requests
from readerkit import ArtifactCache, build_session, resolve_cache_dir

APP: str = "imf-reader"
ENV_VAR: str = "IMF_READER_CACHE_DIR"

# Programmatic override — set by set_cache_dir(), cleared by reset_cache_dir().
_programmatic_override: Path | None = None

# Global cache-enabled toggle. Flipped by enable_cache() / disable_cache() in the umbrella.
_cache_enabled: bool = True

_session: requests.Session | None = None
_session_key: Path | None = None
_uncached_session: requests.Session | None = None
_artifact_caches: dict[str, tuple[Path | None, ArtifactCache]] = {}


def get_active_root() -> Path:
    """Return the resolved cache root, version-segmented. No I/O.

    Called on every dataframe_cache hit, so ensure_exists=False is load-bearing: readerkit's
    default would create the directory and probe-write it on every call.
    """
    return resolve_cache_dir(
        app=APP,
        app_version=version("imf_reader"),
        cache_dir=_programmatic_override,
        env_var=ENV_VAR,
        ensure_exists=False,
    )


def get_http_cache_path() -> Path:
    """Return the HTTP-layer (requests-cache) sublayer directory."""
    return get_active_root() / "http"


def get_bulk_cache_dir() -> Path:
    """Return the WEO bulk-download (SDMX zip) artifact-cache namespace directory."""
    return get_active_root() / "artifacts" / "weo_sdmx"


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

    Closes the memoised session and artifact caches immediately, so the old SQLite handle is
    released at the moment of the call rather than lazily at the next request. No I/O at the old
    path. Overrides any IMF_READER_CACHE_DIR env-var setting until reset_cache_dir() runs.

    Args:
        path: New cache root base (version segment is appended automatically).
    """
    global _programmatic_override
    _programmatic_override = Path(path)
    reset_objects()


def reset_cache_dir() -> None:
    """Clear any programmatic override, restoring env-var or platformdirs default.

    Closes the memoised session and artifact caches immediately, same as set_cache_dir().
    """
    global _programmatic_override
    _programmatic_override = None
    reset_objects()


def is_cache_enabled() -> bool:
    """Return True if caching is currently enabled (the global toggle is on).

    Returns:
        True when caching is active, False when disable_cache() has been called.
    """
    return _cache_enabled


def _set_enabled(flag: bool) -> None:
    """Flip the global cache-enabled toggle.

    A no-op when ``flag`` already matches the current state — objects are only reset on a
    genuine transition. Called by cache.enable_cache() / cache.disable_cache() in the
    umbrella. Not part of the public surface — use the umbrella functions instead.

    Args:
        flag: True to enable, False to disable.
    """
    global _cache_enabled
    if flag == _cache_enabled:
        return
    _cache_enabled = flag
    reset_objects()


def get_session() -> requests.Session:
    """Return the shared cached session, rebuilding it if the root or enabled flag changed.

    Keying on ``get_active_root() if is_cache_enabled() else None`` collapses both
    invalidation triggers (root change, enable/disable flip) into one comparison.
    """
    global _session, _session_key
    key = get_active_root() if is_cache_enabled() else None
    if _session is None or _session_key != key:
        if _session is not None:
            _session.close()
        _session = build_session(
            app=APP,
            cache_dir=key,
            cache_name="http/cache.sqlite",
            backend="sqlite",
            expire_after=timedelta(days=1),
            allowable_codes=(200,),
            allowable_methods=("GET", "POST"),
            # A populated cache must not silently mask a 5xx: callers see a
            # ConnectionError rather than yesterday's data.
            stale_if_error=False,
            # readerkit's "same-origin" default would raise on a cross-host redirect that works
            # today; the SDMX path follows a scraped href that commonly redirects off-host.
            redirect_policy="any",
            # requests allows 30 hops, readerkit 5. The IMF download links chain through
            # several redirectors, so keep the looser cap.
            max_redirects=30,
        )
        _session_key = key
    return _session


def get_uncached_session() -> requests.Session:
    """Return the shared plain (uncached) session, building it on first use.

    It is independent of the cache root and the enabled flag. It never caches responses, so
    there is nothing in either one's configuration to invalidate.
    """
    global _uncached_session
    if _uncached_session is None:
        _uncached_session = build_session(
            app=APP,
            cache_dir=None,
            # Read timeout raised well past the default: bulk_fetcher streams with
            # stream=True, and _TimeoutMixin's timeout is per socket read, not per download.
            timeout=(10.0, 300.0),
            redirect_policy="any",
            max_redirects=30,
        )
    return _uncached_session


def get_artifact_cache(namespace: str) -> ArtifactCache:
    """Return the shared ArtifactCache for *namespace*, rebuilding it if root/enabled changed."""
    key = get_active_root() if is_cache_enabled() else None
    entry = _artifact_caches.get(namespace)
    if entry is None or entry[0] != key:
        if entry is not None:
            with contextlib.suppress(Exception):
                entry[1].close()
        cache = ArtifactCache(cache_dir=key, namespace=namespace)
        _artifact_caches[namespace] = (key, cache)
        return cache
    return entry[1]


def close_session() -> None:
    """Close the memoised cached session so the next get_session() call rebuilds it.

    Called by cache.clear_cache() before it rmtrees the http sublayer, so the open SQLite handle
    never outlives the directory it lives in. It closes nothing else: an artifact cache in bypass
    mode owns a TemporaryDirectory whose paths a caller may still be reading from.
    """
    global _session, _session_key
    if _session is not None:
        with contextlib.suppress(Exception):
            _session.close()
        _session = None
        _session_key = None


def reset_objects() -> None:
    """Close the memoised session and artifact caches so the next access rebuilds them.

    Called by set_cache_dir(), reset_cache_dir() and _set_enabled() after they mutate state,
    where rebuilding every object against the new root or flag is the point. Wrapped in
    contextlib.suppress: a Windows share-mode handle on a still-open file (e.g. a ZipFile from a
    bypass fetch) must not make this raise.
    """
    close_session()
    for _key, cache in _artifact_caches.values():
        with contextlib.suppress(Exception):
            cache.close()
    _artifact_caches.clear()
