from types import SimpleNamespace
from typing import Any

import pytest
from ascend_python_common.rate_limit import McpRateLimitMiddleware, build_limiter
from httpx import ASGITransport, AsyncClient

from src.config.config import Settings
from src.config.config import settings as service_settings
from src.main import create_app

TRANSCRIBE_TOOLS = ["transcribe_local", "transcribe_openai", "transcribe_hf", "transcribe_audacity"]
TRANSCRIBE_ROUTES = [
    "/api/v1/transcribe/local",
    "/api/v1/transcribe/openai",
    "/api/v1/transcribe/hf",
    "/api/v1/transcribe/audacity",
]


def test_rate_limit_defaults_are_600_and_60_per_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.delenv("RATE_LIMIT_DEFAULT", raising=False)
    monkeypatch.delenv("RATE_LIMIT_TRANSCRIBE", raising=False)
    # when
    fresh = Settings()
    # then
    assert fresh.RATE_LIMIT_DEFAULT == "600/minute"
    assert fresh.RATE_LIMIT_TRANSCRIBE == "60/minute"


@pytest.mark.asyncio
@pytest.mark.parametrize("route", TRANSCRIBE_ROUTES)
async def test_transcription_route_answers_429_after_limit(
    monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    # given
    monkeypatch.setattr(service_settings, "RATE_LIMIT_DEFAULT", "3/minute")
    monkeypatch.setattr(service_settings, "RATE_LIMIT_TRANSCRIBE", "3/minute")
    limited_app = create_app()
    transport = ASGITransport(app=limited_app, raise_app_exceptions=False)
    # when
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        statuses: list[int] = []
        for _ in range(4):
            response = await client.post(route, files={})
            statuses.append(response.status_code)
        refused = await client.post(route, files={})
    # then
    assert statuses[3] == 429
    assert refused.status_code == 429
    assert refused.json()["code"] == "rate_limited"
    assert "retry-after" in {key.lower() for key in refused.headers}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", TRANSCRIBE_TOOLS)
async def test_transcription_tool_call_after_limit_fails_with_rate_limited(tool_name: str) -> None:
    # given
    middleware = McpRateLimitMiddleware(build_limiter("2/minute"), "2/minute", {tool_name: "2/minute"})
    context = SimpleNamespace(
        message=SimpleNamespace(name=tool_name),
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
