from unittest.mock import patch, AsyncMock

import pytest

from src.api.mcp.mcp_server import web_search, web_read


def test_mcp_web_search_tool():
    mock_results = [{"title": "MCP", "url": "url"}]

    with patch("src.api.mcp.mcp_server.search_client.search", return_value=mock_results):
        result = web_search("query", 5)

        assert result == mock_results


@pytest.mark.asyncio
async def test_mcp_web_read_tool():
    mock_content = "MCP Content"

    with patch("src.api.mcp.mcp_server.web_reader.read", new_callable=AsyncMock) as mock_read:
        mock_read.return_value = mock_content
        result = await web_read("http://mcp.com")

        assert result == "MCP Content"


@pytest.mark.asyncio
async def test_mcp_web_read_tool_with_links():
    mock_result = {
        "content": "Job title [1]",
        "links": {1: "https://example.com/job1"},
        "status": "success"
    }

    with patch("src.api.mcp.mcp_server.web_reader.read_with_links", new_callable=AsyncMock) as mock_read:
        mock_read.return_value = mock_result
        result = await web_read("http://mcp.com", include_links=True)

        assert result["status"] == "success"
        assert "links" in result
        assert result["links"] == {1: "https://example.com/job1"}
        mock_read.assert_called_once_with("http://mcp.com", None, heavy_mode=False)


@pytest.mark.asyncio
async def test_mcp_web_read_tool_with_links_and_filter():
    mock_result = {
        "content": "Senior Dev [1]",
        "links": {1: "https://example.com/job-offer/senior-dev"},
        "status": "success"
    }

    with patch("src.api.mcp.mcp_server.web_reader.read_with_links", new_callable=AsyncMock) as mock_read:
        mock_read.return_value = mock_result
        result = await web_read("http://mcp.com", include_links=True, link_filter="/job-offer/")

        assert len(result["links"]) == 1
        mock_read.assert_called_once_with("http://mcp.com", "/job-offer/", heavy_mode=False)
