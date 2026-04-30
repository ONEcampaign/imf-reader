"""Shared pytest fixtures for the imf_reader test suite.

``tmp_cache_root``:
    Redirects the cache root to a fresh ``tmp_path`` directory for the duration
    of a test, then restores the previous setting.  Use this for any test that
    exercises code decorated with ``@dataframe_cache`` or ``CacheManager`` so
    that on-disk state does not bleed between tests.

``cache_disabled``:
    Disables all caching for the duration of a test, then re-enables it.  Use
    this for tests that patch HTTP internals (``requests.post``, ``requests.get``)
    directly and need to ensure the cache layer is bypassed entirely.
"""

from pathlib import Path

import pytest

from imf_reader.cache import disable_cache, enable_cache, reset_cache_dir, set_cache_dir


@pytest.fixture
def tmp_cache_root(tmp_path: Path):
    """Isolate cache I/O to a per-test temporary directory."""
    set_cache_dir(tmp_path)
    yield tmp_path
    reset_cache_dir()


@pytest.fixture
def cache_disabled():
    """Disable caching for the duration of the test, then re-enable."""
    disable_cache()
    try:
        yield
    finally:
        enable_cache()
