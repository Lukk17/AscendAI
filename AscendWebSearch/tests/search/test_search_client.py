from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.search.search_client import SearxngClient


def _build_html_with_articles(count: int = 1) -> str:
    articles = "".join(
        f"""
        <article class="result">
            <h3><a href="http://example.com/{i}">Title {i}</a></h3>
            <p class="content">Body {i}</p>
        </article>
        """
        for i in range(count)
    )

    return f"<html><body>{articles}</body></html>"


@pytest.mark.asyncio
async def test_search_returns_results_for_async_client():
    html = _build_html_with_articles(1)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html
    mock_response.raise_for_status = MagicMock()

    client = SearxngClient()
    with patch.object(client.client, "get", new=AsyncMock(return_value=mock_response)):
        results = await client.search("query")

    assert len(results) == 1
    assert results[0]["title"] == "Title 0"
    assert results[0]["url"] == "http://example.com/0"
    assert results[0]["content"] == "Body 0"

    await client.aclose()


@pytest.mark.asyncio
async def test_search_limits_results():
    html = _build_html_with_articles(5)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html
    mock_response.raise_for_status = MagicMock()

    client = SearxngClient()
    with patch.object(client.client, "get", new=AsyncMock(return_value=mock_response)):
        results = await client.search("query", limit=2)

    assert len(results) == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_search_skips_article_without_title():
    html = """
    <html><body>
        <article class="result">
            <p class="content">No anchor</p>
        </article>
        <article class="result">
            <h3><a href="http://example.com">Good</a></h3>
        </article>
    </body></html>
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html
    mock_response.raise_for_status = MagicMock()

    client = SearxngClient()
    with patch.object(client.client, "get", new=AsyncMock(return_value=mock_response)):
        results = await client.search("query")

    assert len(results) == 1
    assert results[0]["title"] == "Good"
    assert results[0]["content"] == ""

    await client.aclose()


@pytest.mark.asyncio
async def test_search_with_categories_forwards_param():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html></html>"
    mock_response.raise_for_status = MagicMock()

    client = SearxngClient()
    mock_get = AsyncMock(return_value=mock_response)
    with patch.object(client.client, "get", new=mock_get):
        await client.search("q", categories="news")

    assert mock_get.call_args.kwargs["params"]["categories"] == "news"
    await client.aclose()


@pytest.mark.asyncio
async def test_search_raises_on_http_status_error():
    request = httpx.Request("GET", "http://searxng/search")
    response = httpx.Response(500, request=request)
    mock_get = AsyncMock(side_effect=httpx.HTTPStatusError("boom", request=request, response=response))

    client = SearxngClient()
    with patch.object(client.client, "get", new=mock_get):
        with pytest.raises(httpx.HTTPStatusError):
            await client.search("q")

    await client.aclose()


@pytest.mark.asyncio
async def test_search_raises_on_timeout():
    mock_get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

    client = SearxngClient()
    with patch.object(client.client, "get", new=mock_get):
        with pytest.raises(httpx.TimeoutException):
            await client.search("q")

    await client.aclose()


@pytest.mark.asyncio
async def test_search_raises_on_transport_error():
    mock_get = AsyncMock(side_effect=httpx.ConnectError("nope"))

    client = SearxngClient()
    with patch.object(client.client, "get", new=mock_get):
        with pytest.raises(httpx.ConnectError):
            await client.search("q")

    await client.aclose()
