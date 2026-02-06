from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.search.search_client import SearxngClient


def test_search_success():
    mock_html = """
    <html>
        <body>
            <article class="result">
                <h3><a href="http://example.com">Example</a></h3>
                <p class="content">Description</p>
            </article>
        </body>
    </html>
    """

    with patch("httpx.Client.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = mock_html
        mock_get.return_value = mock_response

        client = SearxngClient()
        results = client.search("query")

        assert len(results) == 1
        assert results[0]["title"] == "Example"
        assert results[0]["url"] == "http://example.com"


def test_search_failure():
    with patch("httpx.Client.get") as mock_get:
        mock_get.side_effect = httpx.HTTPError("Network Error")

        client = SearxngClient()
        with pytest.raises(httpx.HTTPError):
            client.search("query")
