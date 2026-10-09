from types import SimpleNamespace
from typing import Any

import pytest
from ascend_python_common.rate_limit import McpRateLimitMiddleware, build_limiter
from httpx import ASGITransport, AsyncClient

from src.config.config import Settings
from src.config.config import settings as service_settings
from src.main import create_app


def test_rate_limit_default_is_6000_per_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.delenv("RATE_LIMIT_DEFAULT", raising=False)
    # when
    default = Settings().RATE_LIMIT_DEFAULT
    # then
    assert default == "6000/minute"


@pytest.mark.asyncio
async def test_request_after_limit_answers_429_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(service_settings, "RATE_LIMIT_DEFAULT", "3/minute")
    monkeypatch.setattr(service_settings, "REDIS_URL", "memory://")
    limited_app = create_app()
    transport = ASGITransport(app=limited_app, raise_app_exceptions=False)
    # when
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        statuses: list[int] = []
        for _ in range(4):
            response = await client.post("/api/v1/memory/insert", json={})
            statuses.append(response.status_code)
        refused = await client.post("/api/v1/memory/insert", json={})
    # then
    assert statuses[:3] == [400, 400, 400]
    assert statuses[3] == 429
    assert refused.status_code == 429
    assert refused.json()["code"] == "rate_limited"
    assert "retry-after" in {key.lower() for key in refused.headers}


@pytest.mark.asyncio
async def test_mcp_tool_call_after_limit_fails_with_rate_limited() -> None:
    # given
    middleware = McpRateLimitMiddleware(build_limiter("3/minute"), "3/minute")
    context = SimpleNamespace(
        message=SimpleNamespace(name="memory_search"),
        fastmcp_context=None,
    )

    async def call_next(_context: Any) -> dict[str, str]:
        return {"status": "success"}

    for _ in range(3):
        # when
        result = await middleware.on_call_tool(context, call_next)  # type: ignore[arg-type]
        # then
        assert result == {"status": "success"}
    # when
    with pytest.raises(Exception, match=r"^rate_limited: ") as exc_info:
        await middleware.on_call_tool(context, call_next)  # type: ignore[arg-type]
    # then
    assert str(exc_info.value).startswith("rate_limited: ")
