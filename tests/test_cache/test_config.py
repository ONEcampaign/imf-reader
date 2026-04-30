"""Tests for imf_reader.cache.config — CacheConfig resolution and listener pattern."""

from importlib.metadata import version
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import imf_reader.cache.config as cfg


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset config state before and after every test to avoid cross-test pollution."""
    cfg._programmatic_override = None
    cfg._listeners.clear()
    cfg._clear_listeners.clear()
    cfg._cache_enabled = True
    yield
    cfg._programmatic_override = None
    cfg._listeners.clear()
    cfg._clear_listeners.clear()
    cfg._cache_enabled = True


def test_default_root_uses_platformdirs(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_active_root() uses platformdirs when no override or env var is set."""
    monkeypatch.delenv(cfg.ENV_VAR, raising=False)
    fake_base = "/fake/cache/dir"

    with patch("platformdirs.user_cache_dir", return_value=fake_base) as mock_pdir:
        root = cfg.get_active_root()

    mock_pdir.assert_called_once_with("imf_reader", appauthor=False)
    assert str(root).startswith(fake_base)


def test_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """IMF_READER_CACHE_DIR env var overrides the platformdirs default."""
    env_path = "/tmp/imf_cache_env"
    monkeypatch.setenv(cfg.ENV_VAR, env_path)

    root = cfg.get_active_root()

    assert str(root).startswith(env_path)


def test_version_segment_in_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """The resolved root always contains the imf_reader package version as a path segment."""
    monkeypatch.delenv(cfg.ENV_VAR, raising=False)

    root = cfg.get_active_root()
    pkg_version = version("imf_reader")

    assert pkg_version in root.parts


def test_set_cache_dir_triggers_listeners(tmp_path: Path) -> None:
    """set_cache_dir fires all registered listeners with the new root."""
    listener = MagicMock()
    cfg.register_listener(listener)

    cfg.set_cache_dir(tmp_path)

    listener.assert_called_once()
    called_path: Path = listener.call_args[0][0]
    assert str(called_path).startswith(str(tmp_path))


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
    """Programmatic set_cache_dir wins over IMF_READER_CACHE_DIR env var (I4 precedence rule)."""
    env_path = str(tmp_path / "a")
    override_path = tmp_path / "b"
    monkeypatch.setenv(cfg.ENV_VAR, env_path)

    cfg.set_cache_dir(override_path)
    assert cfg.get_active_root().is_relative_to(override_path)

    cfg.reset_cache_dir()
    assert cfg.get_active_root().is_relative_to(env_path)


def test_register_clear_listener() -> None:
    """register_clear_listener tags the callback with its sublayer."""
    cb = MagicMock()
    cfg.register_clear_listener(cb, sublayer="sdr")

    assert ("sdr", cb) in cfg._clear_listeners


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


def test_multiple_listeners_all_fired(tmp_path: Path) -> None:
    """All registered listeners are called when set_cache_dir is invoked."""
    listener_a = MagicMock()
    listener_b = MagicMock()
    cfg.register_listener(listener_a)
    cfg.register_listener(listener_b)

    cfg.set_cache_dir(tmp_path)

    listener_a.assert_called_once()
    listener_b.assert_called_once()


def test_unregister_listener(tmp_path: Path) -> None:
    """unregister_listener removes a callback so it is no longer called."""
    listener = MagicMock()
    cfg.register_listener(listener)
    cfg.unregister_listener(listener)

    cfg.set_cache_dir(tmp_path)

    listener.assert_not_called()


def test_reset_cache_dir_triggers_listeners(tmp_path: Path) -> None:
    """reset_cache_dir() also fires listeners."""
    listener = MagicMock()
    cfg.set_cache_dir(tmp_path)
    cfg.register_listener(listener)

    cfg.reset_cache_dir()

    listener.assert_called_once()
