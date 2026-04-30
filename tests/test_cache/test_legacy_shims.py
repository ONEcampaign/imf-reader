"""Tests for deprecation-warned legacy shims (cache/legacy.py).

Verifies that the three old clear_cache symbols:
  - imf_reader.weo.clear_cache
  - imf_reader.weo.api.clear_cache
  - imf_reader.sdr.clear_cache

all emit DeprecationWarning with the correct message text, delegate to the
umbrella clear_cache(), and keep their original () -> None signature.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

import imf_reader.cache.config as cfg


@pytest.fixture(autouse=True)
def _reset_config(tmp_path: Path) -> None:
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
# weo.clear_cache
# ---------------------------------------------------------------------------


def test_weo_clear_cache_emits_deprecation_warning() -> None:
    from imf_reader.weo import clear_cache

    with pytest.warns(DeprecationWarning, match="imf_reader.weo.clear_cache"):
        with patch("imf_reader.cache.clear_cache") as mock_cc:
            clear_cache()

    mock_cc.assert_called_once()


def test_weo_clear_cache_message_contains_replacement() -> None:
    from imf_reader.weo import clear_cache

    with pytest.warns(DeprecationWarning) as rec:
        with patch("imf_reader.cache.clear_cache"):
            clear_cache()

    assert "imf_reader.cache.clear_cache" in str(rec[0].message)


def test_weo_clear_cache_no_warning_at_import() -> None:
    """Importing the symbol must not emit a warning — only calling it does."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        from imf_reader.weo import clear_cache  # noqa: F401 — import itself is under test


def test_weo_clear_cache_signature() -> None:
    from imf_reader.weo import clear_cache

    with patch("imf_reader.cache.clear_cache"):
        with pytest.warns(DeprecationWarning):
            result = clear_cache()
    assert result is None


# ---------------------------------------------------------------------------
# weo.api.clear_cache
# ---------------------------------------------------------------------------


def test_weo_api_clear_cache_emits_deprecation_warning() -> None:
    from imf_reader.weo.api import clear_cache

    with pytest.warns(DeprecationWarning, match="imf_reader.weo.api.clear_cache"):
        with patch("imf_reader.cache.clear_cache"):
            clear_cache()


def test_weo_api_clear_cache_message_contains_replacement() -> None:
    from imf_reader.weo.api import clear_cache

    with pytest.warns(DeprecationWarning) as rec:
        with patch("imf_reader.cache.clear_cache"):
            clear_cache()

    assert "imf_reader.cache.clear_cache" in str(rec[0].message)


def test_weo_api_clear_cache_signature() -> None:
    from imf_reader.weo.api import clear_cache

    with patch("imf_reader.cache.clear_cache"):
        with pytest.warns(DeprecationWarning):
            result = clear_cache()
    assert result is None


# ---------------------------------------------------------------------------
# sdr.clear_cache
# ---------------------------------------------------------------------------


def test_sdr_clear_cache_emits_deprecation_warning() -> None:
    from imf_reader.sdr import clear_cache

    with pytest.warns(DeprecationWarning, match="imf_reader.sdr.clear_cache"):
        with patch("imf_reader.cache.clear_cache"):
            clear_cache()


def test_sdr_clear_cache_message_contains_replacement() -> None:
    from imf_reader.sdr import clear_cache

    with pytest.warns(DeprecationWarning) as rec:
        with patch("imf_reader.cache.clear_cache"):
            clear_cache()

    assert "imf_reader.cache.clear_cache" in str(rec[0].message)


def test_sdr_clear_cache_signature() -> None:
    from imf_reader.sdr import clear_cache

    with patch("imf_reader.cache.clear_cache"):
        with pytest.warns(DeprecationWarning):
            result = clear_cache()
    assert result is None


# ---------------------------------------------------------------------------
# Delegation: shims call the umbrella with the right scope
# ---------------------------------------------------------------------------


def test_weo_shim_delegates_to_umbrella_with_weo_scope() -> None:
    from imf_reader.cache.legacy import _legacy_weo_clear_cache

    with patch("imf_reader.cache.clear_cache") as mock_cc:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            _legacy_weo_clear_cache()

    mock_cc.assert_called_once_with(scope="weo")


def test_sdr_shim_delegates_to_umbrella_with_sdr_scope() -> None:
    from imf_reader.cache.legacy import _legacy_sdr_clear_cache

    with patch("imf_reader.cache.clear_cache") as mock_cc:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            _legacy_sdr_clear_cache()

    mock_cc.assert_called_once_with(scope="sdr")
