"""Tests for the utils module"""

import pytest
from unittest.mock import patch
import requests

from imf_reader import utils


TEST_URL = "https://test.com"


def test_make_request():
    """Test make_request"""

    # test successful request
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        response = utils.make_request(TEST_URL)
        assert response == mock_get.return_value

    # test failed request
    with patch("requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.RequestException
        with pytest.raises(ConnectionError, match="Could not connect to"):
            utils.make_request(TEST_URL)

    # test when status code is not 200
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 404
        with pytest.raises(ConnectionError, match="Could not connect to"):
            utils.make_request(TEST_URL)