"""REST and MCP accept the patched browser tiers and start the chain at them.

Change enhance-web-search-tier-ladder, task 2.4.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.api.mcp.mcp_server import web_read

_URL = "http://unit.com/"
_REST_READ = "src.api.rest.rest_endpoints.web_reader.read"
_REST_GUARD = "src.api.rest.rest_endpoints.check_fetch_uri"
_MCP_READ = "src.api.mcp.mcp_server.web_reader.read"
_MCP_GUARD = "src.api.mcp.mcp_server.check_fetch_uri"


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["4a-patchright", "4b-camoufox"])
async def test_rest_read_starts_the_chain_at_the_patched_tier(
    client: AsyncClient, tier: str
) -> None:
    # given
    result = {"content": "X", "status": "success", "mode": tier}

    # when
    with (
        patch(_REST_READ, new_callable=AsyncMock, return_value=result) as mock_read,
        patch(_REST_GUARD, return_value=True),
    ):
        resp = await client.post("/api/v2/web/read", json={"url": _URL, "tier": tier})

    # then
    assert resp.status_code == 200
    mock_read.assert_awaited_once_with(
        _URL, heavy_mode=False, profile=None, output_format="text", tier=tier, extraction_schema=None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["4a-patchright", "4b-camoufox"])
async def test_mcp_web_read_starts_the_chain_at_the_patched_tier(tier: str) -> None:
    # given
    result = {"content": "X", "status": "success", "mode": tier}

    # when
    with (
        patch(_MCP_GUARD, return_value=True),
        patch(_MCP_READ, new_callable=AsyncMock, return_value=result) as mock_read,
    ):
        payload = await web_read(_URL, tier=tier)  # type: ignore[arg-type]

    # then
    assert payload["mode"] == tier
    mock_read.assert_awaited_once_with(
        _URL, heavy_mode=False, profile=None, output_format="text", tier=tier, extraction_schema=None
    )
