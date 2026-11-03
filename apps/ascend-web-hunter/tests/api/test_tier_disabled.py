"""A caller who selects a switched-off tier is refused with 409 tier_disabled (task 2.8)."""

import re
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError
from httpx import AsyncClient

from src.api.mcp.mcp_server import web_read

_URL = "http://unit.com/"
_REST_GUARD = "src.api.rest.rest_endpoints.check_fetch_uri"
_MCP_GUARD = "src.api.mcp.mcp_server.check_fetch_uri"
_EXECUTE = "src.reader.web_reader.WebReader._execute_strategy"

_ARTICLE_HTML = (
    "<html><head><title>Article</title></head>"
    "<body><article><p>"
    "This is a genuine paragraph of article content with more than ten words in it. "
    "It continues with a second sentence so the extractor has plenty of real prose to work with."
    "</p></article></body></html>"
)


@pytest.mark.asyncio
async def test_rest_disabled_camoufox_answers_409_and_runs_no_tier(client: AsyncClient) -> None:
    # when
    with (
        patch(_REST_GUARD, return_value=True),
        patch("src.reader.web_reader.settings.CAMOUFOX_ENABLED", False),
        patch(_EXECUTE, new=AsyncMock()) as mock_execute,
    ):
        resp = await client.post("/api/v2/web/read", json={"url": _URL, "tier": "4b-camoufox"})

    # then
    assert resp.status_code == 409
    assert "application/problem+json" in resp.headers["content-type"]
    body = resp.json()
    assert body["code"] == "tier_disabled"
    assert body["type"] == "https://ascend.ai/errors/tier-disabled"
    assert body["instance"] == "/api/v2/web/read"
    assert re.fullmatch(r"[0-9a-f]{32}", body["traceId"]) is not None
    assert "4b-camoufox" in body["detail"]
    mock_execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_mcp_disabled_camoufox_answers_tier_disabled_and_runs_no_tier() -> None:
    # when
    with (
        patch(_MCP_GUARD, return_value=True),
        patch("src.reader.web_reader.settings.CAMOUFOX_ENABLED", False),
        patch(_EXECUTE, new=AsyncMock()) as mock_execute,
    ):
        with pytest.raises(ToolError) as exc_info:
            await web_read(_URL, tier="4b-camoufox")

    # then
    assert str(exc_info.value).startswith("tier_disabled: ")
    assert "4b-camoufox" in str(exc_info.value)
    mock_execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_rest_enabled_camoufox_runs_at_camoufox(client: AsyncClient) -> None:
    # when
    with (
        patch(_REST_GUARD, return_value=True),
        patch("src.reader.web_reader.settings.CAMOUFOX_ENABLED", True),
        patch(
            "src.reader.strategies.camoufox_strategy.CamoufoxStrategy.get_html",
            new=AsyncMock(return_value=_ARTICLE_HTML),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        resp = await client.post("/api/v2/web/read", json={"url": _URL, "tier": "4b-camoufox"})

    # then
    assert resp.status_code == 200
    assert resp.json()["mode"] == "4b-camoufox"
