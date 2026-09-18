"""The MCP web_read tool exposes output_format, tier, and the session_expired outcome.

Change close-web-search-scraping-follow-ups, tasks 2.3, 3.5 and 3.6.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.api.mcp.mcp_server import web_read

_URL = "http://mcp.com"
_READ = "src.api.mcp.mcp_server.web_reader.read"
_READ_WITH_LINKS = "src.api.mcp.mcp_server.web_reader.read_with_links"
_GUARD = "src.api.mcp.mcp_server.is_safe_external_url"

_STRUCTURED_FIELDS = ["content", "title", "author", "date", "sitename", "status", "mode"]
_SESSION_EXPIRED_FIELDS = ["content", "status", "profile", "message"]


@pytest.mark.asyncio
async def test_web_read_forwards_output_format_and_tier():
    result = {"content": "X", "status": "success", "mode": "3-flaresolverr"}
    with (
        patch(_GUARD, return_value=True),
        patch(_READ, new_callable=AsyncMock, return_value=result) as mock_read,
    ):
        await web_read(_URL, output_format="structured", tier="3-flaresolverr")

    mock_read.assert_awaited_once_with(
        _URL, heavy_mode=False, profile=None, output_format="structured", tier="3-flaresolverr"
    )


@pytest.mark.asyncio
async def test_web_read_returns_the_structured_contract():
    result = {
        "content": "The body",
        "title": "A title",
        "author": "An author",
        "date": "2026-09-18",
        "sitename": "MCP",
        "source": "trafilatura",
        "status": "success",
        "mode": "1-beautifulsoup",
    }
    with (
        patch(_GUARD, return_value=True),
        patch(_READ, new_callable=AsyncMock, return_value=result),
    ):
        payload = await web_read(_URL, output_format="structured")

    for field in _STRUCTURED_FIELDS:
        assert field in payload


@pytest.mark.asyncio
async def test_web_read_forwards_the_tier_on_the_links_path():
    result = {"content": "X", "links": {}, "status": "success", "mode": "5-crawlee_adaptive"}
    with (
        patch(_GUARD, return_value=True),
        patch(_READ_WITH_LINKS, new_callable=AsyncMock, return_value=result) as mock_read,
    ):
        await web_read(_URL, include_links=True, tier="5-crawlee_adaptive")

    mock_read.assert_awaited_once_with(
        _URL, None, heavy_mode=False, profile=None, output_format="text", tier="5-crawlee_adaptive"
    )


@pytest.mark.asyncio
async def test_structured_with_links_is_rejected():
    with (
        patch(_GUARD, return_value=True),
        patch(_READ_WITH_LINKS, new_callable=AsyncMock) as mock_read,
    ):
        with pytest.raises(ValueError, match="include_links"):
            await web_read(_URL, include_links=True, output_format="structured")

    mock_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_expired_reaches_the_agent_whole():
    result = {
        "content": "",
        "status": "session_expired",
        "profile": "work",
        "message": "Stored session for mcp.com (profile=work) is no longer valid. Re-establish it.",
    }
    with (
        patch(_GUARD, return_value=True),
        patch(_READ, new_callable=AsyncMock, return_value=result),
    ):
        payload = await web_read(_URL, profile="work")

    for field in _SESSION_EXPIRED_FIELDS:
        assert field in payload
    assert payload["status"] == "session_expired"
