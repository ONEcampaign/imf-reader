"""File-based binary-payload cache with atomic NFS-safe writes.

Each entry consists of:
  - ``<key>``                  — the raw payload (e.g. a zip file)
  - ``<key>.manifest.json``    — ``{"created_at", "size_bytes", "schema_version"}``

Writes are atomic: the payload is staged to a ``<key>.tmp.<host>.<pid>`` file,
fsynced, then renamed into place so a crashed writer never leaves a half-written
entry visible to readers.

Concurrency safety uses ``SoftFileLock`` (mkdir-based) rather than ``FileLock``
(fcntl/LockFileEx) because OS-level locks are unreliable on NFS/SMB.

Double-checked locking: the cache-hit path reads ``final_path`` + manifest
without acquiring the lock (idempotent); only the miss path takes the lock and
re-checks inside it so a concurrent writer that populated the entry between the
unlocked check and the lock acquisition avoids a redundant download.
"""

import json
import logging
import os
import socket
import tempfile
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from importlib.metadata import version as pkg_version
from pathlib import Path

# SoftFileLock is FS-agnostic; OS-level locks are unreliable on NFS/SMB.
from filelock import SoftFileLock

from imf_reader.cache import config as _cfg
from imf_reader.config import BulkPayloadCorruptError

logger = logging.getLogger(__name__)

_MANIFEST_SUFFIX = ".manifest.json"
_TMP_PATTERN = ".tmp."
_STALE_TMP_SECONDS = (
    86_400  # 24 hours — matches oda_reader; tolerates slow NFS bulk downloads.
)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")


def _parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")


class CacheManager:
    """File-based cache for binary payloads (e.g. WEO SDMX zips).

    Each call to ``get_or_fetch`` returns the on-disk ``Path`` to the cached
    payload.  On a cache miss the ``fetch_fn`` callable is invoked, its result
    validated, and then written atomically.

    Args:
        sublayer: Subdirectory name under the cache root (e.g. ``"weo_sdmx"``).
        ttl: How long a cached entry is considered fresh.
        keep_n: Maximum number of entries to retain (LRU eviction removes oldest
            beyond this limit).  Defaults to ``4``.
    """

    def __init__(self, *, sublayer: str, ttl: timedelta, keep_n: int = 4) -> None:
        self._sublayer = sublayer
        self._ttl = ttl
        self._keep_n = keep_n
        self._sublayer_dir: Path | None = None

        # Register so set_cache_dir(...) rebinds our working directory.
        _cfg.register_listener(self._on_cache_dir_changed)

        # Clean up any orphaned tmp files from previous crashed processes.
        self._sweep_orphan_tmp()

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _get_sublayer_dir(self) -> Path:
        if self._sublayer_dir is None:
            self._sublayer_dir = _cfg.get_active_root() / self._sublayer
        return self._sublayer_dir

    def _final_path(self, key: str) -> Path:
        return self._get_sublayer_dir() / key

    def _manifest_path(self, key: str) -> Path:
        return self._get_sublayer_dir() / f"{key}{_MANIFEST_SUFFIX}"

    def _tmp_path(self, final: Path) -> Path:
        # Append the tmp suffix to the full filename rather than replacing the extension,
        # because Path.with_suffix() forbids interior dots (e.g. ".tmp.host.123" is invalid).
        return (
            final.parent
            / f"{final.name}{_TMP_PATTERN}{socket.gethostname()}.{os.getpid()}"
        )

    def _lock_path(self, key: str) -> Path:
        return self._get_sublayer_dir() / f"{key}.lock"

    def _on_cache_dir_changed(self, new_root: Path) -> None:
        self._sublayer_dir = new_root / self._sublayer

    # ------------------------------------------------------------------
    # TTL helpers
    # ------------------------------------------------------------------

    def _read_manifest(self, key: str) -> dict | None:
        mp = self._manifest_path(key)
        if not mp.exists():
            return None
        try:
            return json.loads(mp.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _not_expired(self, manifest: dict) -> bool:
        try:
            created = _parse_iso(manifest["created_at"])
            return datetime.now(tz=timezone.utc) - created < self._ttl
        except (KeyError, ValueError):
            return False

    # ------------------------------------------------------------------
    # Atomic write helpers
    # ------------------------------------------------------------------

    def _atomic_write(self, final: Path, content: bytes) -> None:
        """Write *content* to *final* atomically via a host+pid-suffixed tmp file."""
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._tmp_path(final)
        try:
            tmp.write_bytes(content)
            # fsync before rename so the data is durable on NFS.
            with tmp.open("r+b") as fh:
                os.fsync(fh.fileno())
            os.replace(tmp, final)
        except BaseException:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _write_manifest(self, key: str, size_bytes: int) -> None:
        data = {
            "created_at": _now_iso(),
            "size_bytes": size_bytes,
            "schema_version": pkg_version("imf_reader"),
        }
        manifest_final = self._manifest_path(key)
        self._atomic_write(manifest_final, json.dumps(data).encode())

    # ------------------------------------------------------------------
    # LRU eviction
    # ------------------------------------------------------------------

    def _evict_lru(self) -> None:
        """Remove the oldest entries beyond ``keep_n``."""
        d = self._get_sublayer_dir()
        if not d.exists():
            return

        entries: list[tuple[datetime, Path]] = []
        for p in d.iterdir():
            # Skip manifests (compound name ends with _MANIFEST_SUFFIX), tmp files, and locks.
            if (
                p.name.endswith(_MANIFEST_SUFFIX)
                or _TMP_PATTERN in p.name
                or p.suffix == ".lock"
            ):
                continue
            manifest = self._read_manifest(p.name)
            if manifest and "created_at" in manifest:
                try:
                    created = _parse_iso(manifest["created_at"])
                    entries.append((created, p))
                except ValueError:
                    pass

        if len(entries) <= self._keep_n:
            return

        # Sort oldest first, evict all beyond keep_n.
        entries.sort(key=lambda t: t[0])
        for _, payload_path in entries[: len(entries) - self._keep_n]:
            try:
                payload_path.unlink(missing_ok=True)
            except OSError:
                pass
            mp = d / f"{payload_path.name}{_MANIFEST_SUFFIX}"
            try:
                mp.unlink(missing_ok=True)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Startup tmp sweep
    # ------------------------------------------------------------------

    def _sweep_orphan_tmp(self) -> None:
        """Remove ``*.tmp.*`` files older than 1 hour left by crashed processes."""
        d = self._get_sublayer_dir()
        if not d.exists():
            return
        cutoff = datetime.now(tz=timezone.utc).timestamp() - _STALE_TMP_SECONDS
        for p in d.iterdir():
            if _TMP_PATTERN not in p.name:
                continue
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_or_fetch(
        self,
        key: str,
        fetch_fn: Callable[[], bytes],
        *,
        validator: Callable[[bytes], None] | None = None,
    ) -> Path:
        """Return the on-disk path to the cached payload for *key*.

        On a cache hit (entry exists and TTL has not expired) the path is returned
        immediately — no re-validation and no lock acquisition.

        On a cache miss the lock is acquired, the entry is re-checked inside the
        lock (double-checked locking — another writer may have populated the entry
        between the unlocked check and the lock acquisition), and if still absent
        ``fetch_fn`` is called to download the content.  The ``validator`` is then
        invoked on the raw bytes; on failure the entry is removed and
        :exc:`~imf_reader.config.BulkPayloadCorruptError` is raised so the next
        call can retry cleanly.

        Args:
            key: Cache key (used as the filename, e.g. ``"weo_april_2024.zip"``).
            fetch_fn: Zero-arg callable that downloads and returns the raw bytes.
            validator: Optional callable that raises on corrupt content.  Called
                only on a cache miss / refetch (never on a hit).

        Returns:
            Absolute ``Path`` to the cached payload on disk.

        Raises:
            BulkPayloadCorruptError: When the downloaded payload fails validation.
        """
        if not _cfg.is_cache_enabled():
            # Bypass: fetch and validate, then materialize the bytes in the system
            # temp directory (NOT the cache root) so disable_cache() truly bypasses
            # the cache layer — no payload is written under the configured cache
            # directory and no manifest is created. The caller still gets a Path
            # to a valid file on disk.
            content = fetch_fn()
            if validator is not None:
                validator(content)
            fd, tmp_name = tempfile.mkstemp(
                prefix="imf_reader_disabled_", suffix=f"_{key}"
            )
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(content)
            except BaseException:
                Path(tmp_name).unlink(missing_ok=True)
                raise
            return Path(tmp_name)

        final = self._final_path(key)
        manifest_p = self._manifest_path(key)

        # --- Hit check WITHOUT lock (idempotent read) ---
        if final.exists() and manifest_p.exists():
            manifest = self._read_manifest(key)
            if manifest is not None and self._not_expired(manifest):
                logger.debug("Cache hit: %s", key)
                return final

        # --- Miss path: acquire lock, re-check, then fetch ---
        lock_file = self._lock_path(key)
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        with SoftFileLock(str(lock_file)):
            # Re-check inside the lock (another writer may have populated by now).
            if final.exists() and manifest_p.exists():
                manifest = self._read_manifest(key)
                if manifest is not None and self._not_expired(manifest):
                    logger.debug("Cache hit (inside lock, populated by peer): %s", key)
                    return final

            content = fetch_fn()
            if validator is not None:
                try:
                    validator(content)
                except BulkPayloadCorruptError:
                    # Remove any partial/corrupt entry before re-raising.
                    try:
                        final.unlink(missing_ok=True)
                    except OSError:
                        pass
                    try:
                        manifest_p.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise
                except Exception as exc:
                    try:
                        final.unlink(missing_ok=True)
                    except OSError:
                        pass
                    try:
                        manifest_p.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise BulkPayloadCorruptError(
                        f"Payload validation failed for {key}: {exc}"
                    ) from exc

            self._atomic_write(final, content)
            self._write_manifest(key, len(content))
            self._evict_lru()

        return final

    def clear(self) -> None:
        """Remove all cached entries (payloads and manifests) in this sublayer."""
        d = self._get_sublayer_dir()
        if not d.exists():
            return
        for p in list(d.iterdir()):
            # SoftFileLock holds a directory at <key>.lock; skip those rather
            # than leak orphaned IsADirectoryError-suppressed entries.
            if p.is_dir():
                continue
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
