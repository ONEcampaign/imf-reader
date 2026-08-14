"""DataFrameCache decorator for disk-backed persistent caching of function results.

Wraps a function to cache its return value under <root>/<sublayer>/. DataFrame
results are stored as parquet; everything else as pickle. The wrapped function
exposes .cache_clear() (zero-arg, returns None) and allows arbitrary attribute
assignment on the wrapper (e.g. fetch_data.last_version_fetched = ...).
"""

import functools
import logging
import pickle
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from readerkit import cache_key_for_call

# readerkit internal, used deliberately: this package's artifact cache already
# depends on the same helper, and readerkit is a sibling released in step.
from readerkit._atomic import atomic_write

from imf_reader.cache import config as _cfg

logger = logging.getLogger(__name__)

# Consecutive cache-write and cache-read failure counts per cache key, shared
# across every decorated function. Cache keys already embed module + qualname
# + call args, so collisions across functions are impossible. No public
# surface: this is purely to detect a cache that has gone silently and
# permanently dead. The two counters are independent -- a write success does
# not clear a read-failure streak and vice versa, since they diagnose
# different failure modes (nothing persists vs. what persists can't be read
# back).
_write_failure_counts: dict[str, int] = {}
_read_failure_counts: dict[str, int] = {}


def dataframe_cache(
    *,
    ttl: timedelta,
    sublayer: str,
) -> Any:
    """Decorator factory that caches a function's return value to disk.

    Args:
        ttl: How long cached results are valid.
        sublayer: Subdirectory under the cache root (e.g. "weo_api", "sdr").

    Returns:
        Decorator that wraps the target function.
    """

    def decorator(fn: Any) -> Any:
        # Sanitize fn.__qualname__ for use in filenames: nested-defined functions
        # produce names like "outer.<locals>.fetch" which contain "<" and ">",
        # both illegal on Windows (NTFS reserved characters → ENOTSUP/EINVAL on
        # write). Stripping them keeps cache keys portable across platforms.
        safe_qualname = fn.__qualname__.replace("<", "_").replace(">", "_")

        def _get_sublayer_dir() -> Path:
            # Always re-resolve so set_cache_dir() takes effect immediately, even
            # between calls. The cost is one Path concat per call, which is negligible.
            return _cfg.get_active_root() / sublayer

        def _make_cache_key(*args: Any, **kwargs: Any) -> str:
            key = cache_key_for_call(fn, *args, **kwargs)
            module = fn.__module__ or ""
            return f"{module}.{safe_qualname}__{key}"

        def _cache_path(key: str, result: Any) -> Path:
            ext = ".parquet" if isinstance(result, pd.DataFrame) else ".pkl"
            return _get_sublayer_dir() / f"{key}{ext}"

        def _find_cache_file(key: str) -> Path | None:
            d = _get_sublayer_dir()
            for ext in (".parquet", ".pkl"):
                p = d / f"{key}{ext}"
                if p.exists():
                    return p
            return None

        def _is_fresh(path: Path) -> bool:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            # Windows' system clock is coarser (~16ms) than the timestamp NTFS
            # stamps on a write, so a file written moments ago can carry an
            # mtime a few milliseconds ahead of datetime.now(). Clamping keeps
            # that skew from producing a negative age, which compares as less
            # than every ttl and would make a zero-ttl entry look fresh.
            age = max(datetime.now(tz=UTC) - mtime, timedelta(0))
            return age < ttl

        def _read(path: Path) -> Any:
            if path.suffix == ".parquet":
                return pd.read_parquet(path)
            with path.open("rb") as f:
                # S301: unpickling executes arbitrary code, so this is only as
                # trustworthy as the cache directory. Every .pkl here is written
                # by _write below, under a root owned by the running user, and
                # an attacker able to plant a file there can already run code as
                # that user by easier routes. JSON would remove the primitive
                # outright, at the cost of a custom encoding for
                # _fetch_version_mapping, which caches a dict keyed by
                # (month, year) tuples that JSON cannot round-trip.
                return pickle.load(f)  # noqa: S301

        def _write(path: Path, result: Any) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with atomic_write(path) as fh:
                if isinstance(result, pd.DataFrame):
                    result.to_parquet(fh)
                else:
                    pickle.dump(result, fh)

        def _do_cache_clear() -> None:
            """Remove all cached files for this function from the sublayer dir."""
            d = _get_sublayer_dir()
            if not d.exists():
                return
            module = fn.__module__ or ""
            prefix = f"{module}.{safe_qualname}__"
            for p in d.iterdir():
                if p.name.startswith(prefix):
                    p.unlink(missing_ok=True)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _cfg.is_cache_enabled():
                return fn(*args, **kwargs)

            key = _make_cache_key(*args, **kwargs)
            cached = _find_cache_file(key)
            if cached is not None and _is_fresh(cached):
                logger.debug("Cache hit: %s", cached.name)
                try:
                    result = _read(cached)
                except Exception as exc:
                    # A poisoned entry (truncated write, incompatible format, ...)
                    # is treated as a miss, not an error. Unlinking it matters as
                    # much as the try: without it, every later call would re-read
                    # and re-fail against the same file, and only a manual
                    # clear_cache() would recover.
                    _read_failure_counts[key] = _read_failure_counts.get(key, 0) + 1
                    logger.warning(
                        "Ignoring unreadable cache entry %s: %s: %s",
                        cached.name,
                        type(exc).__name__,
                        exc,
                    )
                    if _read_failure_counts[key] >= 2:
                        # Writes can "succeed" (no exception) yet produce files
                        # that fail on every subsequent read -- a version skew,
                        # a partial write that didn't raise, a format
                        # incompatibility. This is the same invisible-forever
                        # failure mode as the write-side one above: left as
                        # ordinary per-call warnings, caching would be
                        # silently defeated on every call, with nothing but a
                        # log level bump to surface it.
                        logger.warning(
                            "Cache sublayer %r has failed to read back %d "
                            "times in a row for %s; results are not being "
                            "served from cache and are being re-fetched on "
                            "every call.",
                            sublayer,
                            _read_failure_counts[key],
                            key,
                        )
                    cached.unlink(missing_ok=True)
                    # falls through to the live call below
                else:
                    _read_failure_counts.pop(key, None)
                    return result

            result = fn(*args, **kwargs)
            path = _cache_path(key, result)
            try:
                _write(path, result)
            except Exception as exc:
                _write_failure_counts[key] = _write_failure_counts.get(key, 0) + 1
                logger.warning(
                    "Failed to write cache entry %s: %s: %s",
                    path,
                    type(exc).__name__,
                    exc,
                )
                if _write_failure_counts[key] >= 2:
                    # A single failure can be bad luck (disk full for a moment,
                    # a transient permission glitch). Two in a row for the same
                    # cache key means the cache is dead, not unlucky -- e.g. a
                    # pyarrow install that can't write parquet at all, silently
                    # re-fetching the full payload on every call while the
                    # package appears to work. Left as an ordinary per-call
                    # warning, that failure mode is easy to miss, so it gets
                    # one louder line naming the sublayer.
                    logger.warning(
                        "Cache sublayer %r has failed to write %d times in a "
                        "row for %s; results are not being persisted and are "
                        "being re-fetched on every call.",
                        sublayer,
                        _write_failure_counts[key],
                        key,
                    )
            else:
                _write_failure_counts.pop(key, None)
            return result

        # Attach cache_clear so sdr/clear_cache.py and user code can clear this
        # function's entries without reaching into module internals.
        wrapper.cache_clear = _do_cache_clear  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]

        return wrapper

    return decorator
