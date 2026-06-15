from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.session.session_manager import SessionInfo, SessionManager


@pytest.mark.asyncio
async def test_search_get_success(client: AsyncClient):
    mock_results = [{"title": "Unit", "url": "http://unit.com", "content": "desc"}]
    with patch(
        "src.api.rest.rest_endpoints.search_client.search",
        new_callable=AsyncMock,
        return_value=mock_results,
    ):
        resp = await client.get("/api/v1/web/search", params={"query": "unit"})
    assert resp.status_code == 200
    assert resp.json()[0]["title"] == "Unit"


@pytest.mark.asyncio
async def test_search_get_empty_query_returns_400(client: AsyncClient):
    resp = await client.get("/api/v1/web/search", params={"query": ""})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_search_get_whitespace_query_returns_400(client: AsyncClient):
    resp = await client.get("/api/v1/web/search", params={"query": "   "})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_search_get_too_long_returns_400(client: AsyncClient):
    resp = await client.get("/api/v1/web/search", params={"query": "x" * 501})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_read_post_success(client: AsyncClient):
    mock_content = {"content": "Extracted unit", "status": "success", "mode": "test"}
    with (
        patch(
            "src.api.rest.rest_endpoints.web_reader.read",
            new_callable=AsyncMock,
            return_value=mock_content,
        ),
        patch("src.api.rest.rest_endpoints.is_safe_external_url", return_value=True),
    ):
        resp = await client.post("/api/v2/web/read", json={"url": "http://unit.com/"})
    assert resp.status_code == 200
    assert resp.json()["content"] == "Extracted unit"


@pytest.mark.asyncio
async def test_read_post_unsafe_url_returns_400(client: AsyncClient):
    with patch("src.api.rest.rest_endpoints.is_safe_external_url", return_value=False):
        resp = await client.post("/api/v2/web/read", json={"url": "http://127.0.0.1/"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_read_post_missing_url_returns_422(client: AsyncClient):
    resp = await client.post("/api/v2/web/read", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_read_post_with_include_links(client: AsyncClient):
    mock_res = {
        "content": "X",
        "links": {1: "http://unit.com/a"},
        "status": "success",
        "mode": "test",
    }
    with (
        patch(
            "src.api.rest.rest_endpoints.web_reader.read_with_links",
            new_callable=AsyncMock,
            return_value=mock_res,
        ) as mock_read,
        patch("src.api.rest.rest_endpoints.is_safe_external_url", return_value=True),
    ):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": "http://unit.com/", "include_links": True, "link_filter": "/a"},
        )
    assert resp.status_code == 200
    mock_read.assert_awaited_once_with("http://unit.com/", "/a", heavy_mode=False, profile=None)


@pytest.mark.asyncio
async def test_read_post_heavy_mode_forwarded(client: AsyncClient):
    mock_res = {"content": "X", "status": "success", "mode": "test"}
    with (
        patch(
            "src.api.rest.rest_endpoints.web_reader.read",
            new_callable=AsyncMock,
            return_value=mock_res,
        ) as mock_read,
        patch("src.api.rest.rest_endpoints.is_safe_external_url", return_value=True),
    ):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": "http://unit.com/", "heavy_mode": True},
        )
    assert resp.status_code == 200
    mock_read.assert_awaited_once_with("http://unit.com/", heavy_mode=True, profile=None)


# ---------------------------------------------------------------------------
# POST /api/v2/web/session/establish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_establish_session_returns_vnc_url(client: AsyncClient):
    with (
        patch("src.api.rest.rest_endpoints.is_safe_external_url", return_value=True),
        patch.object(
            SessionManager,
            "establish",
            new=AsyncMock(return_value="http://vnc:7900"),
        ),
    ):
        resp = await client.post(
            "/api/v2/web/session/establish",
            json={"url": "http://example.com/"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "login_required"
    assert body["vnc_url"] == "http://vnc:7900"
    assert "example.com" in body["target"]


@pytest.mark.asyncio
async def test_establish_session_unsafe_url_returns_400(client: AsyncClient):
    with patch("src.api.rest.rest_endpoints.is_safe_external_url", return_value=False):
        resp = await client.post(
            "/api/v2/web/session/establish",
            json={"url": "http://192.168.1.1/"},
        )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/v2/web/session/status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_status_returns_info(client: AsyncClient):
    info = SessionInfo(status="active", auth_ttl_remaining=3600.0, last_validated=1_000_000.0, profile="default")
    with patch.object(SessionManager, "status", new=AsyncMock(return_value=info)):
        resp = await client.post(
            "/api/v2/web/session/status",
            json={"url": "http://example.com/"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["auth_ttl_remaining_seconds"] == 3600.0
