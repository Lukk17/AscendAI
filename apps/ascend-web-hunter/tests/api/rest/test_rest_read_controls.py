"""The REST read operation exposes output_format, tier, and the session_expired outcome.

Change close-web-search-scraping-follow-ups, tasks 2.3, 3.4 and 3.6.
"""

import re
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

_URL = "http://unit.com/"
_READ = "src.api.rest.rest_endpoints.web_reader.read"
_READ_WITH_LINKS = "src.api.rest.rest_endpoints.web_reader.read_with_links"
_GUARD = "src.api.rest.rest_endpoints.check_fetch_uri"

_STRUCTURED_FIELDS = ["url", "content", "title", "author", "date", "sitename", "status", "mode"]
_SESSION_EXPIRED_FIELDS = ["url", "content", "status", "profile", "message"]


@pytest.mark.asyncio
async def test_read_forwards_output_format_and_tier(client: AsyncClient) -> None:
    # given
    result = {"content": "X", "status": "success", "mode": "4-playwright_stealth"}

    # when
    with (
        patch(_READ, new_callable=AsyncMock, return_value=result) as mock_read,
        patch(_GUARD, return_value=True),
    ):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": _URL, "output_format": "structured", "tier": "4-playwright_stealth"},
        )

    # then
    assert resp.status_code == 200
    mock_read.assert_awaited_once_with(
        _URL,
        heavy_mode=False,
        profile=None,
        output_format="structured",
        tier="4-playwright_stealth",
        extraction_schema=None,
    )


@pytest.mark.asyncio
async def test_read_defaults_to_text_and_no_tier(client: AsyncClient) -> None:
    # given
    result = {"content": "X", "status": "success", "mode": "1-beautifulsoup"}

    # when
    with (
        patch(_READ, new_callable=AsyncMock, return_value=result) as mock_read,
        patch(_GUARD, return_value=True),
    ):
        resp = await client.post("/api/v2/web/read", json={"url": _URL})

    # then
    assert resp.status_code == 200
    mock_read.assert_awaited_once_with(
        _URL,
        heavy_mode=False,
        profile=None,
        output_format="text",
        tier=None,
        extraction_schema=None,
    )


@pytest.mark.asyncio
async def test_structured_read_returns_the_structured_contract(client: AsyncClient) -> None:
    # given
    result = {
        "content": "The body",
        "title": "A title",
        "author": "An author",
        "date": "2026-09-18",
        "sitename": "Unit",
        "source": "trafilatura",
        "status": "success",
        "mode": "1-beautifulsoup",
    }

    # when
    with (
        patch(_READ, new_callable=AsyncMock, return_value=result),
        patch(_GUARD, return_value=True),
    ):
        resp = await client.post("/api/v2/web/read", json={"url": _URL, "output_format": "structured"})

    # then
    body = resp.json()
    for field in _STRUCTURED_FIELDS:
        assert field in body


@pytest.mark.asyncio
async def test_read_forwards_the_tier_on_the_links_path(client: AsyncClient) -> None:
    # given
    result = {"content": "X", "links": {}, "status": "success", "mode": "4-playwright_stealth"}

    # when
    with (
        patch(_READ_WITH_LINKS, new_callable=AsyncMock, return_value=result) as mock_read,
        patch(_GUARD, return_value=True),
    ):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": _URL, "include_links": True, "tier": "4-playwright_stealth"},
        )

    # then
    assert resp.status_code == 200
    mock_read.assert_awaited_once_with(
        _URL, None, heavy_mode=False, profile=None, output_format="text", tier="4-playwright_stealth"
    )


@pytest.mark.asyncio
async def test_structured_with_links_is_rejected(client: AsyncClient) -> None:
    # when
    with (
        patch(_READ_WITH_LINKS, new_callable=AsyncMock) as mock_read,
        patch(_GUARD, return_value=True),
    ):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": _URL, "include_links": True, "output_format": "structured"},
        )

    # then
    assert resp.status_code == 400
    assert "application/problem+json" in resp.headers["content-type"]
    body = resp.json()
    assert body["code"] == "bad_request"
    assert body["type"] == "https://ascend.ai/errors/bad-request"
    assert body["instance"] == "/api/v2/web/read"
    assert re.fullmatch(r"[0-9a-f]{32}", body["traceId"]) is not None
    assert "include_links" in body["detail"]
    mock_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unknown_tier_is_rejected(client: AsyncClient) -> None:
    # given
    payload = {"url": _URL, "tier": "7-telepathy"}

    # when
    with patch(_GUARD, return_value=True):
        resp = await client.post("/api/v2/web/read", json=payload)

    # then
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "validation"
    assert isinstance(body["errors"], list)
    assert len(body["errors"]) > 0


@pytest.mark.asyncio
async def test_an_unknown_output_format_is_rejected(client: AsyncClient) -> None:
    # given
    payload = {"url": _URL, "output_format": "yaml"}

    # when
    with patch(_GUARD, return_value=True):
        resp = await client.post("/api/v2/web/read", json=payload)

    # then
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "validation"
    assert isinstance(body["errors"], list)
    assert len(body["errors"]) > 0


@pytest.mark.asyncio
async def test_session_expired_reaches_the_caller_whole(client: AsyncClient) -> None:
    # given
    result = {
        "content": "",
        "status": "session_expired",
        "profile": "work",
        "message": "Stored session for unit.com (profile=work) is no longer valid. Re-establish it.",
    }

    # when
    with (
        patch(_READ, new_callable=AsyncMock, return_value=result),
        patch(_GUARD, return_value=True),
    ):
        resp = await client.post("/api/v2/web/read", json={"url": _URL, "profile": "work"})

    # then
    assert resp.status_code == 200
    body = resp.json()
    for field in _SESSION_EXPIRED_FIELDS:
        assert field in body
    assert body["status"] == "session_expired"


@pytest.mark.asyncio
async def test_schema_format_forwards_extraction_schema(client: AsyncClient) -> None:
    # given
    result = {"content": {"name": "Red Widget"}, "status": "success", "mode": "1-beautifulsoup"}
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}

    # when
    with (
        patch(_READ, new_callable=AsyncMock, return_value=result) as mock_read,
        patch(_GUARD, return_value=True),
    ):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": _URL, "output_format": "schema", "extraction_schema": schema},
        )

    # then
    assert resp.status_code == 200
    mock_read.assert_awaited_once_with(
        _URL,
        heavy_mode=False,
        profile=None,
        output_format="schema",
        tier=None,
        extraction_schema=schema,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("output_format", ["schema", "tables", "screenshot"])
async def test_every_non_text_format_with_links_is_refused(client: AsyncClient, output_format: str) -> None:
    # when
    with (
        patch(_READ_WITH_LINKS, new_callable=AsyncMock) as mock_read,
        patch(_GUARD, return_value=True),
    ):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": _URL, "include_links": True, "output_format": output_format},
        )

    # then
    assert resp.status_code == 400
    assert "include_links" in resp.json()["detail"]
    mock_read.assert_not_awaited()
