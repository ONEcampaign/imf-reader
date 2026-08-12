"""Tests for imf_reader.cache.config, covering root resolution and the memoised readerkit objects."""

from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

import pytest
import requests_cache

import imf_reader.cache.config as cfg


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset config state before and after every test to avoid cross-test pollution."""
    cfg._programmatic_override = None
    cfg._cache_enabled = True
    cfg.reset_objects()
    yield
    cfg._programmatic_override = None
    cfg._cache_enabled = True
    cfg.reset_objects()


def test_default_root_uses_platformdirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """get_active_root() uses platformdirs when no override or env var is set."""
    monkeypatch.delenv(cfg.ENV_VAR, raising=False)
    monkeypatch.delenv("BBLOCKS_CACHE_DIR", raising=False)
    fake_base = str(tmp_path / "fake_cache")

    with patch("platformdirs.user_cache_dir", return_value=fake_base):
        root = cfg.get_active_root()

    # readerkit resolves the platformdirs app name to "readerkit", not "imf_reader".
    # Only the base directory it returns is under our control here.
    assert root.is_relative_to(Path(fake_base))


def test_env_var_overrides_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """IMF_READER_CACHE_DIR env var overrides the platformdirs default."""
    env_path = str(tmp_path / "env_cache")
    monkeypatch.setenv(cfg.ENV_VAR, env_path)

    root = cfg.get_active_root()

    assert root.is_relative_to(Path(env_path))


def test_version_segment_in_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """The resolved root always contains the imf_reader package version as a path segment."""
    monkeypatch.delenv(cfg.ENV_VAR, raising=False)

    root = cfg.get_active_root()
    pkg_version = version("imf_reader")

    assert pkg_version in root.parts


def test_root_shape_is_v1_imf_reader_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """readerkit inserts a schema-version and app-slug segment ahead of the version."""
    monkeypatch.delenv(cfg.ENV_VAR, raising=False)

    root = cfg.get_active_root()

    assert root.parts[-3:] == ("v1", "imf-reader", version("imf_reader"))


def test_get_http_cache_path_under_root() -> None:
    assert cfg.get_http_cache_path() == cfg.get_active_root() / "http"


def test_get_bulk_cache_dir_under_root() -> None:
    assert cfg.get_bulk_cache_dir() == cfg.get_active_root() / "artifacts" / "weo_sdmx"


def test_get_dataframe_cache_dir_under_root() -> None:
    assert cfg.get_dataframe_cache_dir() == cfg.get_active_root() / "sdr"


def test_reset_cache_dir_returns_to_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """reset_cache_dir() restores the env-var or platformdirs default after a programmatic override."""
    env_path = str(tmp_path / "env")
    monkeypatch.setenv(cfg.ENV_VAR, env_path)

    cfg.set_cache_dir(tmp_path / "override")
    assert str(cfg.get_active_root()).startswith(str(tmp_path / "override"))

    cfg.reset_cache_dir()
    assert str(cfg.get_active_root()).startswith(env_path)


def test_get_active_root_does_no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_active_root() must not touch the filesystem (no mkdir, no stat, etc.)."""
    monkeypatch.delenv(cfg.ENV_VAR, raising=False)

    def _fail_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        raise AssertionError("get_active_root() must not call Path.mkdir()")

    monkeypatch.setattr(Path, "mkdir", _fail_mkdir)

    for _ in range(100):
        cfg.get_active_root()


def test_programmatic_override_beats_env_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Programmatic set_cache_dir wins over IMF_READER_CACHE_DIR env var."""
    env_path = str(tmp_path / "a")
    override_path = tmp_path / "b"
    monkeypatch.setenv(cfg.ENV_VAR, env_path)

    cfg.set_cache_dir(override_path)
    assert cfg.get_active_root().is_relative_to(override_path)

    cfg.reset_cache_dir()
    assert cfg.get_active_root().is_relative_to(env_path)


def test_is_cache_enabled_default() -> None:
    """Cache is enabled by default."""
    assert cfg.is_cache_enabled() is True


def test_set_enabled_false() -> None:
    """_set_enabled(False) disables the cache."""
    cfg._set_enabled(False)
    assert cfg.is_cache_enabled() is False


def test_set_enabled_true() -> None:
    """_set_enabled(True) re-enables the cache after disabling."""
    cfg._set_enabled(False)
    cfg._set_enabled(True)
    assert cfg.is_cache_enabled() is True


def test_set_enabled_true_when_already_enabled_is_noop() -> None:
    """_set_enabled(True) while already enabled must not rebuild the session."""
    session_before = cfg.get_session()

    cfg._set_enabled(True)

    assert cfg.get_session() is session_before


def test_set_enabled_false_when_already_disabled_is_noop() -> None:
    """_set_enabled(False) while already disabled must not tear down the bypass artifact cache."""
    cfg._set_enabled(False)
    cache_before = cfg.get_artifact_cache("weo_sdmx")
    bypass_dir = Path(cache_before._bypass_dir.name)
    assert bypass_dir.exists()

    cfg._set_enabled(False)

    assert cfg.get_artifact_cache("weo_sdmx") is cache_before
    assert bypass_dir.exists()


def test_set_enabled_false_then_true_rebuilds_session() -> None:
    """A genuine disable→enable transition still rebuilds the session (regression guard for
    the early-return added for the redundant-toggle case)."""
    session_before = cfg.get_session()

    cfg._set_enabled(False)
    cfg._set_enabled(True)

    assert cfg.get_session() is not session_before


def test_set_enabled_true_then_false_rebuilds_artifact_cache() -> None:
    """A genuine enable→disable transition still rebuilds the artifact cache."""
    cache_before = cfg.get_artifact_cache("weo_sdmx")

    cfg._set_enabled(False)

    assert cfg.get_artifact_cache("weo_sdmx") is not cache_before


def test_get_session_returns_singleton() -> None:
    """Two calls to get_session() must return the exact same object."""
    assert cfg.get_session() is cfg.get_session()


def test_set_cache_dir_rebuilds_session(tmp_path: Path) -> None:
    """set_cache_dir() must tear down the old session so get_session() rebuilds under the new root."""
    s1 = cfg.get_session()

    cfg.set_cache_dir(tmp_path / "other")
    s2 = cfg.get_session()

    assert s2 is not s1
    assert Path(s2.cache.responses.db_path).is_relative_to(tmp_path / "other")


def test_disable_cache_session_is_not_cached_session(tmp_path: Path) -> None:
    """get_session() under disable_cache() must not be a requests_cache.CachedSession."""
    cfg.set_cache_dir(tmp_path)
    cfg._set_enabled(False)

    assert not isinstance(cfg.get_session(), requests_cache.CachedSession)


def test_get_artifact_cache_returns_singleton() -> None:
    """Two calls to get_artifact_cache() for the same namespace return the same object."""
    assert cfg.get_artifact_cache("weo_sdmx") is cfg.get_artifact_cache("weo_sdmx")


def test_set_cache_dir_rebinds_artifact_cache(tmp_path: Path) -> None:
    """set_cache_dir() must rebind the memoised ArtifactCache to the new root."""
    cache1 = cfg.get_artifact_cache("weo_sdmx")

    cfg.set_cache_dir(tmp_path / "other")
    cache2 = cfg.get_artifact_cache("weo_sdmx")

    assert cache2 is not cache1
