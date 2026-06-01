from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_ready_all_ok_returns_200(client: AsyncClient):
    with (
        patch("src.api.readiness._probe_redis", new=AsyncMock(return_value={"status": "ok"})),
        patch("src.api.readiness._probe_searxng", new=AsyncMock(return_value={"status": "ok"})),
        patch(
            "src.api.readiness._probe_flaresolverr",
            new=AsyncMock(return_value={"status": "ok"}),
        ),
    ):
        resp = await client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["redis"]["status"] == "ok"


@pytest.mark.asyncio
async def test_ready_degrades_when_any_check_fails(client: AsyncClient):
    with (
        patch("src.api.readiness._probe_redis", new=AsyncMock(return_value={"status": "ok"})),
        patch("src.api.readiness._probe_searxng", new=AsyncMock(return_value={"status": "ok"})),
        patch(
            "src.api.readiness._probe_flaresolverr",
            new=AsyncMock(return_value={"status": "error"}),
        ),
    ):
        resp = await client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"


@pytest.mark.asyncio
async def test_ready_response_does_not_leak_exception_detail(client: AsyncClient):
    """Security: /ready must not echo upstream exception strings."""
    with (
        patch("src.api.readiness._probe_redis", new=AsyncMock(return_value={"status": "error"})),
        patch("src.api.readiness._probe_searxng", new=AsyncMock(return_value={"status": "ok"})),
        patch(
            "src.api.readiness._probe_flaresolverr",
            new=AsyncMock(return_value={"status": "ok"}),
        ),
    ):
        resp = await client.get("/ready")
    body = resp.text
    assert "redis://" not in body
    assert "password" not in body.lower()


@pytest.mark.asyncio
async def test_probe_redis_skipped_when_url_empty():
    from src.api.readiness import _probe_redis

    with patch("src.api.readiness.settings.REDIS_URL", ""):
        result = await _probe_redis()
    assert result["status"] == "skipped"


@pytest.mark.asyncio
async def test_probe_redis_ok_path():
    from src.api.readiness import _probe_redis

    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(return_value=True)
    mock_client.aclose = AsyncMock()
    with patch("src.api.readiness.redis.from_url", return_value=mock_client):
        result = await _probe_redis()
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_probe_redis_error_path_returns_redacted_status():
    from src.api.readiness import _probe_redis

    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(side_effect=RuntimeError("redis://user:pw@host/0 down"))
    mock_client.aclose = AsyncMock(side_effect=RuntimeError("close failed"))
    with patch("src.api.readiness.redis.from_url", return_value=mock_client):
        result = await _probe_redis()
    assert result == {"status": "error"}


@pytest.mark.asyncio
async def test_probe_searxng_ok():
    from src.api.readiness import _probe_searxng

    response = MagicMock()
    response.status_code = 200
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(return_value=response)
    with patch("src.api.readiness.httpx.AsyncClient", return_value=mock_client):
        result = await _probe_searxng()
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_probe_searxng_non_200_is_error():
    from src.api.readiness import _probe_searxng

    response = MagicMock()
    response.status_code = 503
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(return_value=response)
    with patch("src.api.readiness.httpx.AsyncClient", return_value=mock_client):
        result = await _probe_searxng()
    assert result == {"status": "error"}


@pytest.mark.asyncio
async def test_probe_searxng_exception_redacted():
    from src.api.readiness import _probe_searxng

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(side_effect=RuntimeError("dns nope"))
    with patch("src.api.readiness.httpx.AsyncClient", return_value=mock_client):
        result = await _probe_searxng()
    assert result == {"status": "error"}


@pytest.mark.asyncio
async def test_probe_flaresolverr_posts_sessions_list():
    from src.api.readiness import _probe_flaresolverr

    response = MagicMock()
    response.status_code = 200
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post = AsyncMock(return_value=response)
    with patch("src.api.readiness.httpx.AsyncClient", return_value=mock_client):
        result = await _probe_flaresolverr()
    assert result["status"] == "ok"
    mock_client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_probe_flaresolverr_non_200_is_error():
    from src.api.readiness import _probe_flaresolverr

    response = MagicMock()
    response.status_code = 405
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post = AsyncMock(return_value=response)
    with patch("src.api.readiness.httpx.AsyncClient", return_value=mock_client):
        result = await _probe_flaresolverr()
    assert result == {"status": "error"}


@pytest.mark.asyncio
async def test_probe_flaresolverr_exception_redacted():
    from src.api.readiness import _probe_flaresolverr

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post = AsyncMock(side_effect=RuntimeError("net"))
    with patch("src.api.readiness.httpx.AsyncClient", return_value=mock_client):
        result = await _probe_flaresolverr()
    assert result == {"status": "error"}
