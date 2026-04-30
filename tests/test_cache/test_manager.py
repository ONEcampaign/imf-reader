"""Tests for CacheManager."""

import io
import json
import os
import time
from datetime import datetime, timedelta, timezone
from zipfile import ZipFile, is_zipfile

import pytest

from imf_reader.cache.config import reset_cache_dir, set_cache_dir
from imf_reader.cache.manager import CacheManager, _MANIFEST_SUFFIX, _TMP_PATTERN
from imf_reader.config import BulkPayloadCorruptError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_zip_bytes(filename: str = "data.txt", content: str = "hello") -> bytes:
    """Return the raw bytes of a valid in-memory zip."""
    buf = io.BytesIO()
    with ZipFile(buf, "w") as zf:
        zf.writestr(filename, content)
    return buf.getvalue()


def _noop_validator(content: bytes) -> None:
    pass


def _zip_validator(content: bytes) -> None:
    if not is_zipfile(io.BytesIO(content)):
        raise BulkPayloadCorruptError("Not a zip")
    with ZipFile(io.BytesIO(content)) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise BulkPayloadCorruptError(f"Corrupt zip: {bad}")


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path):
    """Redirect the cache root to a temp directory for every test."""
    set_cache_dir(tmp_path)
    yield tmp_path
    reset_cache_dir()


def _make_manager(
    tmp_path, *, sublayer: str = "test_sdmx", ttl_hours: int = 24
) -> CacheManager:
    return CacheManager(sublayer=sublayer, ttl=timedelta(hours=ttl_hours), keep_n=4)


# ---------------------------------------------------------------------------
# test_round_trip
# ---------------------------------------------------------------------------


def test_round_trip(tmp_path):
    mgr = _make_manager(tmp_path)
    payload = _make_zip_bytes()

    path = mgr.get_or_fetch("key_a.zip", lambda: payload, validator=_noop_validator)

    assert path.exists()
    assert path.read_bytes() == payload


# ---------------------------------------------------------------------------
# test_corrupt_payload_raises_BulkPayloadCorruptError_and_removes_entry
# ---------------------------------------------------------------------------


def test_corrupt_payload_raises_BulkPayloadCorruptError_and_removes_entry(tmp_path):
    mgr = _make_manager(tmp_path)
    bad_bytes = b"this is not a zip"

    with pytest.raises(BulkPayloadCorruptError):
        mgr.get_or_fetch("corrupt.zip", lambda: bad_bytes, validator=_zip_validator)

    # Entry must be gone so the next call can re-download cleanly.
    sublayer = mgr._get_sublayer_dir()
    assert not (sublayer / "corrupt.zip").exists()
    assert not (sublayer / f"corrupt.zip{_MANIFEST_SUFFIX}").exists()


# ---------------------------------------------------------------------------
# test_atomic_write_no_orphan_tmp_on_success
# ---------------------------------------------------------------------------


def test_atomic_write_no_orphan_tmp_on_success(tmp_path):
    mgr = _make_manager(tmp_path)
    payload = _make_zip_bytes()
    mgr.get_or_fetch("entry.zip", lambda: payload, validator=_noop_validator)

    sublayer = mgr._get_sublayer_dir()
    tmp_files = [p for p in sublayer.iterdir() if _TMP_PATTERN in p.name]
    assert tmp_files == [], f"Orphan tmp files found: {tmp_files}"


# ---------------------------------------------------------------------------
# test_startup_sweep_removes_stale_tmp
# ---------------------------------------------------------------------------


def test_startup_sweep_removes_stale_tmp(tmp_path):
    # Pre-create the sublayer directory with a stale tmp file.
    from imf_reader.cache.config import get_active_root

    sublayer_dir = get_active_root() / "test_sdmx"
    sublayer_dir.mkdir(parents=True, exist_ok=True)

    stale_tmp = sublayer_dir / f"weo_april_2020.zip{_TMP_PATTERN}testhost.12345"
    stale_tmp.write_bytes(b"garbage")

    # Age it past the 24-hour threshold.
    stale_time = time.time() - 90_000
    os.utime(stale_tmp, (stale_time, stale_time))

    # Instantiating a new CacheManager triggers the startup sweep.
    _make_manager(tmp_path)

    assert not stale_tmp.exists(), (
        "Stale tmp file should have been removed by startup sweep"
    )


# ---------------------------------------------------------------------------
# test_lru_keeps_n_entries
# ---------------------------------------------------------------------------


def test_lru_keeps_n_entries(tmp_path):
    keep_n = 3
    mgr = CacheManager(sublayer="test_sdmx", ttl=timedelta(hours=24), keep_n=keep_n)
    payload = _make_zip_bytes()
    total = keep_n + 2

    for i in range(total):
        key = f"entry_{i}.zip"
        mgr.get_or_fetch(key, lambda: payload, validator=_noop_validator)
        # Backdate each manifest so entries have strictly increasing created_at times,
        # avoiding the 1-second ISO resolution ambiguity from real-clock writes.
        mp = mgr._manifest_path(key)
        data = json.loads(mp.read_text())
        data["created_at"] = datetime(2020, 1, 1, i, tzinfo=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S%z"
        )
        mp.write_text(json.dumps(data))

    # Write one more entry to trigger eviction (eviction runs after each write).
    final_key = f"entry_{total}.zip"
    mgr.get_or_fetch(final_key, lambda: payload, validator=_noop_validator)

    sublayer = mgr._get_sublayer_dir()
    zip_files = [p for p in sublayer.iterdir() if p.suffix == ".zip"]
    assert len(zip_files) == keep_n, (
        f"Expected {keep_n} zip files after LRU eviction, found {len(zip_files)}: "
        f"{[p.name for p in zip_files]}"
    )


# ---------------------------------------------------------------------------
# test_ttl_expiry_forces_refetch
# ---------------------------------------------------------------------------


def test_ttl_expiry_forces_refetch(tmp_path):
    mgr = CacheManager(sublayer="test_sdmx", ttl=timedelta(hours=1), keep_n=4)
    payload = _make_zip_bytes()

    # Populate the cache.
    mgr.get_or_fetch("entry.zip", lambda: payload, validator=_noop_validator)

    # Backdate the manifest's created_at to force TTL expiry.
    manifest_path = mgr._manifest_path("entry.zip")
    data = json.loads(manifest_path.read_text())
    old_time = datetime(2000, 1, 1, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")
    data["created_at"] = old_time
    manifest_path.write_text(json.dumps(data))

    fetch_count = 0

    def _counting_fetch() -> bytes:
        nonlocal fetch_count
        fetch_count += 1
        return payload

    mgr.get_or_fetch("entry.zip", _counting_fetch, validator=_noop_validator)

    assert fetch_count == 1, "Expected fetch_fn to be called once on TTL expiry"


# ---------------------------------------------------------------------------
# test_cache_hit_does_not_revalidate
# ---------------------------------------------------------------------------


def test_cache_hit_does_not_revalidate(tmp_path):
    mgr = _make_manager(tmp_path)
    payload = _make_zip_bytes()

    # First call: miss — populates the cache.
    mgr.get_or_fetch("entry.zip", lambda: payload, validator=_noop_validator)

    fetch_called = False
    validator_called = False

    def _sentinel_fetch() -> bytes:
        nonlocal fetch_called
        fetch_called = True
        return payload

    def _sentinel_validator(content: bytes) -> None:
        nonlocal validator_called
        validator_called = True

    # Second call: hit — must not invoke fetch_fn or validator.
    mgr.get_or_fetch("entry.zip", _sentinel_fetch, validator=_sentinel_validator)

    assert not fetch_called, "fetch_fn must NOT be called on a cache hit"
    assert not validator_called, (
        "validator must NOT be called on a cache hit (no testzip on hit)"
    )


# ---------------------------------------------------------------------------
# test_set_cache_dir_rebinds_sublayer
# ---------------------------------------------------------------------------


def test_set_cache_dir_rebinds_sublayer(tmp_path):
    mgr = _make_manager(tmp_path)
    payload = _make_zip_bytes()

    # Write to a different root.
    other_root = tmp_path / "other_root"
    set_cache_dir(other_root)

    path = mgr.get_or_fetch("rebind.zip", lambda: payload, validator=_noop_validator)

    assert path.is_relative_to(other_root), (
        f"Entry should be under new root {other_root}, got {path}"
    )
    # Original root must be empty for this key.
    original_root = tmp_path
    assert not (original_root / "rebind.zip").exists()
