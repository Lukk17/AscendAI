import asyncio
import dataclasses
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version as package_version
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from limits.storage import MemoryStorage
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from starlette.responses import Response
from starlette.routing import Match
from starlette.types import Message, Receive, Scope, Send

from ascend_python_common.app import (
    MCP_PATH,
    McpPathRoute,
    ServiceDefinition,
    create_service_app,
)
from ascend_python_common.errors import ErrorRegistry
from ascend_python_common.errors.codes import VALIDATION
from ascend_python_common.readiness import ProbeResult
from ascend_python_common.request_context import CorrelationIdMiddleware
from ascend_python_common.security_headers import SecurityHeadersMiddleware
from ascend_python_common.settings import RateLimit, ServiceSettings


class _Settings(ServiceSettings):
    API_PORT: int = 9917
    RATE_LIMIT_DEFAULT: RateLimit = "100/minute"


async def _ok_probe() -> ProbeResult:
    return ProbeResult(status="ok")


def _sync_ok_probe() -> ProbeResult:
    return ProbeResult(status="ok")


def _server(name: str = "test-service") -> FastMCP:
    server = FastMCP(name)

    @server.tool
    def echo(text: str) -> str:
        return text

    return server


def _definition(
    *,
    name: str = "test-service",
    probes: dict[str, Any] | None = None,
    registry: ErrorRegistry | None = None,
    lifespan: Any = None,
    banner: Any = None,
    routers: tuple[Any, ...] = (),
    tool_rate_limits: dict[str, str] | None = None,
    settings: _Settings | None = None,
) -> ServiceDefinition:
    return ServiceDefinition(
        name=name,
        distribution="ascend-python-common",
        settings=settings if settings is not None else _Settings(),
        mcp=_server(name),
        routers=routers,
        error_registry=registry if registry is not None else ErrorRegistry(),
        probes=probes if probes is not None else {"ok": _ok_probe},
        lifespan=lifespan,
        tool_rate_limits=tool_rate_limits,
        startup_banner=banner,
    )


def test_health_answers_ok_with_service_and_version() -> None:
    # given
    app = create_service_app(_definition(name="probe-service"))
    client = TestClient(app)
    # when
    response = client.get("/health")
    # then
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "probe-service",
        "version": package_version("ascend-python-common"),
    }


def test_ready_answers_200_when_all_probes_ok_or_skipped() -> None:
    # given
    async def _skipped() -> ProbeResult:
        return ProbeResult(status="skipped", details={"reason": "no gpu"})

    app = create_service_app(
        _definition(probes={"db": _ok_probe, "gpu": _skipped}),
    )
    client = TestClient(app)
    # when
    response = client.get("/ready")
    # then
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "test-service",
        "version": package_version("ascend-python-common"),
        "checks": {
            "db": {"status": "ok"},
            "gpu": {"status": "skipped", "reason": "no gpu"},
        },
    }


def test_ready_answers_503_not_ready_when_a_probe_degrades() -> None:
    # given
    async def _degraded() -> ProbeResult:
        return ProbeResult(status="degraded")

    app = create_service_app(_definition(probes={"queue": _degraded}))
    client = TestClient(app)
    # when
    response = client.get("/ready")
    # then
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not-ready"
    assert body["checks"] == {"queue": {"status": "degraded"}}


def test_raising_probe_is_reported_as_error_without_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given
    secret = "boom-secret-9f3k"

    async def _raising() -> ProbeResult:
        raise ValueError(secret)

    app = create_service_app(_definition(probes={"db": _raising}))
    client = TestClient(app)
    logging.getLogger().addHandler(caplog.handler)
    # when
    with caplog.at_level(logging.WARNING, logger="ascend_python_common.readiness"):
        response = client.get("/ready")
    # then
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not-ready"
    assert body["checks"]["db"]["status"] == "error"
    assert secret not in response.text
    assert "Traceback" not in response.text
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_probes_run_at_once() -> None:
    # given
    def _slow(name: str) -> Any:
        async def _probe() -> ProbeResult:
            await asyncio.sleep(0.5)
            return ProbeResult(status="ok")

        _probe.__name__ = name
        return _probe

    app = create_service_app(_definition(probes={"one": _slow("one"), "two": _slow("two")}))
    client = TestClient(app)
    # when
    started = time.monotonic()
    response = client.get("/ready")
    elapsed = time.monotonic() - started
    # then
    assert response.status_code == 200
    assert elapsed < 0.9


def test_timed_out_probe_is_reported_as_error() -> None:
    # given
    settings = _Settings(READINESS_PROBE_TIMEOUT_SECONDS=0.05)

    async def _hangs() -> ProbeResult:
        await asyncio.sleep(5.0)
        return ProbeResult(status="ok")

    app = create_service_app(_definition(probes={"slow": _hangs}, settings=settings))
    client = TestClient(app)
    # when
    response = client.get("/ready")
    # then
    assert response.status_code == 503
    assert response.json()["checks"] == {"slow": {"status": "error"}}


def test_probe_slower_than_configured_budget_is_reported_as_error_with_503() -> None:
    # given
    async def _slow() -> ProbeResult:
        await asyncio.sleep(0.5)
        return ProbeResult(status="ok")

    settings = _Settings(READINESS_PROBE_TIMEOUT_SECONDS=0.1)
    app = create_service_app(_definition(probes={"slow": _slow}, settings=settings))
    client = TestClient(app)
    # when
    response = client.get("/ready")
    # then
    assert response.status_code == 503
    assert response.json()["checks"] == {"slow": {"status": "error"}}


def test_sync_probe_runs_in_a_thread() -> None:
    # given
    app = create_service_app(_definition(probes={"disk": _sync_ok_probe}))
    client = TestClient(app)
    # when
    response = client.get("/ready")
    # then
    assert response.status_code == 200
    assert response.json()["checks"] == {"disk": {"status": "ok"}}


def test_ready_with_no_probes_is_ready_with_empty_checks() -> None:
    # given
    app = create_service_app(_definition(probes={}))
    client = TestClient(app)
    # when
    response = client.get("/ready")
    # then
    assert response.status_code == 200
    assert response.json()["checks"] == {}


def test_readiness_probe_budget_defaults_to_three_seconds() -> None:
    # given
    env_isolated = True
    # when
    settings = _Settings()
    # then
    assert env_isolated
    assert settings.READINESS_PROBE_TIMEOUT_SECONDS == 3.0


def test_unknown_path_answers_problem_404_with_request_id_echo() -> None:
    # given
    app = create_service_app(_definition())
    client = TestClient(app)
    # when
    response = client.get("/nonexistent", headers={"x-request-id": "probe-123"})
    # then
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "not_found"
    assert body["status"] == 404
    assert body["instance"] == "/nonexistent"
    assert response.headers["x-request-id"] == "probe-123"


def test_delete_health_answers_problem_405_with_allow() -> None:
    # given
    app = create_service_app(_definition())
    client = TestClient(app)
    # when
    response = client.delete("/health")
    # then
    assert response.status_code == 405
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "method_not_allowed"
    assert "GET" in response.headers["allow"]


def test_security_headers_are_present_on_health() -> None:
    # given
    app = create_service_app(_definition())
    client = TestClient(app)
    # when
    response = client.get("/health")
    # then
    assert response.headers["strict-transport-security"] == ("max-age=63072000; includeSubDomains; preload")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert response.headers["content-security-policy"] == (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    )


def test_security_headers_keep_a_route_set_value() -> None:
    # given
    router = APIRouter()

    @router.get("/framed")
    def framed() -> Response:
        return Response("framed", headers={"x-frame-options": "SAMEORIGIN"})

    app = create_service_app(_definition(routers=(router,)))
    client = TestClient(app)
    # when
    response = client.get("/framed")
    # then
    assert response.status_code == 200
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_hsts_max_age_follows_the_setting() -> None:
    # given
    settings = _Settings(SECURITY_HSTS_MAX_AGE_SECONDS=60)
    app = create_service_app(_definition(settings=settings))
    client = TestClient(app)
    # when
    response = client.get("/health")
    # then
    assert response.headers["strict-transport-security"] == "max-age=60; includeSubDomains; preload"


def test_security_middleware_passes_non_http_scopes_through() -> None:
    # given
    seen: list[str] = []

    async def _inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(str(scope["type"]))

    async def _receive() -> Message:
        return {"type": "lifespan.startup"}

    async def _send(message: Message) -> None:
        seen.append(str(message["type"]))

    middleware = SecurityHeadersMiddleware(_inner, 63072000)
    # when
    asyncio.run(middleware({"type": "lifespan"}, _receive, _send))
    # then
    assert seen == ["lifespan"]


def test_metrics_excludes_health_ready_and_metrics_handlers() -> None:
    # given
    app = create_service_app(_definition())
    client = TestClient(app)
    client.get("/health")
    client.get("/ready")
    # when
    response = client.get("/metrics")
    # then
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert 'handler="/health"' not in response.text
    assert 'handler="/ready"' not in response.text
    assert "http_requests_total" in response.text or "http_request_duration_seconds" in response.text


def test_mcp_initialize_answers_through_the_mcp_path() -> None:
    # given
    app = create_service_app(_definition(name="probe-service"))
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "probe", "version": "0.0.1"},
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    # when
    with TestClient(app) as client:
        response = client.post("/mcp", json=payload, headers=headers)
    # then
    assert response.status_code == 200
    assert "probe-service" in response.text


def test_mcp_path_route_matches_only_the_mcp_paths() -> None:
    # given
    async def _noop(scope: Scope, receive: Receive, send: Send) -> None:
        return None

    route = McpPathRoute(_noop)
    # when
    exact, _ = route.matches({"type": "http", "path": MCP_PATH})
    slashed, _ = route.matches({"type": "http", "path": MCP_PATH + "/"})
    nested, _ = route.matches({"type": "http", "path": MCP_PATH + "/extra"})
    other, _ = route.matches({"type": "http", "path": "/other"})
    # then
    assert exact == Match.FULL
    assert slashed == Match.FULL
    assert nested == Match.NONE
    assert other == Match.NONE


def test_mcp_route_passes_the_scope_through_unchanged() -> None:
    # given
    seen: list[Scope] = []

    async def _capture(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope)

    route = McpPathRoute(_capture)
    scope: Scope = {"type": "http", "path": "/mcp", "marker": "kept"}

    async def _receive() -> Message:
        return {"type": "http.request", "body": b""}

    sent: list[Message] = []

    async def _send(message: Message) -> None:
        sent.append(message)

    # when
    asyncio.run(route.handle(scope, _receive, _send))
    # then
    assert seen == [{"type": "http", "path": "/mcp", "marker": "kept"}]


def test_outer_stack_is_correlation_then_tracing() -> None:
    # given
    app = create_service_app(_definition())
    # when
    stack = app.build_middleware_stack()
    # then
    assert isinstance(stack, CorrelationIdMiddleware)
    assert isinstance(stack.app, OpenTelemetryMiddleware)


def test_lifespan_enters_service_before_banner_and_leaves_after() -> None:
    # given
    order: list[str] = []

    @asynccontextmanager
    async def _lifespan() -> AsyncIterator[None]:
        order.append("service-start")
        yield
        order.append("service-stop")

    def _banner() -> list[str]:
        order.append("banner-built")
        return ["banner-built"]

    app = create_service_app(_definition(lifespan=_lifespan(), banner=_banner))
    # when
    with TestClient(app):
        pass
    # then
    assert order == ["service-start", "banner-built", "service-stop"]


def test_service_lifespan_and_banner_are_optional() -> None:
    # given
    app = create_service_app(_definition())
    client = TestClient(app)
    # when
    response = client.get("/health")
    # then
    assert response.status_code == 200


def test_mcp_middlewares_map_registered_errors() -> None:
    # given
    registry = ErrorRegistry()
    registry.register(ValueError, VALIDATION, "bad input")
    definition = _definition(registry=registry)

    @definition.mcp.tool
    def breaks() -> str:
        raise ValueError("bad input")

    create_service_app(definition)

    async def _calls() -> str:
        async with Client(definition.mcp) as client:
            with pytest.raises(ToolError) as exc_info:
                await client.call_tool("breaks", {})
            return str(exc_info.value)

    # when
    message = asyncio.run(_calls())
    # then
    assert message.startswith("validation: ")


def test_service_definition_is_frozen() -> None:
    # given
    definition = _definition()
    # when
    with pytest.raises(dataclasses.FrozenInstanceError):
        definition.name = "other"  # type: ignore[misc]
    # then
    assert definition.name == "test-service"


def test_rate_limit_storage_uri_defaults_to_memory() -> None:
    # given
    definition = _definition(name="probe-service")
    # when
    storage_uri = definition.rate_limit_storage_uri
    # then
    assert storage_uri == "memory://"


def test_limiter_uses_configured_storage_and_service_name_prefix() -> None:
    # given
    definition = _definition(name="probe-service")
    # when
    app: FastAPI = create_service_app(definition)
    # then
    assert isinstance(app.state.limiter._storage, MemoryStorage)
    assert app.state.limiter._key_prefix == "probe-service"


def test_app_carries_service_name_and_distribution_version() -> None:
    # given
    definition = _definition(name="probe-service")
    # when
    app: FastAPI = create_service_app(definition)
    # then
    assert app.title == "probe-service"
    assert app.version == package_version("ascend-python-common")
