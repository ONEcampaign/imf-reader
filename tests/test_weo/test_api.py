"""Tests for weo api module."""

from unittest.mock import patch

import pytest

from imf_reader.weo import api
from imf_reader.weo.scraper import KNOWN_CORRUPT_RELEASES, SDMX_RELEASES


class TestGetWeoVersions:
    """get_weo_versions() must union the API mapping with the SDMX archive."""

    @patch("imf_reader.weo.api._fetch_version_mapping")
    def test_union_includes_sdmx_only_releases(self, mock_mapping):
        """April 2020 is only in the SDMX archive; the API mapping alone
        (October 2025, April 2025) must not be all that comes back."""
        mock_mapping.return_value = {
            ("October", 2025): "9.0.0",
            ("April", 2025): "6.0.0",
        }

        versions = api.get_weo_versions()

        assert ("April", 2020) in versions
        assert ("October", 2025) in versions

    @patch("imf_reader.weo.api._fetch_version_mapping")
    def test_excludes_known_corrupt_releases(self, mock_mapping):
        mock_mapping.return_value = {
            ("October", 2025): "9.0.0",
            ("April", 2025): "6.0.0",
        }

        versions = api.get_weo_versions()

        assert ("April", 2021) not in versions
        assert ("October", 2023) not in versions

    @patch("imf_reader.weo.api._fetch_version_mapping")
    def test_sorted_newest_first(self, mock_mapping):
        mock_mapping.return_value = {
            ("October", 2025): "9.0.0",
            ("April", 2025): "6.0.0",
        }

        versions = api.get_weo_versions()

        assert versions == sorted(
            versions, key=lambda v: (v[1], 0 if v[0] == "April" else 1), reverse=True
        )
        assert versions[0] == ("October", 2025)

    @patch("imf_reader.weo.api._fetch_version_mapping")
    def test_count_is_api_and_sdmx_minus_corrupt_and_overlap(self, mock_mapping):
        """11 fetchable SDMX releases (13 minus the 2 corrupt) union 2 API
        versions, minus the April 2025 overlap between them = 12."""
        mock_mapping.return_value = {
            ("October", 2025): "9.0.0",
            ("April", 2025): "6.0.0",
        }

        versions = api.get_weo_versions()

        assert len(versions) == 12
        assert len(SDMX_RELEASES) == 13
        assert len(KNOWN_CORRUPT_RELEASES) == 2

    @patch("imf_reader.weo.api._fetch_version_mapping")
    def test_propagates_api_failure_instead_of_degrading(self, mock_mapping):
        """If the API mapping is unreachable, the whole call must fail rather than
        silently falling back to the SDMX-only list."""
        mock_mapping.side_effect = ConnectionError("api.imf.org unreachable")

        with pytest.raises(ConnectionError, match="api.imf.org unreachable"):
            api.get_weo_versions()


class TestGetWeoDataVersionResolution:
    """get_weo_data(version=None) must resolve 'latest' against the API mapping
    alone, never through the SDMX-inclusive union get_weo_versions() returns."""

    @patch("imf_reader.weo.api._get_weo_data_cached")
    @patch("imf_reader.weo.api._fetch_version_mapping")
    def test_none_resolves_within_api_mapping_only(
        self, mock_mapping, mock_cached_fetch
    ):
        # April 2025 is the only API version on offer. October 2024 and every
        # other SDMX-only release is newer-looking to nothing here, but if the
        # union ever leaked in, an SDMX release the API cannot serve could be
        # picked as "latest" instead.
        mock_mapping.return_value = {("April", 2025): "6.0.0"}
        mock_cached_fetch.return_value = "sentinel"

        api.get_weo_data(version=None)

        mock_cached_fetch.assert_called_once_with(("April", 2025))
