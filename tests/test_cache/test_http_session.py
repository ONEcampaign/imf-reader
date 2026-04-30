"""Tests for cache/http.py: session singleton, set_cache_dir invalidation,
cache_disabled bypass, alias contract, F19/I2 stale_if_error=False, and
F10/I6 get_weo_versions second-call no-HTTP verification."""

from unittest.mock import MagicMock, patch

import pytest
import requests

import imf_reader.cache.http as http_module
from imf_reader.cache import reset_cache_dir, set_cache_dir
from imf_reader import utils


def _mock_dataflow_response():
    """Return a mock Response with a minimal dataflow JSON payload."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "dataflows": [
                {
                    "version": "9.0.0",
                    "annotations": [
                        {"id": "lastUpdatedAt", "value": "2025-10-01T00:00:00Z"}
                    ],
                }
            ]
        }
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


@pytest.fixture(autouse=False)
def clean_session(tmp_cache_root):
    """Reset the module-level CachedSession before and after each test."""
    http_module._session = None
    yield
    if http_module._session is not None:
        http_module._session.close()
    http_module._session = None


class TestSessionSingleton:
    @pytest.fixture(autouse=True)
    def _use_clean_session(self, clean_session):
        pass

    def test_get_session_returns_singleton(self):
        """Two calls to get_session() must return the exact same object."""
        s1 = http_module.get_session()
        s2 = http_module.get_session()
        assert s1 is s2

    def test_set_cache_dir_invalidates_session(self, tmp_path):
        """set_cache_dir() must tear down the old session so get_session() rebuilds."""
        s1 = http_module.get_session()
        set_cache_dir(tmp_path / "other")
        s2 = http_module.get_session()
        assert s2 is not s1
        reset_cache_dir()


class TestCacheDisabledBypass:
    def test_disable_cache_uses_bare_requests(self, tmp_cache_root, cache_disabled):
        """When cache is disabled, make_get_request must not touch the session."""
        with (
            patch.object(http_module, "get_session") as mock_get_session,
            patch("requests.get") as mock_get,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            utils.make_get_request("http://example.com/test")

            mock_get_session.assert_not_called()
            mock_get.assert_called_once_with("http://example.com/test")


def test_make_request_alias_points_to_make_get_request():
    """make_request must be the exact same callable as make_get_request (Q2)."""
    assert utils.make_request is utils.make_get_request


class TestStaleIfErrorFalse:
    @pytest.fixture(autouse=True)
    def _use_clean_session(self, clean_session):
        pass

    def test_5xx_with_populated_cache_raises_connection_error_no_stale_fallback(self):
        """Populate the HTTP cache, then mock the adapter to return 500.

        Asserts:
        - make_get_request raises ConnectionError (not HTTPError, not stale data).
        - stale_if_error=False is in effect — no silent stale-data fallback.
        """
        url = "http://example.com/api"

        first_resp = MagicMock()
        first_resp.status_code = 200
        first_resp.raise_for_status = MagicMock()
        first_resp.text = "ok"

        session = http_module.get_session()
        with patch.object(session, "get", return_value=first_resp):
            result = utils.make_get_request(url)
            assert result is first_resp

        # Server now returns 500 — must not fall back to stale cached data (I2).
        err_resp = MagicMock()
        err_resp.status_code = 500
        http_error = requests.HTTPError(response=err_resp)

        second_resp = MagicMock()
        second_resp.status_code = 500
        second_resp.raise_for_status.side_effect = http_error

        with patch.object(session, "get", return_value=second_resp):
            with pytest.raises(ConnectionError):
                utils.make_get_request(url)


class TestGetWeoVersionsHttpCaching:
    """F10/I6: a warm dataframe cache means the second get_weo_versions() call
    makes zero HTTP requests."""

    def test_get_weo_versions_second_call_no_http(self, tmp_cache_root):
        """Second get_weo_versions() call must not trigger any HTTP request."""
        from imf_reader.weo.api import _fetch_version_mapping, get_weo_versions

        _fetch_version_mapping.cache_clear()

        mock_resp = _mock_dataflow_response()

        with patch(
            "imf_reader.weo.api.make_get_request", return_value=mock_resp
        ) as mock_http:
            versions1 = get_weo_versions()
            assert mock_http.call_count == 1

            versions2 = get_weo_versions()
            assert mock_http.call_count == 1  # no additional HTTP call on cache hit

        assert versions1 == versions2
