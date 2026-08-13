"""Functions to scrape the IMF WEO website"""

from datetime import timedelta
from pathlib import Path
from zipfile import ZipFile, is_zipfile

import requests
from readerkit import ArtifactCorruptError, FetchContext, TransportError, bulk_fetcher

from imf_reader.cache.config import get_artifact_cache, get_uncached_session
from imf_reader.config import BulkPayloadCorruptError, NoDataError, logger
from imf_reader.weo import Version

# Root of the media library that serves the published SDMX bulk zips. The IMF's
# download-entire-database HTML pages that used to link into this path are behind
# bot management and unreachable from this package; the zips themselves are on a
# different host (Cloudflare) and are not.
MEDIA_BASE = "https://www.imf.org/-/media/files/publications/weo/weo-database"

_MONTH_ABBR = {"April": "apr", "October": "oct"}

# Every WEO bulk SDMX release ever published. The IMF discontinued the bulk
# archive after April 2025 in favor of the API, so this list is complete and
# cannot rot: no further release will ever appear.
SDMX_RELEASES: tuple[Version, ...] = (
    ("April", 2019),
    ("October", 2019),
    ("April", 2020),
    ("October", 2020),
    ("April", 2021),
    ("October", 2021),
    ("April", 2022),
    ("October", 2022),
    ("April", 2023),
    ("October", 2023),
    ("April", 2024),
    ("October", 2024),
    ("April", 2025),
)

# Corrupt in the IMF's own published archive, not in transit: two independent
# re-downloads of each produce identical bytes with a stable SHA-256 matching
# Content-Length, and a bad CRC-32 on the inner XML. No retry can fix this.
KNOWN_CORRUPT_RELEASES: frozenset[Version] = frozenset(
    {("April", 2021), ("October", 2023)}
)


def _sdmx_url_candidates(month: str, year: int) -> list[str]:
    """Build the observed IMF media-library URL forms for a WEO SDMX release.

    The IMF has published the bulk zip at three different path shapes over time,
    with a hard break between the October 2023 and April 2024 releases, plus one
    one-off (October 2020) that uses a release-number segment instead. There is no
    single formula, so all three forms are returned, ordered so the one actually
    used by the release's era comes first.

    Args:
        month: The month of the data to download. Can be April or October.
        year: The year of the data to download.

    Returns:
        Candidate URLs in the order they should be probed.

    Raises:
        ValueError: If month is not April or October.
    """
    try:
        abbr = _MONTH_ABBR[month]
    except KeyError as e:
        raise ValueError(
            f"Unsupported month: {month!r}. Expected April or October."
        ) from e

    filename = f"weo{abbr}{year}-sdmxdata.zip"
    month_segment_url = f"{MEDIA_BASE}/{year}/{month.lower()}/{filename}"
    bare_url = f"{MEDIA_BASE}/{year}/{filename}"
    # Only the October ("02") form has ever been observed; "01" for April is the
    # symmetric guess. It costs nothing to carry: it is always tried last, and
    # every April release so far has resolved at the bare form first.
    release = "01" if month == "April" else "02"
    release_url = f"{MEDIA_BASE}/{year}/{release}/{filename}"

    if year >= 2024:
        return [month_segment_url, bare_url, release_url]
    return [bare_url, month_segment_url, release_url]


def _resolve_sdmx_url(month: str, year: int) -> str:
    """Find the first working candidate URL for a WEO SDMX release.

    Args:
        month: The month of the data to download. Can be April or October.
        year: The year of the data to download.

    Returns:
        The URL to download the SDMX data.

    Raises:
        NoDataError: If every candidate URL 404s.
        requests.HTTPError: If a candidate returns any other non-2xx status
            (e.g. a 403 from bot management, or a 5xx from the origin).
        ValueError: If month is not April or October.
    """
    candidates = _sdmx_url_candidates(month, year)
    session = get_uncached_session()

    for url in candidates:
        # A ranged GET, not HEAD: this host's HEAD responses are served by Akamai
        # and always come back 403, while a ranged GET is served by Cloudflare and
        # works. Probing with HEAD here silently reintroduces the block. Read
        # through the uncached session directly (not make_request, which calls
        # raise_for_status and would turn the 404 we need to see into a
        # ConnectionError) so a 404 is never written to the HTTP cache either.
        response = session.get(url, headers={"Range": "bytes=0-0"}, stream=True)
        response.close()
        if response.status_code < 400:
            logger.debug("SDMX URL found: %s", url)
            return url
        if response.status_code != 404:
            # Only a 404 means "this candidate doesn't exist, try the next one".
            # Any other failure (403 from bot management, 5xx from the origin, ...)
            # is a real problem, not evidence the release is unpublished, so it must
            # not be swallowed into the same NoDataError as an exhausted candidate
            # list: reader.fetch_data catches NoDataError and rolls back to the
            # previous version, so treating a 403 as "not found" here would make it
            # silently return a different release's data instead of failing loudly.
            # raise_for_status() turns it into requests.HTTPError, which scrape()'s
            # transport-failure handler translates to ConnectionError like every
            # other network failure in this package. Do not "simplify" this back to
            # `< 400` advancing to the next candidate.
            response.raise_for_status()

    tried = "\n".join(candidates)
    raise NoDataError(f"No SDMX data found for {month} {year}. Tried:\n{tried}")


def _corrupt_release_note(month: str, year: int) -> str | None:
    """Explain a known-corrupt release, or return None for anything else.

    Returns:
        The explanation to append to the error message, or None if
        ``(month, year)`` is not in ``KNOWN_CORRUPT_RELEASES``.
    """
    if (month, year) not in KNOWN_CORRUPT_RELEASES:
        return None
    return (
        "This release is corrupt in the IMF's own published archive — the CRC-32 "
        "of the inner XML does not match, and re-downloading reproduces the same "
        "bytes. It cannot be fetched by any means, and this is not a bug in "
        "imf-reader. See the 'Coverage and known issues' section in the README."
    )


def _build_corrupt_error(
    message: str, month: str, year: int, **kwargs: str | None
) -> BulkPayloadCorruptError:
    """Build a BulkPayloadCorruptError for a validation failure.

    For the two releases known to be corrupt at the IMF's own source, the message
    is enriched with an explanation and the error is marked non-retryable, since
    retrying is certain to fail.

    Returns:
        The exception, ready to be raised (or raised with ``from``).
    """
    note = _corrupt_release_note(month, year)
    if note is not None:
        message = f"{message}\n{note}"
    exc = BulkPayloadCorruptError(message, **kwargs)
    if note is not None:
        exc.is_retryable = False
    return exc


class SDMXScraper:
    """Class to resolve and download the IMF WEO SDMX bulk files.
    To use this class, call the scrape method with the month and year of the data to download.
    """

    @staticmethod
    def get_sdmx_url(month: str, year: str | int) -> str:
        """Get the url to download the WEO data in SDMX format.

        Args:
            month: The month of the data to download. Can be April or October.
            year: The year of the data to download.

        Returns:
            The url to download the SDMX data.
        """
        return _resolve_sdmx_url(month, int(year))

    @staticmethod
    def scrape(month: str, year: str | int) -> ZipFile:
        """Pipeline to fetch SDMX files, with disk-backed caching.

        The first call for a given ``(month, year)`` downloads the SDMX zip from
        the IMF website, validates it, and stores it atomically on disk. The zip
        is a few MB and holds an XML payload around ten times that size. Subsequent
        calls within the TTL window (7 days) return the cached copy without any
        HTTP requests.

        Args:
            month: The month of the data to download. Can be April or October.
            year: The year of the data to download.

        Returns:
            The zip file object containing the SDMX data files.

        Raises:
            BulkPayloadCorruptError: If the downloaded zip fails integrity validation.
                April 2021 and October 2023 are corrupt in the IMF's own archive
                (see ``KNOWN_CORRUPT_RELEASES``) and always raise this, regardless
                of retries.
            ConnectionError: On any other network failure while downloading the zip.
        """
        # Normalized once so the closures below can compare directly against
        # KNOWN_CORRUPT_RELEASES, which is keyed on int years.
        year = int(year)
        key = f"weo_{str(month).lower()}_{year}.zip"

        def _fetch(ctx: FetchContext) -> None:
            # The SDMX URL isn't known until it's resolved against the candidate
            # forms, so that resolution happens inside the fetcher: a cache hit
            # skips it entirely.
            sdmx_url = SDMXScraper.get_sdmx_url(month, year)
            bulk_fetcher(sdmx_url, session=get_uncached_session())(ctx)

        def _validate(path: Path) -> None:
            if not is_zipfile(path):
                raise _build_corrupt_error(
                    f"Not a zip file for {month} {year}", month, year
                )
            with ZipFile(path) as zf:
                bad = zf.testzip()
                if bad is not None:
                    raise _build_corrupt_error(
                        f"Corrupt zip for {month} {year}: bad entry {bad!r}",
                        month,
                        year,
                    )

        try:
            path = get_artifact_cache("weo_sdmx").ensure(
                key,
                fetcher=_fetch,
                ttl=timedelta(days=7),
                validator=_validate,
                suffix=".zip",
            )
        except ArtifactCorruptError as exc:
            raise _build_corrupt_error(
                str(exc), month, year, key=exc.key, reason=exc.reason
            ) from exc
        except (TransportError, requests.RequestException) as exc:
            # Covers an exhausted requests.ConnectionError, an HTTPError from
            # raise_for_status(), and a Timeout, none of which the fetcher retries.
            # Every other network failure in the package reaches callers as ConnectionError.
            raise ConnectionError(
                f"Could not download the WEO SDMX data for {month} {year}. Error: {exc}"
            ) from exc
        return ZipFile(str(path))
