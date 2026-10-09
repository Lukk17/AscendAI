from unittest.mock import AsyncMock, patch

import pytest

from src.api.exceptions import HumanInterventionRequiredException, NoVNCFlowBusyException
from src.api.mcp.mcp_server import session_establish, web_read, web_search


@pytest.mark.asyncio
async def test_mcp_web_search_success_pins_today_body() -> None:
    # given
    mock_results = [{"title": "MCP", "url": "http://mcp.com"}]
    # when
    with patch(
        "src.api.mcp.mcp_server.search_client.search",
        new_callable=AsyncMock,
        return_value=mock_results,
    ):
        result = await web_search("query", 5)
    # then
    assert result == mock_results


@pytest.mark.asyncio
async def test_mcp_web_read_success_pins_today_body() -> None:
    # given
    mock_content = {"content": "MCP Content", "status": "success", "mode": "1-beautifulsoup"}
    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader.read",
            new_callable=AsyncMock,
            return_value=mock_content,
        ),
    ):
        result = await web_read("http://mcp.com")
    # then
    assert result == mock_content


@pytest.mark.asyncio
async def test_mcp_web_read_human_intervention_status_object_unchanged() -> None:
    # given
    exc = HumanInterventionRequiredException(vnc_url="http://vnc:7900", intervention_type="captcha")
    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader.read",
            new_callable=AsyncMock,
            side_effect=exc,
        ),
    ):
        result = await web_read("http://example.com")
    # then
    assert result["status"] == "human_intervention_required"
    assert result["intervention_type"] == "captcha"
    assert result["vnc_url"] == "http://vnc:7900"
    assert "message" in result


@pytest.mark.asyncio
async def test_mcp_web_read_novnc_busy_status_object_unchanged() -> None:
    # given
    exc = NoVNCFlowBusyException("http://in-flight.example", "default")
    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader.read",
            new_callable=AsyncMock,
            side_effect=exc,
        ),
    ):
        result = await web_read("http://example.com")
    # then
    assert result["status"] == "novnc_busy"
    assert result["holder_url"] == "http://in-flight.example"
    assert result["holder_profile"] == "default"
    assert "message" in result


@pytest.mark.asyncio
async def test_mcp_web_read_session_expired_status_object_unchanged() -> None:
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
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader.read",
            new_callable=AsyncMock,
            return_value=expired,
        ),
    ):
        result = await web_read("http://example.com/feed")
    # then
    assert result["status"] == "session_expired"
    assert result["profile"] == "work"
    assert "message" in result


@pytest.mark.asyncio
async def test_mcp_session_establish_success_pins_today_status_object() -> None:
    # given
    vnc_url = "http://vnc:7900"
    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch(
            "src.api.mcp.mcp_server.session_manager.establish",
            new_callable=AsyncMock,
            return_value=vnc_url,
        ),
    ):
        result = await session_establish("http://example.com/")
    # then
    assert result["status"] == "human_intervention_required"
    assert result["intervention_type"] == "login"
    assert result["vnc_url"] == vnc_url
