from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ascend_python_common.readiness import ProbeResult
from httpx import AsyncClient

from src.circuit_breaker.breaker import BreakerState


def _ok() -> ProbeResult:
    return ProbeResult(status="ok")


def _patch_all_ok() -> tuple[Any, ...]:
    return (
        patch("src.api.readiness.probe_redis", new=AsyncMock(return_value=ProbeResult(status="ok"))),
        patch("src.api.readiness.probe_searxng", new=AsyncMock(return_value=_ok())),
        patch("src.api.readiness.probe_flaresolverr", new=AsyncMock(return_value=_ok())),
        patch(
            "src.api.readiness.probe_searxng_breaker",
            return_value=ProbeResult(status="ok", details={"breaker": "closed"}),
        ),
        patch(
            "src.api.readiness.probe_flaresolverr_breaker",
            return_value=ProbeResult(status="ok", details={"breaker": "closed"}),
        ),
    )


@pytest.mark.asyncio
async def test_ready_all_ok_returns_200(client: AsyncClient) -> None:
    # given
    patches = _patch_all_ok()
    # when
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        resp = await client.get("/ready")
    # then
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["service"] == "ascend-web-hunter"
    assert body["checks"]["redis"]["status"] == "ok"


@pytest.mark.asyncio
async def test_ready_not_ready_when_any_check_fails(client: AsyncClient) -> None:
    # given
    patches = _patch_all_ok()
    down = patch(
        "src.api.readiness.probe_flaresolverr",
        new=AsyncMock(return_value=ProbeResult(status="error")),
    )
    # when
    with patches[0], patches[1], down, patches[3], patches[4]:
        resp = await client.get("/ready")
    # then
    assert resp.status_code == 503
    assert resp.json()["status"] == "not-ready"


@pytest.mark.asyncio
async def test_ready_response_does_not_leak_exception_detail(client: AsyncClient) -> None:
    # given
    patches = _patch_all_ok()
    down = patch("src.api.readiness.probe_redis", new=AsyncMock(return_value=ProbeResult(status="error")))
    # when
    with down, patches[1], patches[2], patches[3], patches[4]:
        resp = await client.get("/ready")
    # then
    body = resp.text
    assert "redis://" not in body
    assert "password" not in body.lower()


@pytest.mark.asyncio
async def test_ready_not_ready_when_flaresolverr_breaker_open(client: AsyncClient) -> None:
    # given
    patches = _patch_all_ok()
    open_breaker = patch(
        "src.api.readiness.probe_flaresolverr_breaker",
        return_value=ProbeResult(status="degraded", details={"breaker": "open"}),
    )
    # when
    with patches[0], patches[1], patches[2], patches[3], open_breaker:
        resp = await client.get("/ready")
    # then
    assert resp.status_code == 503
    body = resp.json()
    assert body["checks"]["flaresolverr_breaker"]["breaker"] == "open"


@pytest.mark.asyncio
async def test_ready_not_ready_when_searxng_breaker_open(client: AsyncClient) -> None:
    # given
    patches = _patch_all_ok()
    open_breaker = patch(
        "src.api.readiness.probe_searxng_breaker",
        return_value=ProbeResult(status="degraded", details={"breaker": "open"}),
    )
    # when
    with patches[0], patches[1], patches[2], open_breaker, patches[4]:
        resp = await client.get("/ready")
    # then
    assert resp.status_code == 503
    body = resp.json()
    assert body["checks"]["searxng_breaker"]["breaker"] == "open"


@pytest.mark.asyncio
async def test_ready_not_ready_when_breaker_is_half_open(client: AsyncClient) -> None:
    # given
    patches = _patch_all_ok()
    half_open = patch(
        "src.api.readiness.probe_searxng_breaker",
        return_value=ProbeResult(status="degraded", details={"breaker": "half_open"}),
    )
    # when
    with patches[0], patches[1], patches[2], half_open, patches[4]:
        resp = await client.get("/ready")
    # then
    assert resp.status_code == 503
    body = resp.json()
    assert body["checks"]["searxng_breaker"]["breaker"] == "half_open"


@pytest.mark.asyncio
async def test_probe_redis_skipped_when_url_empty() -> None:
    # given
    from src.api.readiness import probe_redis

    # when
    with patch("src.api.readiness.settings.REDIS_URL", ""):
        result = await probe_redis()
    # then
    assert result.status == "skipped"


@pytest.mark.asyncio
async def test_probe_redis_ok_path() -> None:
    # given
    from src.api.readiness import probe_redis

    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(return_value=True)
    mock_client.aclose = AsyncMock()
    # when
    with patch("src.api.readiness.redis.from_url", return_value=mock_client):
        result = await probe_redis()
    # then
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_probe_redis_error_path_returns_redacted_status() -> None:
    # given
    from src.api.readiness import probe_redis

    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(side_effect=RuntimeError("redis://user:pw@host/0 down"))
    mock_client.aclose = AsyncMock(side_effect=RuntimeError("close failed"))
    # when
    with patch("src.api.readiness.redis.from_url", return_value=mock_client):
        result = await probe_redis()
    # then
    assert result == ProbeResult(status="error")


@pytest.mark.asyncio
async def test_probe_searxng_ok() -> None:
    # given
    from src.api.readiness import probe_searxng

    response = MagicMock()
    response.status_code = 200
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(return_value=response)
    # when
    with patch("src.api.readiness.httpx.AsyncClient", return_value=mock_client):
        result = await probe_searxng()
    # then
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_probe_searxng_non_200_is_error() -> None:
    # given
    from src.api.readiness import probe_searxng

    response = MagicMock()
    response.status_code = 503
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(return_value=response)
    # when
    with patch("src.api.readiness.httpx.AsyncClient", return_value=mock_client):
        result = await probe_searxng()
    # then
    assert result == ProbeResult(status="error")


@pytest.mark.asyncio
async def test_probe_searxng_exception_redacted() -> None:
    # given
    from src.api.readiness import probe_searxng

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(side_effect=RuntimeError("dns nope"))
    # when
    with patch("src.api.readiness.httpx.AsyncClient", return_value=mock_client):
        result = await probe_searxng()
    # then
    assert result == ProbeResult(status="error")


@pytest.mark.asyncio
async def test_probe_flaresolverr_posts_sessions_list() -> None:
    # given
    from src.api.readiness import probe_flaresolverr

    response = MagicMock()
    response.status_code = 200
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post = AsyncMock(return_value=response)
    # when
    with patch("src.api.readiness.httpx.AsyncClient", return_value=mock_client):
        result = await probe_flaresolverr()
    # then
    assert result.status == "ok"
    mock_client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_probe_flaresolverr_non_200_is_error() -> None:
    # given
    from src.api.readiness import probe_flaresolverr

    response = MagicMock()
    response.status_code = 405
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post = AsyncMock(return_value=response)
    # when
    with patch("src.api.readiness.httpx.AsyncClient", return_value=mock_client):
        result = await probe_flaresolverr()
    # then
    assert result == ProbeResult(status="error")


@pytest.mark.asyncio
async def test_probe_flaresolverr_exception_redacted() -> None:
    # given
    from src.api.readiness import probe_flaresolverr

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post = AsyncMock(side_effect=RuntimeError("net"))
    # when
    with patch("src.api.readiness.httpx.AsyncClient", return_value=mock_client):
        result = await probe_flaresolverr()
    # then
    assert result == ProbeResult(status="error")


def test_probe_searxng_breaker_closed() -> None:
    # given
    from src.api import readiness as readiness_module

    # when
    with patch("src.api.readiness.searxng_breaker") as mock_breaker:
        mock_breaker.state = BreakerState.CLOSED
        result = readiness_module.probe_searxng_breaker()
    # then
    assert result == ProbeResult(status="ok", details={"breaker": "closed"})


def test_probe_searxng_breaker_open() -> None:
    # given
    from src.api import readiness as readiness_module

    # when
    with patch("src.api.readiness.searxng_breaker") as mock_breaker:
        mock_breaker.state = BreakerState.OPEN
        result = readiness_module.probe_searxng_breaker()
    # then
    assert result == ProbeResult(status="degraded", details={"breaker": "open"})


def test_probe_searxng_breaker_half_open() -> None:
    # given
    from src.api import readiness as readiness_module

    # when
    with patch("src.api.readiness.searxng_breaker") as mock_breaker:
        mock_breaker.state = BreakerState.HALF_OPEN
        result = readiness_module.probe_searxng_breaker()
    # then
    assert result == ProbeResult(status="degraded", details={"breaker": "half_open"})


def test_probe_flaresolverr_breaker_closed() -> None:
    # given
    from src.api import readiness as readiness_module

    # when
    with patch("src.api.readiness.flaresolverr_breaker") as mock_breaker:
        mock_breaker.state = BreakerState.CLOSED
        result = readiness_module.probe_flaresolverr_breaker()
    # then
    assert result == ProbeResult(status="ok", details={"breaker": "closed"})


def test_probe_flaresolverr_breaker_open() -> None:
    # given
    from src.api import readiness as readiness_module

    # when
    with patch("src.api.readiness.flaresolverr_breaker") as mock_breaker:
        mock_breaker.state = BreakerState.OPEN
        result = readiness_module.probe_flaresolverr_breaker()
    # then
    assert result == ProbeResult(status="degraded", details={"breaker": "open"})


def test_probe_flaresolverr_breaker_half_open() -> None:
    # given
    from src.api import readiness as readiness_module

    # when
    with patch("src.api.readiness.flaresolverr_breaker") as mock_breaker:
        mock_breaker.state = BreakerState.HALF_OPEN
        result = readiness_module.probe_flaresolverr_breaker()
    # then
    assert result == ProbeResult(status="degraded", details={"breaker": "half_open"})
