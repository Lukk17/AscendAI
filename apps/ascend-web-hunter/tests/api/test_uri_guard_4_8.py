"""Task 4.8: ascend-web-hunter uses the library guard (design D21)."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

_METADATA_URL = "http://169.254.169.254/latest/meta-data"
_USERINFO_URL = "https://user:secret@example.com/"
_READ = "src.api.rest.rest_endpoints.web_reader.read"


@pytest.mark.asyncio
async def test_rest_read_of_metadata_address_answers_unsafe_uri(client: AsyncClient) -> None:
    # given
    payload = {"url": _METADATA_URL}

    # when
    with patch(_READ, new_callable=AsyncMock) as mock_read:
        resp = await client.post("/api/v2/web/read", json=payload)

    # then
    assert resp.status_code == 400
    assert resp.json()["code"] == "unsafe_uri"
    mock_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_rest_read_of_userinfo_url_answers_unsafe_uri(client: AsyncClient) -> None:
    # given
    payload = {"url": _USERINFO_URL}

    # when
    with patch(_READ, new_callable=AsyncMock) as mock_read:
        resp = await client.post("/api/v2/web/read", json=payload)

    # then
    assert resp.status_code == 400
    assert resp.json()["code"] == "unsafe_uri"
    mock_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_mcp_web_read_of_metadata_address_fails_with_unsafe_uri() -> None:
    # given
    from src.api.mcp.mcp_server import web_read

    # when
    with pytest.raises(Exception, match=r"^unsafe_uri: ") as exc_info:
        await web_read(_METADATA_URL)

    # then
    assert str(exc_info.value).startswith("unsafe_uri: ")


@pytest.mark.asyncio
async def test_mcp_session_establish_of_metadata_address_fails_with_unsafe_uri() -> None:
    # given
    from src.api.mcp.mcp_server import session_establish

    # when
    with pytest.raises(Exception, match=r"^unsafe_uri: ") as exc_info:
        await session_establish(_METADATA_URL)

    # then
    assert str(exc_info.value).startswith("unsafe_uri: ")


@pytest.mark.asyncio
async def test_mcp_session_status_of_metadata_address_fails_with_unsafe_uri() -> None:
    # given
    from src.api.mcp.mcp_server import session_status

    # when
    with pytest.raises(Exception, match=r"^unsafe_uri: ") as exc_info:
        await session_status(_METADATA_URL)

    # then
    assert str(exc_info.value).startswith("unsafe_uri: ")


@pytest.mark.asyncio
async def test_mcp_session_clear_of_metadata_address_fails_with_unsafe_uri() -> None:
    # given
    from src.api.mcp.mcp_server import session_clear

    # when
    with pytest.raises(Exception, match=r"^unsafe_uri: ") as exc_info:
        await session_clear(_METADATA_URL)

    # then
    assert str(exc_info.value).startswith("unsafe_uri: ")


@pytest.mark.asyncio
async def test_mcp_web_read_of_userinfo_url_fails_with_unsafe_uri() -> None:
    # given
    from src.api.mcp.mcp_server import web_read

    # when
    with pytest.raises(Exception, match=r"^unsafe_uri: ") as exc_info:
        await web_read(_USERINFO_URL)

    # then
    assert str(exc_info.value).startswith("unsafe_uri: ")
