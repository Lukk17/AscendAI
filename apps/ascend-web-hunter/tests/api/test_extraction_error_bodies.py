"""Task 5.4: the four D8 codes as problem bodies on REST and tool errors on MCP."""

import re
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.api.exceptions import ExtractionFailedError
from src.api.mcp.mcp_server import web_read

_TRACE_RE = re.compile(r"[0-9a-f]{32}")

_URL = "http://unit.com/"
_GUARD = "src.api.rest.rest_endpoints.check_fetch_uri"
_MCP_GUARD = "src.api.mcp.mcp_server.check_fetch_uri"

_ARTICLE_HTML = (
    "<html><head><title>Article</title></head>"
    "<body><article><p>"
    "This is a genuine paragraph of article content with more than ten words in it. "
    "It continues with a second sentence so the extractor has plenty of real prose to work with."
    "</p></article></body></html>"
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
}


class _StubStrategy:
    def __init__(self, html: str = _ARTICLE_HTML) -> None:
        self._html = html

    async def get_html(self, _url: str) -> str:
        return self._html


def _check_shape(body: dict[str, Any], code: str, status: int) -> None:
    assert body["code"] == code
    assert body["type"] == f"https://ascend.ai/errors/{code.replace('_', '-')}"
    assert body["status"] == status
    assert body["instance"] == "/api/v2/web/read"
    assert _TRACE_RE.fullmatch(body["traceId"]) is not None
    assert body["detail"]


@pytest.mark.asyncio
async def test_rest_schema_without_endpoint_is_400(client: AsyncClient) -> None:
    # when
    with (
        patch(_GUARD, return_value=True),
        patch(
            "src.api.rest.rest_endpoints.web_reader._select_strategies",
            new=AsyncMock(return_value={"1-beautifulsoup": _StubStrategy()}),
        ),
        patch("src.reader.web_reader.recipe_lookup", new=AsyncMock(return_value=None)),
        patch("src.reader.web_reader.settings.EXTRACTION_LLM_BASE_URL", ""),
    ):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": _URL, "output_format": "schema", "extraction_schema": _SCHEMA},
        )

    # then
    assert resp.status_code == 400
    assert "application/problem+json" in resp.headers["content-type"]
    body = resp.json()
    _check_shape(body, "extraction_not_configured", 400)
    assert "EXTRACTION_LLM_BASE_URL" in body["detail"]


@pytest.mark.asyncio
async def test_rest_schema_model_failure_is_502(client: AsyncClient) -> None:
    # when
    with (
        patch(_GUARD, return_value=True),
        patch(
            "src.api.rest.rest_endpoints.web_reader._select_strategies",
            new=AsyncMock(return_value={"1-beautifulsoup": _StubStrategy()}),
        ),
        patch("src.reader.web_reader.recipe_lookup", new=AsyncMock(return_value=None)),
        patch(
            "src.reader.web_reader.run_schema_model",
            new=AsyncMock(side_effect=ExtractionFailedError("the model answer was not JSON")),
        ),
    ):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": _URL, "output_format": "schema", "extraction_schema": _SCHEMA},
        )

    # then
    assert resp.status_code == 502
    assert "application/problem+json" in resp.headers["content-type"]
    body = resp.json()
    _check_shape(body, "extraction_failed", 502)


@pytest.mark.asyncio
async def test_rest_screenshot_without_screenshot_tier_is_400(client: AsyncClient) -> None:
    # when
    with patch(_GUARD, return_value=True):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": _URL, "output_format": "screenshot", "tier": "6-novnc"},
        )

    # then
    assert resp.status_code == 400
    assert "application/problem+json" in resp.headers["content-type"]
    body = resp.json()
    _check_shape(body, "screenshot_unavailable", 400)


@pytest.mark.asyncio
async def test_rest_tables_with_links_is_400_bad_request(client: AsyncClient) -> None:
    # when
    with patch(_GUARD, return_value=True):
        resp = await client.post(
            "/api/v2/web/read", json={"url": _URL, "include_links": True, "output_format": "tables"}
        )

    # then
    assert resp.status_code == 400
    assert "application/problem+json" in resp.headers["content-type"]
    body = resp.json()
    _check_shape(body, "bad_request", 400)
    assert "include_links" in body["detail"]


@pytest.mark.asyncio
async def test_rest_screenshot_with_links_is_400_bad_request(client: AsyncClient) -> None:
    # when
    with patch(_GUARD, return_value=True):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": _URL, "include_links": True, "output_format": "screenshot"},
        )

    # then
    assert resp.status_code == 400
    body = resp.json()
    _check_shape(body, "bad_request", 400)


@pytest.mark.asyncio
async def test_rest_schema_without_schema_is_400_validation(client: AsyncClient) -> None:
    # when
    with patch(_GUARD, return_value=True):
        resp = await client.post("/api/v2/web/read", json={"url": _URL, "output_format": "schema"})

    # then
    assert resp.status_code == 400
    assert "application/problem+json" in resp.headers["content-type"]
    body = resp.json()
    assert body["code"] == "validation"
    assert _TRACE_RE.fullmatch(body["traceId"]) is not None


@pytest.mark.asyncio
async def test_mcp_schema_without_endpoint_is_tool_error() -> None:
    # when
    with (
        patch(_MCP_GUARD, return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader._select_strategies",
            new=AsyncMock(return_value={"1-beautifulsoup": _StubStrategy()}),
        ),
        patch("src.reader.web_reader.recipe_lookup", new=AsyncMock(return_value=None)),
        patch("src.reader.web_reader.settings.EXTRACTION_LLM_BASE_URL", ""),
        pytest.raises(Exception, match=r"^extraction_not_configured: ") as exc_info,
    ):
        await web_read(_URL, output_format="schema", extraction_schema=_SCHEMA)

    # then
    assert str(exc_info.value).startswith("extraction_not_configured: ")


@pytest.mark.asyncio
async def test_mcp_schema_model_failure_is_tool_error() -> None:
    # when
    with (
        patch(_MCP_GUARD, return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader._select_strategies",
            new=AsyncMock(return_value={"1-beautifulsoup": _StubStrategy()}),
        ),
        patch("src.reader.web_reader.recipe_lookup", new=AsyncMock(return_value=None)),
        patch(
            "src.reader.web_reader.run_schema_model",
            new=AsyncMock(side_effect=ExtractionFailedError("the model answer was not JSON")),
        ),
        pytest.raises(Exception, match=r"^extraction_failed: ") as exc_info,
    ):
        await web_read(_URL, output_format="schema", extraction_schema=_SCHEMA)

    # then
    assert str(exc_info.value).startswith("extraction_failed: ")


@pytest.mark.asyncio
async def test_mcp_tables_with_links_is_bad_request_tool_error() -> None:
    # when
    with (
        patch(_MCP_GUARD, return_value=True),
        pytest.raises(Exception, match=r"^bad_request: ") as exc_info,
    ):
        await web_read(_URL, include_links=True, output_format="tables")

    # then
    assert str(exc_info.value).startswith("bad_request: ")


@pytest.mark.asyncio
async def test_mcp_schema_without_schema_is_validation_tool_error() -> None:
    # when
    with (
        patch(_MCP_GUARD, return_value=True),
        pytest.raises(Exception, match=r"^validation: ") as exc_info,
    ):
        await web_read(_URL, output_format="schema")

    # then
    assert str(exc_info.value).startswith("validation: ")
