import logging
import re

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from prometheus_client import REGISTRY
from pydantic import BaseModel

from ascend_python_common.errors.codes import (
    BAD_REQUEST,
    CONTENT_TOO_LARGE,
    INTERNAL,
    INTERNAL_FIXED_DETAIL,
    METHOD_NOT_ALLOWED,
    NOT_ACCEPTABLE,
    NOT_FOUND,
    RATE_LIMITED,
    UNAUTHORIZED,
    UNAUTHORIZED_FIXED_DETAIL,
    UNSUPPORTED_MEDIA_TYPE,
    VALIDATION,
    ProblemCode,
)
from ascend_python_common.errors.handlers import install_error_handlers
from ascend_python_common.errors.mcp import McpRefusalMiddleware
from ascend_python_common.errors.problem import problem_response
from ascend_python_common.errors.refusals import operation_of
from ascend_python_common.errors.registry import ErrorRegistry
from ascend_python_common.tracing import current_trace_id

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def _counter(code: str, surface: str, operation: str) -> float:
    value = REGISTRY.get_sample_value(
        "ascend_service_errors_total",
        {"code": code, "surface": surface, "operation": operation},
    )
    return float(value) if value is not None else 0.0


class ItemIn(BaseModel):
    name: str
    age: int


class RefusedError(Exception):
    pass


class UpstreamError(Exception):
    pass


class BoomError(Exception):
    pass


def _app_with_registry(registry: ErrorRegistry, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    app = FastAPI()
    install_error_handlers(app, registry)

    @app.get("/items/{item_id}")
    def read_item(item_id: str) -> dict[str, str]:
        raise RefusedError("no such item")

    @app.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError("kaboom-secret")

    @app.post("/items")
    def create_item(payload: ItemIn) -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app, raise_server_exceptions=False)


def test_platform_codes_carry_expected_status() -> None:
    # given
    cases = {
        VALIDATION: 400,
        BAD_REQUEST: 400,
        UNAUTHORIZED: 401,
        NOT_FOUND: 404,
        METHOD_NOT_ALLOWED: 405,
        NOT_ACCEPTABLE: 406,
        CONTENT_TOO_LARGE: 413,
        UNSUPPORTED_MEDIA_TYPE: 415,
        RATE_LIMITED: 429,
        INTERNAL: 500,
    }
    # when
    observed = {code.code: code.status for code in cases}
    # then
    assert observed == {code.code: status for code, status in cases.items()}


def test_problem_body_has_all_standard_members(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    registry = ErrorRegistry()
    registry.register(RefusedError, NOT_FOUND, "missing thing")
    client = _app_with_registry(registry, monkeypatch)
    # when
    response = client.get("/items/abc")
    # then
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["type"] == "https://ascend.ai/errors/not-found"
    assert body["title"] == "Not Found"
    assert body["status"] == 404
    assert body["detail"] == "missing thing"
    assert body["instance"] == "/items/abc"
    assert body["code"] == "not_found"
    assert body["traceId"] == TRACE_ID


def test_unauthorized_answers_401_with_bearer_and_fixed_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    app = FastAPI()
    install_error_handlers(app, ErrorRegistry())

    @app.get("/private")
    def private() -> dict[str, str]:
        raise HTTPException(status_code=401, detail="bad token xyz")

    client = TestClient(app, raise_server_exceptions=False)
    # when
    response = client.get("/private")
    # then
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    body = response.json()
    assert body["code"] == "unauthorized"
    assert body["type"] == "https://ascend.ai/errors/unauthorized"
    assert body["detail"] == UNAUTHORIZED_FIXED_DETAIL
    assert "bad token xyz" not in body["detail"]
    assert body["traceId"] == TRACE_ID


def test_trace_id_left_out_when_no_trace_current() -> None:
    # given
    assert current_trace_id() is None
    registry = ErrorRegistry()
    registry.register(RefusedError, NOT_FOUND, "missing")
    app = FastAPI()
    install_error_handlers(app, registry)

    @app.get("/items/{item_id}")
    def read_item(item_id: str) -> dict[str, str]:
        raise RefusedError("gone")

    client = TestClient(app, raise_server_exceptions=False)
    # when
    response = client.get("/items/1")
    # then
    assert response.status_code == 404
    assert "traceId" not in response.json()


def test_validation_errors_sorted_without_location_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    registry = ErrorRegistry()
    client = _app_with_registry(registry, monkeypatch)
    # when
    response = client.post("/items", json={"age": "not-an-int"})
    # then
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation"
    assert body["type"] == "https://ascend.ai/errors/validation"
    fields = [entry["field"] for entry in body["errors"]]
    assert fields == sorted(fields)
    assert all(not entry["field"].startswith("body.") for entry in body["errors"])
    assert "name" in fields


def test_internal_500_hides_class_and_message(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    registry = ErrorRegistry()
    registry.register(RefusedError, NOT_FOUND, "missing")
    client = _app_with_registry(registry, monkeypatch)
    # when
    response = client.get("/boom")
    # then
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal"
    assert body["detail"] == INTERNAL_FIXED_DETAIL
    assert "RuntimeError" not in response.text
    assert "kaboom-secret" not in response.text


def test_upstream_502_503_504_and_expected_keep_registry_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    bad_gateway = ProblemCode("bad_gateway", 502)
    busy = ProblemCode("busy_service", 503)
    timeout = ProblemCode("gateway_timeout", 504)
    upstream = ProblemCode("DOWNLOAD_FAILED", 502)
    registry = ErrorRegistry()
    registry.register(RefusedError, bad_gateway, "downstream refused")
    registry.register(UpstreamError, upstream, "fetch failed for caller", expected=True)
    app = FastAPI()
    install_error_handlers(app, registry)

    @app.get("/bad")
    def bad() -> dict[str, str]:
        raise RefusedError("x")

    @app.get("/up")
    def up() -> dict[str, str]:
        raise UpstreamError("y")

    client = TestClient(app, raise_server_exceptions=False)
    # when
    bad_response = client.get("/bad")
    up_response = client.get("/up")
    # then
    assert bad_response.json()["detail"] == "downstream refused"
    assert up_response.json()["detail"] == "fetch failed for caller"
    assert bad_response.json()["code"] == "bad_gateway"
    assert up_response.json()["code"] == "DOWNLOAD_FAILED"
    assert busy.status == 503
    assert timeout.status == 504


def test_registry_refuses_internal_code_without_fixed_detail() -> None:
    # given
    registry = ErrorRegistry()
    # when
    with pytest.raises(ValueError, match="internal code entry must use the fixed detail"):
        registry.register(BoomError, INTERNAL, "something else")
    # then
    assert registry.lookup(BoomError("x")) is None


def test_registry_accepts_internal_code_with_fixed_detail() -> None:
    # given
    registry = ErrorRegistry()
    # when
    registry.register(BoomError, INTERNAL, INTERNAL_FIXED_DETAIL)
    # then
    assert registry.lookup(BoomError("x")) is not None


def test_extensions_never_replace_standard_members(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    registry = ErrorRegistry()
    registry.register(
        RefusedError,
        NOT_FOUND,
        "missing",
        extensions=lambda exc: {
            "vnc_url": "https://example.test/vnc",
            "type": "evil",
            "status": 999,
            "code": "evil",
            "detail": "evil",
            "title": "evil",
            "instance": "evil",
            "traceId": "evil",
        },
    )
    client = _app_with_registry(registry, monkeypatch)
    # when
    response = client.get("/items/1")
    # then
    body = response.json()
    assert body["vnc_url"] == "https://example.test/vnc"
    assert body["type"] == "https://ascend.ai/errors/not-found"
    assert body["status"] == 404
    assert body["code"] == "not_found"


def test_refusal_logs_one_warning_without_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    registry = ErrorRegistry()
    registry.register(RefusedError, NOT_FOUND, "missing")
    client = _app_with_registry(registry, monkeypatch)
    # when
    with caplog.at_level(logging.WARNING, logger="ascend_python_common.errors.refusals"):
        response = client.get("/items/1")
    # then
    assert response.status_code == 404
    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name == "ascend_python_common.errors.refusals"
    ]
    assert len([r for r in warnings if "not_found" in r.getMessage()]) == 1
    assert all(r.exc_info is None and r.exc_text is None for r in warnings)


def test_unexpected_logs_one_error_with_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    registry = ErrorRegistry()
    registry.register(RefusedError, NOT_FOUND, "missing")
    client = _app_with_registry(registry, monkeypatch)
    # when
    with caplog.at_level(logging.ERROR, logger="ascend_python_common.errors.refusals"):
        response = client.get("/boom")
    # then
    assert response.status_code == 500
    errors = [
        r
        for r in caplog.records
        if r.levelno == logging.ERROR and r.name == "ascend_python_common.errors.refusals"
    ]
    assert len(errors) >= 1
    assert any(r.exc_info is not None for r in errors)


def test_counter_uses_route_template_on_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    registry = ErrorRegistry()
    registry.register(RefusedError, NOT_FOUND, "missing")
    client = _app_with_registry(registry, monkeypatch)
    before = _counter("not_found", "rest", "/items/{item_id}")
    # when
    client.get("/items/some-id-123")
    # then
    assert _counter("not_found", "rest", "/items/{item_id}") == before + 1


def test_counter_uses_unmatched_for_unknown_path(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    registry = ErrorRegistry()
    client = _app_with_registry(registry, monkeypatch)
    before = _counter("not_found", "rest", "unmatched")
    # when
    response = client.get("/does-not-exist")
    # then
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    assert _counter("not_found", "rest", "unmatched") == before + 1


def test_counter_uses_tool_name_on_mcp() -> None:
    # given
    registry = ErrorRegistry()
    registry.register(RefusedError, VALIDATION, "bad input")
    server = FastMCP("probe")
    server.add_middleware(McpRefusalMiddleware(registry))

    @server.tool
    def insert(text: str) -> str:
        raise RefusedError("empty")

    async def _call() -> None:
        async with Client(server) as client:
            with pytest.raises(ToolError):
                await client.call_tool("insert", {"text": ""})

    import asyncio

    before = _counter("validation", "mcp", "insert")
    # when
    asyncio.run(_call())
    # then
    assert _counter("validation", "mcp", "insert") == before + 1


def test_two_tools_same_code_counted_separately() -> None:
    # given
    registry = ErrorRegistry()
    registry.register(RefusedError, RATE_LIMITED, "slow down")
    server = FastMCP("probe")
    server.add_middleware(McpRefusalMiddleware(registry))

    @server.tool
    def first_tool() -> str:
        raise RefusedError("one")

    @server.tool
    def second_tool() -> str:
        raise RefusedError("two")

    async def _calls() -> None:
        async with Client(server) as client:
            with pytest.raises(ToolError):
                await client.call_tool("first_tool", {})
            with pytest.raises(ToolError):
                await client.call_tool("second_tool", {})

    import asyncio

    before_first = _counter("rate_limited", "mcp", "first_tool")
    before_second = _counter("rate_limited", "mcp", "second_tool")
    # when
    asyncio.run(_calls())
    # then
    assert _counter("rate_limited", "mcp", "first_tool") == before_first + 1
    assert _counter("rate_limited", "mcp", "second_tool") == before_second + 1


def test_upper_code_maps_to_lower_case_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    assert ProblemCode("INTERNAL_ERROR", 500).type_uri() == ("https://ascend.ai/errors/internal-error")
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    upper = ProblemCode("INTERNAL_ERROR", 500)
    registry = ErrorRegistry(internal_code=upper)
    registry.register(BoomError, upper, INTERNAL_FIXED_DETAIL)
    app = FastAPI()
    install_error_handlers(app, registry)

    @app.get("/fail")
    def fail() -> dict[str, str]:
        raise BoomError("x")

    client = TestClient(app, raise_server_exceptions=False)
    # when
    response = client.get("/fail")
    # then
    assert response.json()["type"] == "https://ascend.ai/errors/internal-error"
    assert response.json()["code"] == "INTERNAL_ERROR"


def test_mcp_tool_error_text_is_code_colon_detail() -> None:
    # given
    registry = ErrorRegistry()
    registry.register(RefusedError, VALIDATION, "bad input")
    server = FastMCP("probe")
    server.add_middleware(McpRefusalMiddleware(registry))

    @server.tool
    def insert(text: str) -> str:
        raise RefusedError("empty")

    async def _call() -> str:
        async with Client(server) as client:
            with pytest.raises(ToolError) as exc_info:
                await client.call_tool("insert", {"text": ""})
            return str(exc_info.value)

    import asyncio

    # when
    message = asyncio.run(_call())
    # then
    assert message == "validation: bad input"


def test_mcp_unexpected_maps_to_internal_fixed_detail() -> None:
    # given
    registry = ErrorRegistry()
    registry.register(RefusedError, VALIDATION, "bad input")
    server = FastMCP("probe")
    server.add_middleware(McpRefusalMiddleware(registry))

    @server.tool
    def do() -> str:
        raise RuntimeError("secret-boom")

    async def _call() -> str:
        async with Client(server) as client:
            with pytest.raises(ToolError) as exc_info:
                await client.call_tool("do", {})
            return str(exc_info.value)

    import asyncio

    # when
    message = asyncio.run(_call())
    # then
    assert message == f"internal: {INTERNAL_FIXED_DETAIL}"
    assert "secret-boom" not in message
    assert "RuntimeError" not in message


def test_unknown_http_status_maps_to_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    app = FastAPI()
    install_error_handlers(app, ErrorRegistry())

    @app.get("/teapot")
    def teapot() -> dict[str, str]:
        raise HTTPException(status_code=418, detail="short and stout")

    client = TestClient(app, raise_server_exceptions=False)
    # when
    response = client.get("/teapot")
    # then
    body = response.json()
    assert response.status_code == 418
    assert body["code"] == "http_error"
    assert body["type"] == "https://ascend.ai/errors/http-error"
    assert body["detail"] == "short and stout"


def test_rate_limit_handler_answers_429_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    from ascend_python_common.rate_limit import build_limiter, install_rate_limiting

    limiter = build_limiter("1/minute")
    app = FastAPI()
    install_rate_limiting(app, limiter)
    install_error_handlers(app, ErrorRegistry())

    @app.get("/limited")
    def limited() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app, raise_server_exceptions=False)
    # when
    client.get("/limited")
    refused = client.get("/limited")
    # then
    assert refused.status_code == 429
    assert refused.json()["code"] == "rate_limited"
    assert refused.headers["content-type"] == "application/problem+json"
    assert "Retry-After" in refused.headers


def test_http_500_uses_fixed_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    app = FastAPI()
    install_error_handlers(app, ErrorRegistry())

    @app.get("/oops")
    def oops() -> dict[str, str]:
        raise HTTPException(status_code=500, detail="secret-db-password")

    client = TestClient(app, raise_server_exceptions=False)
    # when
    response = client.get("/oops")
    # then
    assert response.status_code == 500
    assert response.json()["detail"] == INTERNAL_FIXED_DETAIL
    assert "secret-db-password" not in response.text


def test_method_not_allowed_keeps_allow_header(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    app = FastAPI()
    install_error_handlers(app, ErrorRegistry())

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app, raise_server_exceptions=False)
    # when
    response = client.delete("/health")
    # then
    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"
    assert "Allow" in response.headers


def test_registry_supports_callable_detail_headers_extensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    busy = ProblemCode("busy_service", 503)
    registry = ErrorRegistry()
    registry.register(
        RefusedError,
        busy,
        lambda exc: f"busy because {exc}",
        headers=lambda exc: {"Retry-After": "12"},
        extensions={"static": "kept"},
        expected=True,
    )
    app = FastAPI()
    install_error_handlers(app, registry)

    @app.get("/busy")
    def busy_route() -> dict[str, str]:
        raise RefusedError("all full")

    client = TestClient(app, raise_server_exceptions=False)
    # when
    response = client.get("/busy")
    # then
    body = response.json()
    assert body["detail"] == "busy because all full"
    assert response.headers["Retry-After"] == "12"
    assert body["static"] == "kept"


def test_registry_supports_static_headers_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    registry = ErrorRegistry()
    registry.register(RefusedError, NOT_FOUND, "missing", headers={"X-Hint": "gone"}, extensions={"k": "v"})
    app = FastAPI()
    install_error_handlers(app, registry)

    @app.get("/gone")
    def gone() -> dict[str, str]:
        raise RefusedError("x")

    client = TestClient(app, raise_server_exceptions=False)
    # when
    response = client.get("/gone")
    # then
    assert response.headers["X-Hint"] == "gone"
    assert response.json()["k"] == "v"


def test_mcp_tool_error_carries_debug_log_level() -> None:
    # given
    import asyncio
    from types import SimpleNamespace

    registry = ErrorRegistry()
    registry.register(RefusedError, VALIDATION, "bad input")
    middleware = McpRefusalMiddleware(registry)

    async def _failing(_context: object) -> str:
        raise RefusedError("empty")

    context = SimpleNamespace(message=SimpleNamespace(name="insert"))
    # when
    with pytest.raises(ToolError) as exc_info:
        asyncio.run(middleware.on_call_tool(context, _failing))  # type: ignore[arg-type]
    # then
    assert exc_info.value.log_level == logging.DEBUG
    assert str(exc_info.value) == "validation: bad input"


def test_operation_of_returns_unmatched_without_route() -> None:
    # given
    scope = {"type": "http", "path": "/nothing"}
    request = Request(scope)
    # when
    operation = operation_of(request)
    # then
    assert operation == "unmatched"


def test_problem_response_keeps_static_headers_and_extensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr("ascend_python_common.errors.problem.current_trace_id", lambda: TRACE_ID)
    scope = {"type": "http", "headers": [], "path": "/x", "query_string": b""}
    request = Request(scope)
    # when
    response = problem_response(
        request,
        NOT_FOUND,
        "missing",
        headers={"Retry-After": "7"},
        extensions={"hint": "try again"},
    )
    # then
    assert response.headers["Retry-After"] == "7"
    assert re.match(r"[0-9a-f]{32}", TRACE_ID) is not None
