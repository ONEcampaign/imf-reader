"""DataFrameCache decorator for disk-backed persistent caching of function results.

Wraps a function to cache its return value under <root>/<sublayer>/. DataFrame
results are stored as parquet; everything else as pickle. The wrapped function
exposes .cache_clear() (zero-arg, returns None) and allows arbitrary attribute
assignment on the wrapper (e.g. fetch_data.last_version_fetched = ...).
"""

import functools
import hashlib
import inspect
import logging
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from imf_reader.cache import config as _cfg

logger = logging.getLogger(__name__)


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
        # Capture signature once at decoration time (P2 — avoids per-call overhead).
        sig = inspect.signature(fn)

        def _get_sublayer_dir() -> Path:
            # Always re-resolve so set_cache_dir() takes effect even if the
            # listener registry has been cleared by a test fixture or other
            # caller. The cost is one Path concat per call — negligible.
            return _cfg.get_active_root() / sublayer

        def _make_cache_key(*args: Any, **kwargs: Any) -> str:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            key_repr = repr(sorted(bound.arguments.items()))
            digest = hashlib.sha256(key_repr.encode()).hexdigest()[:16]
            module = fn.__module__ or ""
            return f"{module}.{fn.__qualname__}__{digest}"

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
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            return datetime.now(tz=timezone.utc) - mtime < ttl

        def _read(path: Path) -> Any:
            if path.suffix == ".parquet":
                return pd.read_parquet(path)
            with path.open("rb") as f:
                return pickle.load(f)  # noqa: S301 — trusted local cache files only

        def _write(path: Path, result: Any) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(result, pd.DataFrame):
                result.to_parquet(path)
            else:
                with path.open("wb") as f:
                    pickle.dump(result, f)

        def _do_cache_clear() -> None:
            """Remove all cached files for this function from the sublayer dir."""
            d = _get_sublayer_dir()
            if not d.exists():
                return
            module = fn.__module__ or ""
            prefix = f"{module}.{fn.__qualname__}__"
            for p in d.iterdir():
                if p.name.startswith(prefix):
                    p.unlink(missing_ok=True)

        # Register the clear-callback so umbrella clear_cache() nukes in-memory state.
        # Tagged with our sublayer so a scoped clear (e.g. scope='sdr') cannot reach
        # into another sublayer's files.
        _cfg.register_clear_listener(_do_cache_clear, sublayer=sublayer)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _cfg.is_cache_enabled():
                return fn(*args, **kwargs)

            key = _make_cache_key(*args, **kwargs)
            cached = _find_cache_file(key)
            if cached is not None and _is_fresh(cached):
                logger.debug("Cache hit: %s", cached.name)
                return _read(cached)

            result = fn(*args, **kwargs)
            path = _cache_path(key, result)
            try:
                _write(path, result)
            except Exception as exc:
                logger.warning("Failed to write cache entry %s: %s", path, exc)
            return result

        # Attach cache_clear so sdr/clear_cache.py and user code keep working (F6 + decision 1).
        wrapper.cache_clear = _do_cache_clear  # type: ignore[attr-defined]

        return wrapper

    return decorator
