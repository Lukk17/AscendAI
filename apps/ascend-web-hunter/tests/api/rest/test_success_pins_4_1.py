from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.session.session_manager import SessionInfo, SessionManager


@pytest.mark.asyncio
async def test_search_success_pins_today_body(client: AsyncClient) -> None:
    # given
    mock_results = [{"title": "Unit", "url": "http://unit.com", "content": "desc"}]
    # when
    with patch(
        "src.api.rest.rest_endpoints.search_client.search",
        new_callable=AsyncMock,
        return_value=mock_results,
    ):
        response = await client.get("/api/v1/web/search", params={"query": "unit"})
    # then
    assert response.status_code == 200
    assert response.json() == mock_results


@pytest.mark.asyncio
async def test_read_success_pins_today_body(client: AsyncClient) -> None:
    # given
    mock_content = {"content": "Extracted unit", "status": "success", "mode": "test"}
    # when
    with (
        patch(
            "src.api.rest.rest_endpoints.web_reader.read",
            new_callable=AsyncMock,
            return_value=mock_content,
        ),
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
    ):
        response = await client.post("/api/v2/web/read", json={"url": "http://unit.com/"})
    # then
    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "Extracted unit"
    assert body["status"] == "success"


@pytest.mark.asyncio
async def test_read_session_expired_pins_today_shape(client: AsyncClient) -> None:
    # given
    expired = {
        "content": "",
        "status": "session_expired",
        "profile": "work",
        "message": "Stored session for example.com (profile=work) is no longer valid. "
        "Re-establish it with the session establish operation, then read again.",
    }
    # when
    with (
        patch(
            "src.api.rest.rest_endpoints.web_reader.read",
            new_callable=AsyncMock,
            return_value=expired,
        ),
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
    ):
        response = await client.post("/api/v2/web/read", json={"url": "http://example.com/feed"})
    # then
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "session_expired"
    assert body["profile"] == "work"
    assert "message" in body


@pytest.mark.asyncio
async def test_establish_session_success_pins_today_body(client: AsyncClient) -> None:
    # given
    vnc_url = "http://vnc:7900"
    # when
    with (
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
        patch.object(SessionManager, "establish", new=AsyncMock(return_value=vnc_url)),
    ):
        response = await client.post(
            "/api/v2/web/session/establish",
            json={"url": "http://example.com/"},
        )
    # then
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "login_required"
    assert body["vnc_url"] == vnc_url


@pytest.mark.asyncio
async def test_session_status_and_clear_pin_today_bodies(client: AsyncClient) -> None:
    # given
    info = SessionInfo(
        status="active", auth_ttl_remaining=3600.0, last_validated=1_000_000.0, profile="default"
    )
    # when
    with (
        patch.object(SessionManager, "status", new=AsyncMock(return_value=info)),
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
        patch.object(SessionManager, "clear", new=AsyncMock(return_value=True)),
        patch(
            "src.api.rest.rest_endpoints.web_reader.clear_cache_for_domain",
            return_value=2,
        ),
    ):
        status_response = await client.post(
            "/api/v2/web/session/status",
            json={"url": "http://example.com/"},
        )
        clear_response = await client.post(
            "/api/v2/web/session/clear",
            json={"url": "http://example.com/"},
        )
    # then
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "active"
    assert clear_response.status_code == 200
    clear_body = clear_response.json()
    assert clear_body["status"] == "cleared"
    assert clear_body["existed"] is True
