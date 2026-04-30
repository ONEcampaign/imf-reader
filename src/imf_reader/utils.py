"""Utility functions"""

from typing import NoReturn

import requests

from imf_reader.cache.config import is_cache_enabled
from imf_reader.cache.http import get_session


def _raise_connection_error(url: str, exc: Exception) -> NoReturn:
    """Translate a requests exception into ConnectionError and raise it.

    Always raises; return type Never so callers' control flow is understood.
    """
    if isinstance(exc, requests.HTTPError):
        raise ConnectionError(
            f"Could not connect to {url}. Status code: {exc.response.status_code}"
        ) from exc
    raise ConnectionError(f"Could not connect to {url}. Error: {exc}") from exc


def make_get_request(url: str, *, use_http_cache: bool = True) -> requests.Response:
    """Make a GET request through the shared CachedSession.

    When caching is disabled (e.g. via ``cache.disable_cache()``), falls
    through to bare ``requests.get`` so test patches on ``requests.get``
    keep working.

    Args:
        url: URL to request.
        use_http_cache: When ``False``, bypass the requests-cache layer for this
            call and go through bare ``requests.get``. Use this for payloads that
            have their own bulk-cache layer (e.g. validated SDMX zips handled by
            ``CacheManager``) so a corrupt response cannot be retained by the
            HTTP cache and re-served on retry.

    Returns:
        requests.Response: the response object.

    Raises:
        ConnectionError: on any network failure or non-2xx HTTP response.
            The cache does not silently fall back to stale data on 5xx
            (``stale_if_error=False``).
    """
    session = get_session() if (is_cache_enabled() and use_http_cache) else requests
    try:
        response = session.get(url)
        response.raise_for_status()
        return response
    except (requests.HTTPError, requests.exceptions.RequestException) as e:
        _raise_connection_error(url, e)


def make_post_request(
    url: str, *, data: dict | None = None, use_http_cache: bool = True
) -> requests.Response:
    """Make a POST request through the shared CachedSession.

    When caching is disabled, falls through to bare ``requests.post``.

    Args:
        url: URL to POST to.
        data: Optional form data dict.
        use_http_cache: When ``False``, bypass the requests-cache layer for this
            call (see :func:`make_get_request` for rationale).

    Returns:
        requests.Response: the response object.

    Raises:
        ConnectionError: on any network failure or non-2xx HTTP response.
            Same ``stale_if_error=False`` contract as ``make_get_request``.
    """
    session = get_session() if (is_cache_enabled() and use_http_cache) else requests
    try:
        response = session.post(url, data=data)
        response.raise_for_status()
        return response
    except (requests.HTTPError, requests.exceptions.RequestException) as e:
        _raise_connection_error(url, e)


# Permanent backwards-compat alias — not deprecated (Q2).
make_request = make_get_request
