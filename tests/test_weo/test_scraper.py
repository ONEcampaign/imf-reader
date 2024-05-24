"""Tests for weo scraper module."""

import pytest
from unittest.mock import patch
import requests

from imf_reader.weo import scraper


TEST_URL = "https://test.com"


def test_make_request():
    """Test that make_request returns a response object."""

    # test successful request
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        response = scraper.make_request(TEST_URL)
        assert response == mock_get.return_value

    # test failed request
    with patch("requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.RequestException
        with pytest.raises(ConnectionError, match="Could not connect to"):
            scraper.make_request(TEST_URL)


