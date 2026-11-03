"""The removed `3-flaresolverr` value is refused like any value outside the allowed set.

Change remove-flaresolverr-tier, task 2.1 (owner answer 93 of 2026-10-08, design D1):
no tier runs, REST answers HTTP 400 with the problem body code `validation` and MCP
refuses the invalid argument.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError
from httpx import AsyncClient

from src.api.mcp.mcp_server import web_read

_URL = "http://unit.com/"
_REST_GUARD = "src.api.rest.rest_endpoints.check_fetch_uri"
_REST_READ = "src.api.rest.rest_endpoints.web_reader.read"
_MCP_GUARD = "src.api.mcp.mcp_server.check_fetch_uri"
_EXECUTE = "src.reader.web_reader.WebReader._execute_strategy"


@pytest.mark.asyncio
async def test_rest_removed_flaresolverr_answers_400_validation_and_runs_no_tier(
    client: AsyncClient,
) -> None:
    # when
    with (
        patch(_REST_GUARD, return_value=True),
        patch(_REST_READ, new_callable=AsyncMock) as mock_read,
        patch(_EXECUTE, new=AsyncMock()) as mock_execute,
    ):
        resp = await client.post("/api/v2/web/read", json={"url": _URL, "tier": "3-flaresolverr"})

    # then
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "validation"
    assert isinstance(body["errors"], list)
    assert len(body["errors"]) > 0
    mock_read.assert_not_awaited()
    mock_execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_mcp_removed_flaresolverr_answers_validation_and_runs_no_tier() -> None:
    # when
    with (
        patch(_MCP_GUARD, return_value=True),
        patch(_EXECUTE, new=AsyncMock()) as mock_execute,
    ):
        with pytest.raises(ToolError) as exc_info:
            await web_read(_URL, tier="3-flaresolverr")  # type: ignore[arg-type]

    # then
    assert str(exc_info.value).startswith("validation: ")
    mock_execute.assert_not_awaited()
