"""Integration tests for cache.clear_cache().

Populates both the WEO API parquet cache and the WEO SDMX-parsed parquet cache, calls
imf_reader.cache.clear_cache(), and asserts both sublayer directories are empty.

Also covers a per-scope test: populate SDR and WEO sublayers, call
clear_cache(scope="sdr"), and assert the SDR sublayer is empty while the WEO
sublayers are untouched.
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
    cfg.set_cache_dir(tmp_path)
    yield tmp_path
    cfg.reset_cache_dir()
    cfg.reset_objects()


def _fake_df() -> pd.DataFrame:
    return pd.DataFrame({"x": [1, 2, 3]})


# ---------------------------------------------------------------------------
# Helpers to plant cache files directly in sublayer dirs
# ---------------------------------------------------------------------------


def _plant_parquet(sublayer: str, filename: str) -> Path:
    """Write a minimal parquet file into the active cache root's sublayer dir."""
    d = cfg.get_active_root() / sublayer
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    _fake_df().to_parquet(p)
    return p


# ---------------------------------------------------------------------------
# Both WEO layers cleared by umbrella clear_cache()
# ---------------------------------------------------------------------------


def test_clear_cache_clears_both_weo_sublayers(tmp_cache: Path) -> None:
    """clear_cache() removes both weo_sdmx_parsed and weo_api sublayers."""
    api_file = _plant_parquet("weo_api", "some_api_cache.parquet")
    parsed_file = _plant_parquet("weo_sdmx_parsed", "some_sdmx_cache.parquet")

    assert api_file.exists()
    assert parsed_file.exists()

    cache.clear_cache()

    weo_api_dir = cfg.get_active_root() / "weo_api"
    weo_sdmx_parsed_dir = cfg.get_active_root() / "weo_sdmx_parsed"

    assert not any(weo_api_dir.iterdir()) if weo_api_dir.exists() else True
    assert (
        not any(weo_sdmx_parsed_dir.iterdir()) if weo_sdmx_parsed_dir.exists() else True
    )


def test_clear_cache_all_removes_every_sublayer(tmp_cache: Path) -> None:
    """clear_cache(scope='all') removes every subdir of the cache root."""
    _plant_parquet("weo_api", "a.parquet")
    _plant_parquet("sdr", "b.parquet")
    _plant_parquet("weo_sdmx_parsed", "c.parquet")

    cache.clear_cache(scope="all")

    root = cfg.get_active_root()
    subdirs = [c for c in root.iterdir() if c.is_dir()] if root.exists() else []
    assert subdirs == [], f"Expected all subdirs removed, found: {subdirs}"


# ---------------------------------------------------------------------------
# SDR round-trip: populate via dataframe_cache, verify file exists, clear
# ---------------------------------------------------------------------------


def test_sdr_clear_cache_removes_disk_files(tmp_cache: Path) -> None:
    """Populating the SDR cache then calling clear_cache() removes the files."""
    from datetime import timedelta
    from imf_reader.cache.dataframe import dataframe_cache

    calls: list[int] = []

    @dataframe_cache(ttl=timedelta(days=7), sublayer="sdr")
    def _fetch_sdr() -> pd.DataFrame:
        calls.append(1)
        return _fake_df()

    _fetch_sdr()
    sdr_dir = cfg.get_active_root() / "sdr"
    assert sdr_dir.exists() and any(sdr_dir.iterdir()), (
        "Cache file should exist after first call"
    )

    cache.clear_cache(scope="sdr")

    files = list(sdr_dir.iterdir()) if sdr_dir.exists() else []
    assert files == [], "SDR cache dir should be empty after clear_cache(scope='sdr')"


# ---------------------------------------------------------------------------
# Per-scope: clear_cache(scope="sdr") leaves WEO sublayers intact
# ---------------------------------------------------------------------------


def test_clear_cache_per_scope_only_clears_named_scope(tmp_cache: Path) -> None:
    """clear_cache(scope='sdr') empties sdr/ but leaves weo_sdmx_parsed/ and weo_api/ intact."""
    sdr_file = _plant_parquet("sdr", "sdr_data.parquet")
    weo_api_file = _plant_parquet("weo_api", "weo_api_data.parquet")
    weo_sdmx_file = _plant_parquet("weo_sdmx_parsed", "weo_sdmx_data.parquet")

    assert sdr_file.exists()
    assert weo_api_file.exists()
    assert weo_sdmx_file.exists()

    cache.clear_cache(scope="sdr")

    # SDR sublayer must be empty
    sdr_dir = cfg.get_active_root() / "sdr"
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
# Scoped clear leaves other sublayers intact
# ---------------------------------------------------------------------------


def test_scoped_clear_leaves_other_sublayers_intact(tmp_cache: Path) -> None:
    """clear_cache(scope='sdr') must not touch weo_api's files.

    Reproducer for the scope-leak bug: a scope='sdr' clear must only ever remove
    the sdr sublayer, regardless of how many other dataframe_cache-decorated
    sublayers have been populated in the same process.
    """
    from datetime import timedelta
    from imf_reader.cache.dataframe import dataframe_cache

    @dataframe_cache(ttl=timedelta(days=7), sublayer="sdr")
    def _fetch_sdr() -> pd.DataFrame:
        return _fake_df()

    @dataframe_cache(ttl=timedelta(days=7), sublayer="weo_api")
    def _fetch_weo_api() -> pd.DataFrame:
        return _fake_df()

    _fetch_sdr()
    _fetch_weo_api()

    sdr_dir = cfg.get_active_root() / "sdr"
    weo_api_dir = cfg.get_active_root() / "weo_api"
    assert any(sdr_dir.iterdir())
    assert any(weo_api_dir.iterdir())

    cache.clear_cache(scope="sdr")

    # SDR sublayer empty, WEO sublayer untouched.
    assert list(sdr_dir.iterdir()) == [] if sdr_dir.exists() else True
    assert any(weo_api_dir.iterdir()), (
        "scope='sdr' clear must not delete files in weo_api"
    )


# ---------------------------------------------------------------------------
# clear_cache(scope="weo") empties the bulk artifact-cache namespace too
# ---------------------------------------------------------------------------


def test_clear_cache_weo_scope_empties_bulk_namespace(tmp_cache: Path) -> None:
    """clear_cache(scope='weo') empties the weo_sdmx artifact-cache namespace and
    leaves sdr/ intact."""
    from datetime import timedelta

    sdr_file = _plant_parquet("sdr", "sdr_data.parquet")

    def _fetcher(ctx):
        ctx.path.write_bytes(b"payload")

    cfg.get_artifact_cache("weo_sdmx").ensure(
        "weo_april_2024.zip", fetcher=_fetcher, ttl=timedelta(days=7), suffix=".zip"
    )
    assert cfg.get_artifact_cache("weo_sdmx").entries() != []

    cache.clear_cache(scope="weo")

    assert cfg.get_artifact_cache("weo_sdmx").entries() == []
    assert sdr_file.exists(), "scope='weo' clear must not touch the sdr sublayer"


def test_clear_cache_weo_scope_empties_bulk_namespace_while_disabled(
    tmp_cache: Path,
) -> None:
    """clear_cache(scope='weo') empties the bulk namespace on disk even when caching
    is disabled. Clearing is a maintenance operation on the cache root. The enabled
    flag only governs the read/write path."""
    from datetime import timedelta

    def _fetcher(ctx):
        ctx.path.write_bytes(b"payload")

    cfg.get_artifact_cache("weo_sdmx").ensure(
        "weo_april_2024.zip", fetcher=_fetcher, ttl=timedelta(days=7), suffix=".zip"
    )
    bulk_dir = cfg.get_bulk_cache_dir()
    assert [p for p in bulk_dir.iterdir() if p.is_file()] != []

    cache.disable_cache()
    try:
        cache.clear_cache(scope="weo")
    finally:
        cache.enable_cache()

    leftovers = [p for p in bulk_dir.iterdir() if p.is_file()]
    assert leftovers == [], f"bulk namespace should be empty, found: {leftovers}"


# ---------------------------------------------------------------------------
# clear_cache(scope="http") removes the HTTP cache and rebuilds the session
# ---------------------------------------------------------------------------


def test_clear_cache_http_scope_closes_and_removes_session(tmp_cache: Path) -> None:
    """clear_cache(scope='http') removes get_http_cache_path() and the next
    get_session() call returns a new object."""
    session_before = cfg.get_session()
    http_dir = cfg.get_http_cache_path()
    http_dir.mkdir(parents=True, exist_ok=True)
    (http_dir / "cache.sqlite").write_bytes(b"not a real sqlite file")

    cache.clear_cache(scope="http")

    assert not http_dir.exists()
    assert cfg.get_session() is not session_before


def test_clear_cache_http_scope_leaves_bypass_payload_readable(tmp_cache: Path) -> None:
    """A scope='http' clear must not invalidate a bulk payload the caller still holds.

    With caching disabled the artifact cache writes into a temp directory it owns, and closing
    it deletes that directory out from under the returned path."""
    from datetime import timedelta

    def _fetcher(ctx):
        ctx.path.write_bytes(b"payload")

    cache.disable_cache()
    try:
        payload = cfg.get_artifact_cache("weo_sdmx").ensure(
            "weo_april_2024.zip", fetcher=_fetcher, ttl=timedelta(days=7), suffix=".zip"
        )
        assert payload.exists()

        cache.clear_cache(scope="http")

        assert payload.read_bytes() == b"payload"
    finally:
        cache.enable_cache()
