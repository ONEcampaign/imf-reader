"""Tests for the dataframe_cache decorator (cache/dataframe.py)."""

from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

import imf_reader.cache.config as cfg
from imf_reader.cache import disable_cache, enable_cache
from imf_reader.cache.dataframe import dataframe_cache


@pytest.fixture(autouse=True)
def _reset_config(tmp_path: Path) -> None:
    """Isolate every test: fresh cache root + reset config state."""
    cfg._programmatic_override = tmp_path
    cfg._listeners.clear()
    cfg._clear_listeners.clear()
    cfg._cache_enabled = True
    yield
    cfg._programmatic_override = None
    cfg._listeners.clear()
    cfg._clear_listeners.clear()
    cfg._cache_enabled = True


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
    """Attribute assignments on the wrapper function object persist (F14 contract)."""
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
