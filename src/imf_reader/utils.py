"""Utility functions"""

import requests


def make_request(url: str) -> requests.models.Response:
    """Make a request to a url.

    Args:
        url: url to make request to

    Returns:
        requests.models.Response: response object
    """

    try:
        response = requests.get(url)
        if response.status_code != 200:
            raise ConnectionError(
                f"Could not connect to {url}. Status code: {response.status_code}"
            )

        return response

    except requests.exceptions.RequestException as e:
        raise ConnectionError(f"Could not connect to {url}. Error: {str(e)}")
