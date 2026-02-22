from unittest.mock import patch, AsyncMock

import pytest
from httpx import AsyncClient


# We need a minimal app to test the router in isolation or use the client fixture
# The client fixture in conftest.py uses the main app which provides full context.
# Unit tests ideally rely on the router, but integration with client is safer for routes.

@pytest.mark.asyncio
async def test_search_get_success(client: AsyncClient):
    # given
    mock_results = [{"title": "Unit", "url": "http://unit.com", "content": "desc"}]

    # when
    with patch("src.api.rest.rest_endpoints.search_client.search", return_value=mock_results):
        resp = await client.get("/api/v1/web/search", params={"query": "unit"})

        # then
        assert resp.status_code == 200
        assert resp.json()[0]["title"] == "Unit"


@pytest.mark.asyncio
async def test_search_get_empty(client: AsyncClient):
    # given
    # when
    with patch("src.api.rest.rest_endpoints.search_client.search", return_value=[]):
        resp = await client.get("/api/v1/web/search", params={"query": "empty"})

        # then
        assert resp.status_code == 200
        assert resp.json() == []


@pytest.mark.asyncio
async def test_read_get_success(client: AsyncClient):
    # given
    mock_content = {"content": "Extracted unit", "status": "success", "method": "test"}

    # when
    with patch("src.api.rest.rest_endpoints.web_reader.read", new_callable=AsyncMock) as mock_read:
        mock_read.return_value = mock_content
        resp = await client.get("/api/v1/web/read", params={"url": "http://unit.com"})

        # then
        assert resp.status_code == 200
        assert resp.json()["content"] == "Extracted unit"


@pytest.mark.asyncio
async def test_read_get_missing_url(client: AsyncClient):
    # given
    # when
    resp = await client.get("/api/v1/web/read", params={})  # No url

    # then
    assert resp.status_code == 422  # FastAPI validation error for required param
