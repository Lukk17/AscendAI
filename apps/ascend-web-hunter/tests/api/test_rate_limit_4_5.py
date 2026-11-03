from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from ascend_python_common.rate_limit import McpRateLimitMiddleware, build_limiter
from httpx import ASGITransport, AsyncClient

from src.config.config import Settings
from src.config.config import settings as service_settings
from src.main import create_app


def test_rate_limit_default_is_1200_per_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.delenv("RATE_LIMIT_DEFAULT", raising=False)
    # when
    default = Settings().RATE_LIMIT_DEFAULT
    # then
    assert default == "1200/minute"


@pytest.mark.asyncio
async def test_rapid_successive_reads_within_limit_are_not_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(service_settings, "RATE_LIMIT_DEFAULT", "10/minute")
    limited_app = create_app()
    transport = ASGITransport(app=limited_app, raise_app_exceptions=False)
    # when
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        with (
            patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
            patch(
                "src.api.rest.rest_endpoints.web_reader.read",
                new_callable=AsyncMock,
                return_value={"content": "Extracted unit", "status": "success", "mode": "test"},
            ),
        ):
            statuses = [
                (
                    await client.post("/api/v2/web/read", json={"url": f"http://example-{index}.com/page"})
                ).status_code
                for index in range(5)
            ]
    # then
    assert statuses == [200, 200, 200, 200, 200]


@pytest.mark.asyncio
async def test_reads_of_one_domain_are_not_throttled(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(service_settings, "RATE_LIMIT_DEFAULT", "10/minute")
    limited_app = create_app()
    transport = ASGITransport(app=limited_app, raise_app_exceptions=False)
    # when
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        with (
            patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
            patch(
                "src.api.rest.rest_endpoints.web_reader.read",
                new_callable=AsyncMock,
                return_value={"content": "Extracted unit", "status": "success", "mode": "test"},
            ),
        ):
            statuses = [
                (
                    await client.post("/api/v2/web/read", json={"url": f"http://example.com/page-{index}"})
                ).status_code
                for index in range(5)
            ]
    # then
    assert statuses == [200, 200, 200, 200, 200]


@pytest.mark.asyncio
async def test_caller_over_limit_answers_429_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(service_settings, "RATE_LIMIT_DEFAULT", "3/minute")
    limited_app = create_app()
    transport = ASGITransport(app=limited_app, raise_app_exceptions=False)
    # when
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        with (
            patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
            patch(
                "src.api.rest.rest_endpoints.web_reader.read",
                new_callable=AsyncMock,
                return_value={"content": "Extracted unit", "status": "success", "mode": "test"},
            ),
        ):
            statuses = [
                (await client.post("/api/v2/web/read", json={"url": "http://example.com/page"})).status_code
                for _ in range(4)
            ]
            refused = await client.post("/api/v2/web/read", json={"url": "http://example.com/page"})
    # then
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429
    assert refused.status_code == 429
    assert refused.json()["code"] == "rate_limited"
    assert "retry-after" in {key.lower() for key in refused.headers}


@pytest.mark.asyncio
async def test_mcp_tool_call_after_limit_fails_with_rate_limited() -> None:
    # given
    middleware = McpRateLimitMiddleware(build_limiter("2/minute"), "2/minute")
    context = SimpleNamespace(
        message=SimpleNamespace(name="web_read"),
        fastmcp_context=None,
    )

    async def call_next(_context: Any) -> dict[str, str]:
        return {"status": "success"}

    for _ in range(2):
        # when
        result = await middleware.on_call_tool(context, call_next)  # type: ignore[arg-type]
        # then
        assert result == {"status": "success"}
    # when
    with pytest.raises(Exception, match=r"^rate_limited: ") as exc_info:
        await middleware.on_call_tool(context, call_next)  # type: ignore[arg-type]
    # then
    assert str(exc_info.value).startswith("rate_limited: ")
