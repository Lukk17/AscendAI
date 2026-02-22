from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

# Dependencies are now in the endpoints module
from src.api.rest.rest_endpoints import search_client, web_reader


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_search_endpoint(client: AsyncClient):
    mock_results = [{"title": "Res", "url": "u", "content": "c"}]

    with patch.object(search_client, "search", return_value=mock_results):
        # User changed to GET /api/v1/web/search
        resp = await client.get("/api/v1/web/search", params={"query": "test", "limit": 1})
        assert resp.status_code == 200
        # User changed return type to simple list
        assert resp.json()[0]["title"] == "Res"


@pytest.mark.asyncio
async def test_read_endpoint(client: AsyncClient):
    mock_res = {"status": "success", "content": "Read Content"}

    with patch.object(web_reader, "read", new_callable=AsyncMock) as mock_read:
        mock_read.return_value = mock_res
        # User changed to GET /api/v1/web/read
        resp = await client.get("/api/v1/web/read", params={"url": "http://test.com"})

        assert resp.status_code == 200
        assert resp.json()["content"] == mock_res["content"]
        assert resp.json()["url"] == "http://test.com"
