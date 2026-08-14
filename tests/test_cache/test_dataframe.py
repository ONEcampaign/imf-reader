"""Tests for the dataframe_cache decorator (cache/dataframe.py)."""

import logging
import os
import pickle
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import imf_reader.cache.config as cfg
from imf_reader.cache import disable_cache, enable_cache
from imf_reader.cache.dataframe import (
    _read_failure_counts,
    _write_failure_counts,
    dataframe_cache,
)


@pytest.fixture(autouse=True)
def _reset_config(tmp_path: Path) -> None:
    """Isolate every test: fresh cache root + reset config state.

    Also clears the module-level write- and read-failure counters: they are
    keyed by cache key (module + qualname + args hash), not by cache root, so
    two tests reusing the same closure signature and args would otherwise see
    each other's consecutive-failure counts.
    """
    cfg._programmatic_override = tmp_path
    cfg.reset_objects()
    cfg._cache_enabled = True
    _write_failure_counts.clear()
    _read_failure_counts.clear()
    yield
    cfg._programmatic_override = None
    cfg.reset_objects()
    cfg._cache_enabled = True
    _write_failure_counts.clear()
    _read_failure_counts.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_df_fn(call_tracker: list[int]) -> object:
    @dataframe_cache(ttl=timedelta(days=7), sublayer="test_df")
    def fetch(x: int = 1) -> pd.DataFrame:
        call_tracker.append(x)
        return pd.DataFrame({"a": [x], "b": [x * 2]})

    return fetch


def _make_tuple_fn(call_tracker: list[int]) -> object:
    @dataframe_cache(ttl=timedelta(days=7), sublayer="test_tuple")
    def fetch_tuple(year: int = 2024, month: int = 4) -> tuple[int, int]:
        call_tracker.append(1)
        return (year, month)

    return fetch_tuple


# Defined at module scope, unlike the helpers above, so its __qualname__ has no
# "<locals>" segment to sanitize. The prefix test below needs the raw
# fn.__qualname__ to already be filesystem-safe.
@dataframe_cache(ttl=timedelta(days=7), sublayer="test_prefix")
def _fetch_for_prefix_test(x: int = 1) -> pd.DataFrame:
    return pd.DataFrame({"v": [x]})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dataframe_round_trip() -> None:
    """A DataFrame result is written to disk and read back correctly on the second call."""
    calls: list[int] = []
    fn = _make_df_fn(calls)

    result1 = fn(x=42)
    result2 = fn(x=42)

    assert len(calls) == 1, "Underlying function should be called only once"
    pd.testing.assert_frame_equal(result1, result2)
    assert list(result2["a"]) == [42]


def test_non_dataframe_round_trip() -> None:
    """A non-DataFrame return value is pickled and restored correctly."""
    calls: list[int] = []
    fn = _make_tuple_fn(calls)

    result1 = fn(year=2025, month=10)
    result2 = fn(year=2025, month=10)

    assert len(calls) == 1
    assert result1 == result2 == (2025, 10)


def test_different_args_different_cache_entries() -> None:
    """Different arguments produce independent cache entries."""
    calls: list[int] = []
    fn = _make_df_fn(calls)

    fn(x=1)
    fn(x=2)

    assert len(calls) == 2


def test_cache_clear_attribute_exists_and_works() -> None:
    """Wrapped function exposes .cache_clear() that removes cached files."""
    calls: list[int] = []
    fn = _make_df_fn(calls)

    fn(x=10)
    assert len(calls) == 1

    fn.cache_clear()

    fn(x=10)
    assert len(calls) == 2, "After cache_clear(), function should be called again"


def test_attribute_write_persists() -> None:
    """Attribute assignments on the wrapper function object persist."""
    calls: list[int] = []
    fn = _make_df_fn(calls)

    fn.last_version_fetched = ("April", 2024)
    assert fn.last_version_fetched == ("April", 2024)

    fn.last_version_fetched = ("October", 2025)
    assert fn.last_version_fetched == ("October", 2025)


def test_ttl_expiry_forces_refetch(tmp_path: Path) -> None:
    """A result older than the TTL is not used; the function is called again."""
    calls: list[int] = []

    @dataframe_cache(ttl=timedelta(seconds=0), sublayer="test_ttl")
    def fetch_fresh(x: int = 1) -> pd.DataFrame:
        calls.append(x)
        return pd.DataFrame({"v": [x]})

    fetch_fresh(x=99)
    fetch_fresh(x=99)

    assert len(calls) == 2, "Zero TTL should force a call on every invocation"


def test_future_mtime_does_not_extend_ttl() -> None:
    """An entry stamped ahead of the clock is aged at zero, not treated as fresh.

    Windows stamps a written file from a finer clock than the one
    ``datetime.now()`` reads, so a freshly written entry can sit a few
    milliseconds in the future. Left unclamped that reads as a negative age,
    which is less than every ttl and makes a zero-ttl entry look fresh. This
    forces the skew rather than waiting for the platform to produce it.
    """
    calls: list[int] = []

    @dataframe_cache(ttl=timedelta(seconds=0), sublayer="test_skew")
    def fetch_skewed(x: int = 1) -> pd.DataFrame:
        calls.append(x)
        return pd.DataFrame({"v": [x]})

    fetch_skewed(x=1)
    entry = next((cfg.get_active_root() / "test_skew").iterdir())
    ahead = entry.stat().st_mtime + 60
    os.utime(entry, (ahead, ahead))

    fetch_skewed(x=1)

    assert len(calls) == 2


def test_disable_cache_bypasses_disk() -> None:
    """When the cache is disabled, every call hits the underlying function."""
    calls: list[int] = []
    fn = _make_df_fn(calls)

    disable_cache()
    try:
        fn(x=5)
        fn(x=5)
    finally:
        enable_cache()

    assert len(calls) == 2, (
        "Both calls should reach the function when cache is disabled"
    )


def test_cache_filename_prefix_matches_clear_scan() -> None:
    """The on-disk filename starts with the prefix cache_clear() scans for.

    cache_clear() finds entries to delete by matching a filename prefix built
    from the function's module and qualname, independently of how the writer
    builds that same prefix. Pinning the two together here means a change to
    either side that breaks the match shows up as a test failure instead of
    files that silently outlive a cache_clear() call.
    """
    _fetch_for_prefix_test(x=123)

    cache_dir = cfg.get_active_root() / "test_prefix"
    prefix = (
        f"{_fetch_for_prefix_test.__module__}.{_fetch_for_prefix_test.__qualname__}__"
    )
    matches = [p for p in cache_dir.iterdir() if p.name.startswith(prefix)]
    assert len(matches) == 1


def test_enable_cache_after_disable() -> None:
    """Re-enabling the cache after disable restores normal caching behaviour."""
    calls: list[int] = []
    fn = _make_df_fn(calls)

    disable_cache()
    fn(x=7)
    enable_cache()
    fn(x=7)  # cache miss (written while disabled), triggers another call
    fn(x=7)  # cache hit

    # First call: disabled (no cache write)
    # Second call: enabled, miss → writes to cache
    # Third call: enabled, hit → no call
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Hardening: atomic writes, unreadable entries, dead-cache visibility
# ---------------------------------------------------------------------------


def _raise_oserror(*_args: Any, **_kwargs: Any) -> None:
    raise OSError("disk full")


def test_unreadable_parquet_entry_is_a_miss_and_is_unlinked(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A truncated .parquet entry is ignored, warned about, and removed.

    The refetch's own write is also forced to fail here so the poisoned
    file's absence can be checked directly, instead of being masked by a
    fresh, valid file landing back at the same path.
    """
    calls: list[int] = []
    fn = _make_df_fn(calls)
    fn(x=1)

    cache_dir = cfg.get_active_root() / "test_df"
    poisoned = next(cache_dir.iterdir())
    assert poisoned.suffix == ".parquet"
    poisoned.write_bytes(b"not a parquet file")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _raise_oserror)

    with caplog.at_level(logging.WARNING):
        fn(x=1)

    assert len(calls) == 2, "Unreadable entry should force a live re-fetch"
    assert "Ignoring unreadable cache entry" in caplog.text
    assert not poisoned.exists(), "poisoned entry must be unlinked, not left behind"


def test_unreadable_pickle_entry_is_a_miss_and_is_unlinked(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A truncated .pkl entry is ignored, warned about, and removed."""
    calls: list[int] = []
    fn = _make_tuple_fn(calls)
    fn(year=2025, month=10)

    cache_dir = cfg.get_active_root() / "test_tuple"
    poisoned = next(cache_dir.iterdir())
    assert poisoned.suffix == ".pkl"
    poisoned.write_bytes(b"not a pickle")

    monkeypatch.setattr(pickle, "dump", _raise_oserror)

    with caplog.at_level(logging.WARNING):
        fn(year=2025, month=10)

    assert len(calls) == 2, "Unreadable entry should force a live re-fetch"
    assert "Ignoring unreadable cache entry" in caplog.text
    assert not poisoned.exists(), "poisoned entry must be unlinked, not left behind"


def test_write_failure_still_returns_the_result(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A cache that cannot be written must not fail the call (existing behaviour)."""
    calls: list[int] = []
    fn = _make_df_fn(calls)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _raise_oserror)

    with caplog.at_level(logging.WARNING):
        result = fn(x=1)

    assert len(calls) == 1
    assert list(result["a"]) == [1]
    assert "Failed to write cache entry" in caplog.text
    assert "OSError" in caplog.text, "the exception type should be in the warning"


def test_no_tmp_files_survive_a_successful_write() -> None:
    """After a successful write, no atomic_write temp file is left behind."""
    calls: list[int] = []
    fn = _make_df_fn(calls)
    fn(x=1)

    cache_dir = cfg.get_active_root() / "test_df"
    tmp_files = [p for p in cache_dir.iterdir() if ".tmp-" in p.name]
    assert tmp_files == []


def test_failed_write_leaves_no_target_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """A write that fails mid-flight leaves neither the target nor a temp file."""
    calls: list[int] = []
    fn = _make_df_fn(calls)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _raise_oserror)

    fn(x=1)

    cache_dir = cfg.get_active_root() / "test_df"
    assert list(cache_dir.iterdir()) == []


def test_single_write_failure_does_not_escalate(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One write failure logs the ordinary warning, not the escalated one."""
    calls: list[int] = []
    fn = _make_df_fn(calls)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _raise_oserror)

    with caplog.at_level(logging.WARNING):
        fn(x=1)

    assert "has failed to write" not in caplog.text


def test_two_consecutive_write_failures_escalate(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Two consecutive write failures for the same cache key escalate once.

    Without this, a parquet cache that can't write at all would fail
    silently into an unread `logger.warning` on every call, forever.
    """
    calls: list[int] = []
    fn = _make_df_fn(calls)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _raise_oserror)

    with caplog.at_level(logging.WARNING):
        fn(x=1)  # same args each time -> same cache key -> consecutive failures
        fn(x=1)

    messages = [r.getMessage() for r in caplog.records]
    escalations = [m for m in messages if "has failed to write" in m]
    assert len(escalations) == 1
    assert "test_df" in escalations[0]


def test_single_read_failure_does_not_escalate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One unreadable entry logs the ordinary warning, not the escalated one."""
    calls: list[int] = []
    fn = _make_df_fn(calls)
    fn(x=1)

    cache_dir = cfg.get_active_root() / "test_df"
    entry = next(cache_dir.iterdir())
    entry.write_bytes(b"corrupt")

    with caplog.at_level(logging.WARNING):
        fn(x=1)

    assert "has failed to read back" not in caplog.text


def test_two_consecutive_read_failures_escalate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Two consecutive unreadable entries for the same cache key escalate once.

    Mirrors the write-side escalation. The scenario this guards against does
    not raise on write: the file lands on disk successfully but fails on
    every subsequent read (a version skew, a partial write that didn't raise,
    a format incompatibility). Without this, every call would do cache hit ->
    read fails -> warn -> unlink -> live refetch -> write "succeeds" ->
    repeat, forever -- caching silently defeated with only per-occurrence
    warnings.
    """
    calls: list[int] = []
    fn = _make_df_fn(calls)
    fn(x=1)

    cache_dir = cfg.get_active_root() / "test_df"
    entry = next(cache_dir.iterdir())

    with caplog.at_level(logging.WARNING):
        entry.write_bytes(b"corrupt-1")
        fn(x=1)  # read failure #1; live refetch rewrites a valid entry
        entry.write_bytes(b"corrupt-2")
        fn(x=1)  # read failure #2, same key -> consecutive

    assert len(calls) == 3
    messages = [r.getMessage() for r in caplog.records]
    escalations = [m for m in messages if "has failed to read back" in m]
    assert len(escalations) == 1
    assert "test_df" in escalations[0]


def test_successful_read_resets_read_failure_counter(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A successful read between two failures resets the streak; no escalation."""
    calls: list[int] = []
    fn = _make_df_fn(calls)
    fn(x=1)

    cache_dir = cfg.get_active_root() / "test_df"
    entry = next(cache_dir.iterdir())

    entry.write_bytes(b"corrupt-1")
    fn(x=1)  # read failure #1; live refetch rewrites a valid entry

    fn(x=1)  # reads the freshly rewritten valid entry: a real cache hit

    entry.write_bytes(b"corrupt-2")
    with caplog.at_level(logging.WARNING):
        fn(x=1)  # read failure again, but the streak was reset by the hit above

    # 3 live calls: the initial miss, the first read-failure refetch, and the
    # second read-failure refetch. The intervening hit adds no live call.
    assert len(calls) == 3
    assert "has failed to read back" not in caplog.text
