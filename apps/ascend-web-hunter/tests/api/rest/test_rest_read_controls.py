"""The REST read operation exposes output_format, tier, and the session_expired outcome.

Change close-web-search-scraping-follow-ups, tasks 2.3, 3.4 and 3.6.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

_URL = "http://unit.com/"
_READ = "src.api.rest.rest_endpoints.web_reader.read"
_READ_WITH_LINKS = "src.api.rest.rest_endpoints.web_reader.read_with_links"
_GUARD = "src.api.rest.rest_endpoints.is_safe_external_url"

_STRUCTURED_FIELDS = ["url", "content", "title", "author", "date", "sitename", "status", "mode"]
_SESSION_EXPIRED_FIELDS = ["url", "content", "status", "profile", "message"]


@pytest.mark.asyncio
async def test_read_forwards_output_format_and_tier(client: AsyncClient):
    result = {"content": "X", "status": "success", "mode": "4-playwright_stealth"}
    with (
        patch(_READ, new_callable=AsyncMock, return_value=result) as mock_read,
        patch(_GUARD, return_value=True),
    ):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": _URL, "output_format": "structured", "tier": "4-playwright_stealth"},
        )

    assert resp.status_code == 200
    mock_read.assert_awaited_once_with(
        _URL,
        heavy_mode=False,
        profile=None,
        output_format="structured",
        tier="4-playwright_stealth",
    )


@pytest.mark.asyncio
async def test_read_defaults_to_text_and_no_tier(client: AsyncClient):
    result = {"content": "X", "status": "success", "mode": "1-beautifulsoup"}
    with (
        patch(_READ, new_callable=AsyncMock, return_value=result) as mock_read,
        patch(_GUARD, return_value=True),
    ):
        resp = await client.post("/api/v2/web/read", json={"url": _URL})

    assert resp.status_code == 200
    mock_read.assert_awaited_once_with(_URL, heavy_mode=False, profile=None, output_format="text", tier=None)


@pytest.mark.asyncio
async def test_structured_read_returns_the_structured_contract(client: AsyncClient):
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
    with (
        patch(_READ, new_callable=AsyncMock, return_value=result),
        patch(_GUARD, return_value=True),
    ):
        resp = await client.post("/api/v2/web/read", json={"url": _URL, "output_format": "structured"})

    body = resp.json()
    for field in _STRUCTURED_FIELDS:
        assert field in body


@pytest.mark.asyncio
async def test_read_forwards_the_tier_on_the_links_path(client: AsyncClient):
    result = {"content": "X", "links": {}, "status": "success", "mode": "3-flaresolverr"}
    with (
        patch(_READ_WITH_LINKS, new_callable=AsyncMock, return_value=result) as mock_read,
        patch(_GUARD, return_value=True),
    ):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": _URL, "include_links": True, "tier": "3-flaresolverr"},
        )

    assert resp.status_code == 200
    mock_read.assert_awaited_once_with(
        _URL, None, heavy_mode=False, profile=None, output_format="text", tier="3-flaresolverr"
    )


@pytest.mark.asyncio
async def test_structured_with_links_is_rejected(client: AsyncClient):
    with (
        patch(_READ_WITH_LINKS, new_callable=AsyncMock) as mock_read,
        patch(_GUARD, return_value=True),
    ):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": _URL, "include_links": True, "output_format": "structured"},
        )

    assert resp.status_code == 400
    assert "include_links" in resp.json()["detail"]
    mock_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unknown_tier_is_rejected(client: AsyncClient):
    with patch(_GUARD, return_value=True):
        resp = await client.post("/api/v2/web/read", json={"url": _URL, "tier": "7-telepathy"})

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_output_format_is_rejected(client: AsyncClient):
    with patch(_GUARD, return_value=True):
        resp = await client.post("/api/v2/web/read", json={"url": _URL, "output_format": "yaml"})

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_session_expired_reaches_the_caller_whole(client: AsyncClient):
    result = {
        "content": "",
        "status": "session_expired",
        "profile": "work",
        "message": "Stored session for unit.com (profile=work) is no longer valid. Re-establish it.",
    }
    with (
        patch(_READ, new_callable=AsyncMock, return_value=result),
        patch(_GUARD, return_value=True),
    ):
        resp = await client.post("/api/v2/web/read", json={"url": _URL, "profile": "work"})

    assert resp.status_code == 200
    body = resp.json()
    for field in _SESSION_EXPIRED_FIELDS:
        assert field in body
    assert body["status"] == "session_expired"
