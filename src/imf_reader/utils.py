"""Utility functions"""

from collections.abc import Mapping
from typing import NoReturn

import readerkit
import requests

from imf_reader.cache.config import get_session, get_uncached_session


def _raise_connection_error(url: str, exc: Exception) -> NoReturn:
    """Translate a requests exception into ConnectionError and raise it.

    Always raises; return type Never so callers' control flow is understood.
    """
    if isinstance(exc, requests.HTTPError):
        raise ConnectionError(
            f"Could not connect to {url}. Status code: {exc.response.status_code}"
        ) from exc
    raise ConnectionError(f"Could not connect to {url}. Error: {exc}") from exc


def make_get_request(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    use_http_cache: bool = True,
) -> requests.Response:
    """Make a GET request through the shared session.

    Args:
        url: URL to request.
        headers: Optional extra headers for this request.
        use_http_cache: When ``False``, bypass the requests-cache layer for this
            call and go through the shared uncached session instead. Use this for
            payloads that have their own bulk-cache layer (e.g. validated SDMX
            zips) so a corrupt response cannot be retained by the HTTP cache and
            re-served on retry.

    Returns:
        requests.Response: the response object.

    Raises:
        ConnectionError: on any network failure or non-2xx HTTP response.
            The cache does not silently fall back to stale data on 5xx
            (``stale_if_error=False``).
    """
    session = get_session() if use_http_cache else get_uncached_session()
    try:
        response = session.get(url, headers=headers)
        response.raise_for_status()
        return response
    except (requests.RequestException, readerkit.TransportError) as e:
        _raise_connection_error(url, e)


def make_post_request(
    url: str,
    *,
    data: dict | None = None,
    use_http_cache: bool = True,
) -> requests.Response:
    """Make a POST request through the shared session.

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
    session = get_session() if use_http_cache else get_uncached_session()
    try:
        response = session.post(url, data=data)
        response.raise_for_status()
        return response
    except (requests.RequestException, readerkit.TransportError) as e:
        _raise_connection_error(url, e)


# Permanent backwards-compat alias, not deprecated.
make_request = make_get_request
