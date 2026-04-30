"""Integration tests for cache.clear_cache().

F1 reproducer: populate both the WEO API parquet cache and the WEO SDMX-parsed
parquet cache, call imf_reader.cache.clear_cache(), and assert both sublayer
directories are empty.

Q1 per-scope test: populate SDR + WEO sublayers, call clear_cache(scope="sdr"),
assert the SDR sublayer is empty and the WEO sublayers are untouched.
"""

from pathlib import Path

import pandas as pd
import pytest

import imf_reader.cache.config as cfg
import imf_reader.cache as cache


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_cache(tmp_path: Path) -> Path:
    """Point the cache at a fresh tmp directory for this test."""
    cfg._programmatic_override = tmp_path
    cfg._listeners.clear()
    cfg._clear_listeners.clear()
    cfg._cache_enabled = True
    yield tmp_path
    cfg._programmatic_override = None
    cfg._listeners.clear()
    cfg._clear_listeners.clear()
    cfg._cache_enabled = True


def _fake_df() -> pd.DataFrame:
    return pd.DataFrame({"x": [1, 2, 3]})


# ---------------------------------------------------------------------------
# Helpers to plant cache files directly in sublayer dirs
# ---------------------------------------------------------------------------


def _plant_parquet(root: Path, sublayer: str, filename: str) -> Path:
    """Write a minimal parquet file into <root>/<pkg_version>/<sublayer>/."""
    from importlib.metadata import version

    pkg_ver = version("imf_reader")
    d = root / pkg_ver / sublayer
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    _fake_df().to_parquet(p)
    return p


# ---------------------------------------------------------------------------
# F1 reproducer: both WEO layers cleared by umbrella clear_cache()
# ---------------------------------------------------------------------------


def test_clear_cache_clears_both_weo_sublayers(tmp_cache: Path) -> None:
    """F1 fix: clear_cache() removes both weo_sdmx_parsed and weo_api sublayers."""
    from importlib.metadata import version

    pkg_ver = version("imf_reader")

    api_file = _plant_parquet(tmp_cache, "weo_api", "some_api_cache.parquet")
    parsed_file = _plant_parquet(
        tmp_cache, "weo_sdmx_parsed", "some_sdmx_cache.parquet"
    )

    assert api_file.exists()
    assert parsed_file.exists()

    cache.clear_cache()

    weo_api_dir = tmp_cache / pkg_ver / "weo_api"
    weo_sdmx_parsed_dir = tmp_cache / pkg_ver / "weo_sdmx_parsed"

    assert not any(weo_api_dir.iterdir()) if weo_api_dir.exists() else True
    assert (
        not any(weo_sdmx_parsed_dir.iterdir()) if weo_sdmx_parsed_dir.exists() else True
    )


def test_clear_cache_all_removes_every_sublayer(tmp_cache: Path) -> None:
    """clear_cache(scope='all') removes every subdir of the cache root."""
    from importlib.metadata import version

    pkg_ver = version("imf_reader")

    _plant_parquet(tmp_cache, "weo_api", "a.parquet")
    _plant_parquet(tmp_cache, "sdr", "b.parquet")
    _plant_parquet(tmp_cache, "weo_sdmx_parsed", "c.parquet")

    cache.clear_cache(scope="all")

    root = tmp_cache / pkg_ver
    subdirs = [c for c in root.iterdir() if c.is_dir()] if root.exists() else []
    assert subdirs == [], f"Expected all subdirs removed, found: {subdirs}"


# ---------------------------------------------------------------------------
# SDR round-trip: populate via dataframe_cache, verify file exists, clear
# ---------------------------------------------------------------------------


def test_sdr_clear_cache_removes_disk_files(tmp_cache: Path) -> None:
    """Populating the SDR cache then calling clear_cache() removes the files."""
    from datetime import timedelta
    from importlib.metadata import version
    from imf_reader.cache.dataframe import dataframe_cache

    pkg_ver = version("imf_reader")
    calls: list[int] = []

    @dataframe_cache(ttl=timedelta(days=7), sublayer="sdr")
    def _fetch_sdr() -> pd.DataFrame:
        calls.append(1)
        return _fake_df()

    _fetch_sdr()
    sdr_dir = tmp_cache / pkg_ver / "sdr"
    assert sdr_dir.exists() and any(sdr_dir.iterdir()), (
        "Cache file should exist after first call"
    )

    cache.clear_cache(scope="sdr")

    files = list(sdr_dir.iterdir()) if sdr_dir.exists() else []
    assert files == [], "SDR cache dir should be empty after clear_cache(scope='sdr')"


# ---------------------------------------------------------------------------
# Q1 per-scope: clear_cache(scope="sdr") leaves WEO sublayers intact
# ---------------------------------------------------------------------------


def test_clear_cache_per_scope_only_clears_named_scope(tmp_cache: Path) -> None:
    """Q1: clear_cache(scope='sdr') empties sdr/ but leaves weo_sdmx_parsed/ and weo_api/ intact."""
    from importlib.metadata import version

    pkg_ver = version("imf_reader")

    sdr_file = _plant_parquet(tmp_cache, "sdr", "sdr_data.parquet")
    weo_api_file = _plant_parquet(tmp_cache, "weo_api", "weo_api_data.parquet")
    weo_sdmx_file = _plant_parquet(
        tmp_cache, "weo_sdmx_parsed", "weo_sdmx_data.parquet"
    )

    assert sdr_file.exists()
    assert weo_api_file.exists()
    assert weo_sdmx_file.exists()

    cache.clear_cache(scope="sdr")

    # SDR sublayer must be empty
    sdr_dir = tmp_cache / pkg_ver / "sdr"
    sdr_files = list(sdr_dir.iterdir()) if sdr_dir.exists() else []
    assert sdr_files == [], f"SDR sublayer should be empty, found: {sdr_files}"

    # WEO sublayers must be intact
    assert weo_api_file.exists(), (
        "weo_api file should be untouched by scope='sdr' clear"
    )
    assert weo_sdmx_file.exists(), (
        "weo_sdmx_parsed file should be untouched by scope='sdr' clear"
    )


# ---------------------------------------------------------------------------
# clear_cache on empty root is a no-op (no exception)
# ---------------------------------------------------------------------------


def test_clear_cache_empty_root_is_noop(tmp_cache: Path) -> None:
    """clear_cache() on a non-existent cache root does not raise."""
    cache.clear_cache()  # root doesn't exist yet — must not raise


# ---------------------------------------------------------------------------
# Scoped clear must not fire listeners outside its scope
# ---------------------------------------------------------------------------


def test_scoped_clear_does_not_fire_other_sublayer_listeners(tmp_cache: Path) -> None:
    """clear_cache(scope='sdr') must not trigger weo_api / weo_sdmx_parsed clear callbacks.

    Reproducer for the scope-leak bug: when both SDR and WEO modules have been
    imported, every dataframe_cache(...) registers a clear-listener. Pre-fix,
    _fire_clear_listeners() ran them all on every clear, so a scope='sdr' clear
    silently deleted weo_api parquet files too.
    """
    from datetime import timedelta
    from importlib.metadata import version
    from imf_reader.cache.dataframe import dataframe_cache

    pkg_ver = version("imf_reader")

    @dataframe_cache(ttl=timedelta(days=7), sublayer="sdr")
    def _fetch_sdr() -> pd.DataFrame:
        return _fake_df()

    @dataframe_cache(ttl=timedelta(days=7), sublayer="weo_api")
    def _fetch_weo_api() -> pd.DataFrame:
        return _fake_df()

    _fetch_sdr()
    _fetch_weo_api()

    sdr_dir = tmp_cache / pkg_ver / "sdr"
    weo_api_dir = tmp_cache / pkg_ver / "weo_api"
    assert any(sdr_dir.iterdir())
    assert any(weo_api_dir.iterdir())

    cache.clear_cache(scope="sdr")

    # SDR sublayer empty, WEO sublayer untouched.
    assert list(sdr_dir.iterdir()) == [] if sdr_dir.exists() else True
    assert any(weo_api_dir.iterdir()), (
        "scope='sdr' clear must not delete files in weo_api (listener-leak regression)"
    )
