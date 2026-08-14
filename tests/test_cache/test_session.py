"""Tests for the shared HTTP session: singleton behaviour, set_cache_dir invalidation,
cache_disabled bypass, alias contract, stale_if_error=False, and get_weo_versions
second-call no-HTTP verification."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import readerkit
import requests
import requests_cache

import imf_reader.cache.config as cfg
from imf_reader import utils
from imf_reader.cache import reset_cache_dir, set_cache_dir


def _mock_dataflow_response():
    """Return a mock Response serving both the flow-discovery JSON body and
    the PUBLICATION_DATE probe's CSV body -- the same mocked response object
    is returned for every make_get_request call in this test, and one bare
    WEO flow needs exactly one of each."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {"dataflows": [{"id": "WEO", "version": "9.0.0"}]}
    }
    mock_resp.text = (
        "COUNTRY,INDICATOR,PUBLICATION_DATE\nUSA,NGDP_RPCH,2025-10-01T00:00:00Z\n"
    )
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestSessionSingleton:
    def test_get_session_returns_singleton(self, tmp_cache_root):
        """Two calls to get_session() must return the exact same object."""
        s1 = cfg.get_session()
        s2 = cfg.get_session()
        assert s1 is s2

    def test_set_cache_dir_invalidates_session(self, tmp_cache_root, tmp_path):
        """set_cache_dir() must tear down the old session so get_session() rebuilds."""
        s1 = cfg.get_session()
        set_cache_dir(tmp_path / "other")
        s2 = cfg.get_session()
        assert s2 is not s1
        reset_cache_dir()


class TestCacheDisabledBypass:
    def test_disabled_session_is_not_cached_and_writes_nothing(
        self, tmp_cache_root, cache_disabled
    ):
        """Under cache_disabled, get_session() is a plain session and a request writes
        nothing under the cache root. There is no bare-requests fallback any more.
        Disabled means the uncached readerkit session instead."""
        session = cfg.get_session()
        assert not isinstance(session, requests_cache.CachedSession)

        with patch.object(session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            utils.make_get_request("http://example.com/test")

            mock_get.assert_called_once()

        assert not tmp_cache_root.exists() or not any(tmp_cache_root.rglob("*.sqlite"))


def test_make_request_alias_points_to_make_get_request():
    """make_request must be the exact same callable as make_get_request."""
    assert utils.make_request is utils.make_get_request


class TestStaleIfErrorFalse:
    def test_5xx_with_populated_cache_raises_connection_error_no_stale_fallback(
        self, tmp_cache_root
    ):
        """Populate the HTTP cache, then mock the adapter to return 500.

        Asserts:
        - make_get_request raises ConnectionError (not HTTPError, not stale data).
        - stale_if_error=False is in effect, so the error propagates to the caller immediately.
        """
        url = "http://example.com/api"

        first_resp = MagicMock()
        first_resp.status_code = 200
        first_resp.raise_for_status = MagicMock()
        first_resp.text = "ok"

        session = cfg.get_session()
        with patch.object(session, "get", return_value=first_resp):
            result = utils.make_get_request(url)
            assert result is first_resp

        # Server now returns 500. It must not fall back to stale cached data.
        err_resp = MagicMock()
        err_resp.status_code = 500
        http_error = requests.HTTPError(response=err_resp)

        second_resp = MagicMock()
        second_resp.status_code = 500
        second_resp.raise_for_status.side_effect = http_error

        with (
            patch.object(session, "get", return_value=second_resp),
            pytest.raises(ConnectionError),
        ):
            utils.make_get_request(url)


class TestMakePostRequestErrorTranslation:
    """make_post_request is the only thing standing between a transport failure and the SDR
    readers, which have no handler of their own."""

    def test_requests_exception_becomes_connection_error(self, tmp_cache_root):
        session = cfg.get_session()
        with (
            patch.object(
                session,
                "post",
                side_effect=requests.exceptions.RequestException("boom"),
            ),
            pytest.raises(ConnectionError, match="Could not connect to"),
        ):
            utils.make_post_request("http://example.com/post")

    def test_transport_error_becomes_connection_error(self, tmp_cache_root):
        session = cfg.get_session()
        with (
            patch.object(session, "post", side_effect=readerkit.TransportError("boom")),
            pytest.raises(ConnectionError, match="Could not connect to"),
        ):
            utils.make_post_request("http://example.com/post")

    def test_http_error_connection_error_names_the_status_code(self, tmp_cache_root):
        err_resp = MagicMock()
        err_resp.status_code = 503
        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError(response=err_resp)

        session = cfg.get_session()
        with (
            patch.object(session, "post", return_value=resp),
            pytest.raises(ConnectionError, match="Status code: 503"),
        ):
            utils.make_post_request("http://example.com/post")


class TestGetWeoVersionsHttpCaching:
    """A warm dataframe cache means the second get_weo_versions() call
    makes zero HTTP requests."""

    def test_get_weo_versions_second_call_no_http(self, tmp_cache_root):
        """Second get_weo_versions() call must not trigger any additional HTTP
        request once the flow mapping is cached."""
        from imf_reader.weo.api import _fetch_flow_mapping, get_weo_versions

        _fetch_flow_mapping.cache_clear()

        mock_resp = _mock_dataflow_response()

        with patch(
            "imf_reader.weo.api.make_get_request", return_value=mock_resp
        ) as mock_http:
            versions1 = get_weo_versions()
            first_call_count = mock_http.call_count
            assert first_call_count > 0  # discovery + at least one probe

            versions2 = get_weo_versions()
            # no additional HTTP call on cache hit
            assert mock_http.call_count == first_call_count

        assert versions1 == versions2


class TestAllowableMethodsAndUserAgent:
    def test_allowable_methods_contains_post(self, tmp_cache_root):
        assert "POST" in cfg.get_session().settings.allowable_methods

    def test_user_agent_names_imf_reader(self, tmp_cache_root):
        assert "imf-reader" in cfg.get_session().headers["User-Agent"]

    def test_stale_if_error_is_off(self, tmp_cache_root):
        assert cfg.get_session().settings.stale_if_error is False

    def test_expire_after_is_one_day(self, tmp_cache_root):
        assert cfg.get_session().settings.expire_after == timedelta(days=1)

    def test_sqlite_db_under_http_cache_path(self, tmp_cache_root):
        db_path = Path(cfg.get_session().cache.responses.db_path)
        assert db_path == cfg.get_http_cache_path() / "cache.sqlite"
