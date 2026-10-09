from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from limits.storage import MemoryStorage
from slowapi import Limiter

from ascend_python_common.errors import ErrorRegistry, install_error_handlers
from ascend_python_common.rate_limit import (
    McpRateLimitMiddleware,
    build_limiter,
    install_rate_limiting,
)

LIMIT = "2/minute"
HIGH_DEFAULT = "10/minute"
SHARED_TOOL = "shared_tool"
SHARED_LIMIT = "2/minute"
SHARED_OPERATION = "shared_operation"
UNREACHABLE_REDIS_URI = "redis://127.0.0.1:9/0"


def _rest_app(limiter: Limiter | None = None) -> tuple[TestClient, Any]:
    # given
    owned = limiter if limiter is not None else build_limiter(LIMIT)
    app = FastAPI()
    install_rate_limiting(app, owned)
    install_error_handlers(app, ErrorRegistry())

    @app.get("/limited")
    def limited() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app), owned


def _mcp_server(default_limit: str, tool_limits: dict[str, str] | None = None) -> FastMCP:
    limiter = build_limiter(HIGH_DEFAULT)
    server = FastMCP("probe")

    @server.tool
    def echo(text: str) -> str:
        return text

    server.add_middleware(McpRateLimitMiddleware(limiter, default_limit, tool_limits))
    return server


def test_request_after_limit_answers_429_rate_limited_with_retry_after() -> None:
    # given
    client, _ = _rest_app()
    # when
    first = client.get("/limited")
    second = client.get("/limited")
    refused = client.get("/limited")
    # then
    assert first.status_code == 200
    assert second.status_code == 200
    assert refused.status_code == 429
    assert refused.json()["code"] == "rate_limited"
    assert refused.headers["content-type"] == "application/problem+json"
    assert "Retry-After" in refused.headers


def test_two_service_names_on_shared_storage_keep_separate_budgets() -> None:
    # given
    storage = _RecordingStorage()
    alpha_limiter = build_limiter(LIMIT, key_prefix="svc-alpha")
    beta_limiter = build_limiter(LIMIT, key_prefix="svc-beta")
    _use_shared_storage(alpha_limiter, storage)
    _use_shared_storage(beta_limiter, storage)
    alpha_client, _ = _rest_app(alpha_limiter)
    beta_client, _ = _rest_app(beta_limiter)
    beta_middleware = McpRateLimitMiddleware(
        beta_limiter, LIMIT, {SHARED_OPERATION: LIMIT}, key_prefix="svc-beta"
    )

    async def _next(context: Any) -> str:
        assert context is not None
        return "tool-ok"

    import asyncio

    # when
    alpha_first = alpha_client.get("/limited")
    alpha_second = alpha_client.get("/limited")
    alpha_refused = alpha_client.get("/limited")
    beta_first = beta_client.get("/limited")
    beta_mcp = asyncio.run(beta_middleware.on_call_tool(_tool_context(SHARED_OPERATION), _next))
    # then
    assert alpha_first.status_code == 200
    assert alpha_second.status_code == 200
    assert alpha_refused.status_code == 429
    assert beta_first.status_code == 200
    assert beta_mcp == "tool-ok"
    assert [key.split("/")[1] for key in storage.keys] == [
        "svc-alpha",
        "svc-alpha",
        "svc-alpha",
        "svc-beta",
        "svc-beta",
    ]


def test_unreachable_storage_lets_traffic_through(caplog: pytest.LogCaptureFixture) -> None:
    # given
    limiter = build_limiter(LIMIT, storage_uri=UNREACHABLE_REDIS_URI, key_prefix="svc")
    client, _ = _rest_app(limiter)
    middleware = McpRateLimitMiddleware(limiter, LIMIT, key_prefix="svc")

    async def _next(context: Any) -> str:
        assert context is not None
        return "tool-ok"

    import asyncio
    import logging

    # when
    with caplog.at_level(logging.WARNING):
        mcp_result = asyncio.run(middleware.on_call_tool(_tool_context("echo"), _next))
        response = client.get("/limited")
    # then
    assert mcp_result == "tool-ok"
    assert response.status_code == 200
    assert any("unreachable" in record.getMessage() for record in caplog.records)


def test_default_storage_is_in_memory() -> None:
    # given
    first = build_limiter(LIMIT)
    # when
    second = build_limiter(LIMIT)
    # then
    assert isinstance(first._storage, MemoryStorage)
    assert isinstance(second._storage, MemoryStorage)
    assert first._storage is not second._storage
    assert not first._key_prefix


def test_health_is_never_limited() -> None:
    # given
    client, _ = _rest_app()
    refused = None
    for _ in range(3):
        refused = client.get("/limited")
    # when
    health_answers = [client.get("/health").status_code for _ in range(10)]
    # then
    assert refused is not None
    assert refused.status_code == 429
    assert all(status == 200 for status in health_answers)


def test_tool_call_after_limit_fails_with_rate_limited() -> None:
    # given
    server = _mcp_server(LIMIT)

    # when
    async def _calls() -> str:
        async with Client(server) as client:
            first = await client.call_tool("echo", {"text": "one"})
            second = await client.call_tool("echo", {"text": "two"})
            assert "one" in str(first)
            assert "two" in str(second)
            with pytest.raises(ToolError) as exc_info:
                await client.call_tool("echo", {"text": "three"})
            return str(exc_info.value)

    import asyncio

    message = asyncio.run(_calls())
    # then
    assert message.startswith("rate_limited: ")


def test_tools_list_is_never_limited() -> None:
    # given
    server = _mcp_server("1/minute")

    # when
    async def _calls() -> list[list[str]]:
        async with Client(server) as client:
            await client.call_tool("echo", {"text": "only"})
            with pytest.raises(ToolError):
                await client.call_tool("echo", {"text": "over"})
            names_each: list[list[str]] = []
            for _ in range(5):
                tools = await client.list_tools()
                names_each.append([tool.name for tool in tools])
            return names_each

    import asyncio

    names_each = asyncio.run(_calls())
    # then
    assert all("echo" in names for names in names_each)


def test_rest_and_mcp_share_one_budget_for_same_limit_operation() -> None:
    # given
    limiter = build_limiter(HIGH_DEFAULT)
    app = FastAPI()
    install_rate_limiting(app, limiter)
    install_error_handlers(app, ErrorRegistry())

    @app.get("/shared")
    @limiter.shared_limit(LIMIT, scope=SHARED_TOOL)
    async def shared(request: Request, response: Response) -> dict[str, str]:
        assert request.url.path == "/shared"
        assert response is not None
        return {"status": "ok"}

    middleware = McpRateLimitMiddleware(limiter, HIGH_DEFAULT, {SHARED_TOOL: LIMIT})
    client = TestClient(app)

    async def _next(context: Any) -> str:
        assert context is not None
        return "tool-ok"

    carrying_request = SimpleNamespace(client=SimpleNamespace(host="testclient"))
    fake_context = SimpleNamespace(
        message=SimpleNamespace(name=SHARED_TOOL),
        fastmcp_context=SimpleNamespace(request_context=SimpleNamespace(request=carrying_request)),
    )
    # when
    import asyncio

    first = client.get("/shared")
    mcp_result = asyncio.run(middleware.on_call_tool(fake_context, _next))  # type: ignore[arg-type]
    refused = client.get("/shared")
    # then
    assert first.status_code == 200
    assert mcp_result == "tool-ok"
    assert refused.status_code == 429
    assert refused.json()["code"] == "rate_limited"


def test_unmapped_tool_uses_the_default_limit() -> None:
    # given
    server = _mcp_server("1/minute", {"other": "5/minute"})

    # when
    async def _calls() -> str:
        async with Client(server) as client:
            await client.call_tool("echo", {"text": "one"})
            with pytest.raises(ToolError) as exc_info:
                await client.call_tool("echo", {"text": "two"})
            return str(exc_info.value)

    import asyncio

    message = asyncio.run(_calls())
    # then
    assert message.startswith("rate_limited: ")


def test_invalid_default_limit_is_refused() -> None:
    # given
    invalid = "not-a-limit"
    # when
    with pytest.raises(ValueError, match="invalid rate limit"):
        build_limiter(invalid)
    # then
    assert invalid == "not-a-limit"


def test_streamed_answer_sends_one_response_start() -> None:
    # given
    limiter = build_limiter(HIGH_DEFAULT)
    app = FastAPI()
    install_rate_limiting(app, limiter)
    install_error_handlers(app, ErrorRegistry())

    @app.get("/stream")
    def stream() -> StreamingResponse:
        async def _chunks() -> AsyncIterator[bytes]:
            yield b"one"
            yield b"two"

        return StreamingResponse(_chunks(), media_type="text/plain")

    client = TestClient(app)
    # when
    response = client.get("/stream")
    # then
    assert response.status_code == 200
    assert response.text == "onetwo"


class _RecordingStorage(MemoryStorage):
    def __init__(self) -> None:
        super().__init__()
        self.keys: list[str] = []

    def incr(self, key: str, expiry: float, amount: int = 1) -> int:
        self.keys.append(key)
        return super().incr(key, expiry, amount)


def _use_shared_storage(limiter: Limiter, storage: MemoryStorage) -> None:
    limiter._storage = storage
    limiter._limiter.storage = storage


def _shared_app(limiter: Limiter, scope: str) -> TestClient:
    app = FastAPI()
    install_rate_limiting(app, limiter)
    install_error_handlers(app, ErrorRegistry())

    @app.get("/shared")
    @limiter.shared_limit(SHARED_LIMIT, scope=scope)
    async def shared(request: Request, response: Response) -> dict[str, str]:
        assert request.url.path == "/shared"
        assert response is not None
        return {"status": "ok"}

    return TestClient(app)


def _tool_context(tool_name: str) -> Any:
    carrying_request = SimpleNamespace(client=SimpleNamespace(host="testclient"))
    return SimpleNamespace(
        message=SimpleNamespace(name=tool_name),
        fastmcp_context=SimpleNamespace(request_context=SimpleNamespace(request=carrying_request)),
    )


def test_two_apps_on_shared_storage_share_one_rest_and_mcp_budget() -> None:
    # given
    storage = _RecordingStorage()
    first_limiter = build_limiter(SHARED_LIMIT, key_prefix="svc")
    second_limiter = build_limiter(SHARED_LIMIT, key_prefix="svc")
    _use_shared_storage(first_limiter, storage)
    _use_shared_storage(second_limiter, storage)
    first_client = _shared_app(first_limiter, SHARED_OPERATION)
    second_client = _shared_app(second_limiter, SHARED_OPERATION)
    second_middleware = McpRateLimitMiddleware(
        second_limiter, SHARED_LIMIT, {SHARED_OPERATION: SHARED_LIMIT}, key_prefix="svc"
    )

    async def _next(context: Any) -> str:
        assert context is not None
        return "tool-ok"

    import asyncio

    # when
    first = first_client.get("/shared")
    mcp_result = asyncio.run(second_middleware.on_call_tool(_tool_context(SHARED_OPERATION), _next))
    refused = second_client.get("/shared")
    # then
    assert first.status_code == 200
    assert mcp_result == "tool-ok"
    assert refused.status_code == 429
    assert refused.json()["code"] == "rate_limited"
