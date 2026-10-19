"""The FlareSolverr tier runs only while FLARESOLVERR_ENABLED is true (task 3.1)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError
from httpx import AsyncClient

from src.api.mcp.mcp_server import web_read

_URL = "http://unit.com/"
_REST_GUARD = "src.api.rest.rest_endpoints.check_fetch_uri"
_MCP_GUARD = "src.api.mcp.mcp_server.check_fetch_uri"
_EXECUTE = "src.reader.web_reader.WebReader._execute_strategy"


@pytest.mark.asyncio
async def test_rest_disabled_flaresolverr_answers_409_and_runs_no_tier(client: AsyncClient) -> None:
    # when
    with (
        patch(_REST_GUARD, return_value=True),
        patch("src.reader.web_reader.settings.FLARESOLVERR_ENABLED", False),
        patch(_EXECUTE, new=AsyncMock()) as mock_execute,
    ):
        resp = await client.post("/api/v2/web/read", json={"url": _URL, "tier": "3-flaresolverr"})

    # then
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "tier_disabled"
    assert "3-flaresolverr" in body["detail"]
    mock_execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_mcp_disabled_flaresolverr_answers_tier_disabled_and_runs_no_tier() -> None:
    # when
    with (
        patch(_MCP_GUARD, return_value=True),
        patch("src.reader.web_reader.settings.FLARESOLVERR_ENABLED", False),
        patch(_EXECUTE, new=AsyncMock()) as mock_execute,
    ):
        with pytest.raises(ToolError) as exc_info:
            await web_read(_URL, tier="3-flaresolverr")

    # then
    assert str(exc_info.value).startswith("tier_disabled: ")
    assert "3-flaresolverr" in str(exc_info.value)
    mock_execute.assert_not_awaited()


_ARTICLE_HTML = (
    "<html><head><title>Article</title></head>"
    "<body><article><p>"
    "This is a genuine paragraph of article content with more than ten words in it. "
    "It continues with a second sentence so the extractor has plenty of real prose to work with."
    "</p></article></body></html>"
)


@pytest.mark.asyncio
async def test_rest_enabled_flaresolverr_runs_at_flaresolverr(client: AsyncClient) -> None:
    # when
    with (
        patch(_REST_GUARD, return_value=True),
        patch("src.reader.web_reader.settings.FLARESOLVERR_ENABLED", True),
        patch(
            "src.reader.strategies.flaresolverr_strategy.FlareSolverrStrategy.get_html",
            new=AsyncMock(return_value=_ARTICLE_HTML),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        resp = await client.post("/api/v2/web/read", json={"url": _URL, "tier": "3-flaresolverr"})

    # then
    assert resp.status_code == 200
    assert resp.json()["mode"] == "3-flaresolverr"
