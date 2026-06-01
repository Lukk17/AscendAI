from unittest.mock import AsyncMock, patch

import pytest

from src.api.exceptions import HumanInterventionRequiredException
from src.api.mcp.mcp_server import web_read, web_search


@pytest.mark.asyncio
async def test_mcp_web_search_returns_results():
    mock_results = [{"title": "MCP", "url": "url"}]
    with patch(
        "src.api.mcp.mcp_server.search_client.search",
        new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = mock_results
        result = await web_search("query", 5)
    assert result == mock_results


@pytest.mark.asyncio
async def test_mcp_web_search_empty_query_raises():
    with pytest.raises(ValueError, match="empty"):
        await web_search("")


@pytest.mark.asyncio
async def test_mcp_web_search_whitespace_only_raises():
    with pytest.raises(ValueError, match="empty"):
        await web_search("   ")


@pytest.mark.asyncio
async def test_mcp_web_search_too_long_raises():
    with pytest.raises(ValueError, match="maximum length"):
        await web_search("x" * 501)


@pytest.mark.asyncio
async def test_mcp_web_read_unsafe_url_raises():
    with patch("src.api.mcp.mcp_server.is_safe_external_url", return_value=False):
        with pytest.raises(ValueError, match="non-routable"):
            await web_read("http://127.0.0.1")


@pytest.mark.asyncio
async def test_mcp_web_read_calls_read_when_include_links_false():
    mock_content = {"content": "MCP Content", "status": "success", "mode": "1-beautifulsoup"}
    with (
        patch("src.api.mcp.mcp_server.is_safe_external_url", return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader.read",
            new_callable=AsyncMock,
            return_value=mock_content,
        ) as mock_read,
    ):
        result = await web_read("http://mcp.com")

    assert result == mock_content
    mock_read.assert_awaited_once_with("http://mcp.com", heavy_mode=False)


@pytest.mark.asyncio
async def test_mcp_web_read_calls_read_with_links_when_include_links_true():
    mock_result = {
        "content": "Job title [1]",
        "links": {1: "https://example.com/job1"},
        "status": "success",
    }
    with (
        patch("src.api.mcp.mcp_server.is_safe_external_url", return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader.read_with_links",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_read,
    ):
        result = await web_read("http://mcp.com", include_links=True, link_filter="/job/")

    assert result["status"] == "success"
    mock_read.assert_awaited_once_with("http://mcp.com", "/job/", heavy_mode=False)


@pytest.mark.asyncio
async def test_mcp_web_read_catches_human_intervention_and_returns_structured_payload():
    exc = HumanInterventionRequiredException(vnc_url="http://vnc/x", intervention_type="captcha")
    with (
        patch("src.api.mcp.mcp_server.is_safe_external_url", return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader.read",
            new_callable=AsyncMock,
            side_effect=exc,
        ),
    ):
        result = await web_read("http://mcp.com")

    assert result["status"] == "human_intervention_required"
    assert result["intervention_type"] == "captcha"
    assert result["vnc_url"] == "http://vnc/x"
    assert "vnc/x" in result["message"]


@pytest.mark.asyncio
async def test_mcp_web_read_human_intervention_on_links_branch():
    exc = HumanInterventionRequiredException(vnc_url="http://vnc/y", intervention_type="login")
    with (
        patch("src.api.mcp.mcp_server.is_safe_external_url", return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader.read_with_links",
            new_callable=AsyncMock,
            side_effect=exc,
        ),
    ):
        result = await web_read("http://mcp.com", include_links=True)

    assert result["intervention_type"] == "login"
