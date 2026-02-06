from unittest.mock import patch, AsyncMock

import pytest

from src.api.mcp.mcp_server import web_search, web_read


# Since we mocked FastMCP in conftest.py, the decorators @mcp.tool()
# just return the function itself (identity), so we can test them directly!

def test_mcp_web_search_tool():
    # given
    mock_results = [{"title": "MCP", "url": "url"}]

    # when
    with patch("src.api.mcp.mcp_server.search_client.search", return_value=mock_results):
        result = web_search("query", 5)

        # then
        assert result == mock_results


@pytest.mark.asyncio
async def test_mcp_web_read_tool():
    # given
    mock_content = "MCP Content"

    # when
    with patch("src.api.mcp.mcp_server.web_reader.read", new_callable=AsyncMock) as mock_read:
        mock_read.return_value = mock_content
        result = await web_read("http://mcp.com")

        # then
        assert result == "MCP Content"
