import logging
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from importlib.metadata import version as package_version
from typing import Any, Final

from fastapi import APIRouter, FastAPI
from fastmcp import FastMCP
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Match
from starlette.types import ASGIApp, Receive, Scope, Send

from ascend_python_common.errors import (
    ErrorRegistry,
    McpRefusalMiddleware,
    install_error_handlers,
)
from ascend_python_common.log_config import configure_logging
from ascend_python_common.rate_limit import (
    DEFAULT_STORAGE_URI,
    McpRateLimitMiddleware,
    build_limiter,
    install_rate_limiting,
)
from ascend_python_common.readiness import (
    ProbeCallable,
    check_readiness,
    checks_body,
    is_ready,
)
from ascend_python_common.request_context import (
    CorrelationIdMiddleware,
    McpRequestLogContextMiddleware,
)
from ascend_python_common.security_headers import SecurityHeadersMiddleware
from ascend_python_common.settings import ServiceSettings
from ascend_python_common.tracing import configure_tracing, wrap_with_tracing

logger = logging.getLogger(__name__)

MCP_PATH: Final[str] = "/mcp"


class McpPathRoute(BaseRoute):
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope.get("path") in (MCP_PATH, MCP_PATH + "/"):
            return Match.FULL, scope
        return Match.NONE, {}

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    name: str
    distribution: str
    settings: ServiceSettings
    mcp: FastMCP
    routers: Sequence[APIRouter | Any] = ()
    error_registry: ErrorRegistry = field(default_factory=ErrorRegistry)
    probes: Mapping[str, ProbeCallable] = field(default_factory=dict)
    lifespan: AbstractAsyncContextManager[None] | None = None
    tool_rate_limits: dict[str, str] | None = None
    rate_limit_storage_uri: str = DEFAULT_STORAGE_URI
    startup_banner: Callable[[], list[str]] | None = None


class _CorrelatedFastAPI(FastAPI):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._tracer_provider: Any = kwargs.pop("tracer_provider", None)
        self._mcp_endpoint_path: str = kwargs.pop("mcp_endpoint_path", MCP_PATH)
        super().__init__(*args, **kwargs)

    def build_middleware_stack(self) -> ASGIApp:
        traced = wrap_with_tracing(super().build_middleware_stack(), self._tracer_provider)
        return CorrelationIdMiddleware(traced, mcp_endpoint_path=self._mcp_endpoint_path)


def create_service_app(definition: ServiceDefinition) -> FastAPI:
    configure_logging(definition.name, definition.settings)
    provider = configure_tracing(
        definition.name,
        otel_endpoint=definition.settings.OTEL_EXPORTER_OTLP_ENDPOINT,
    )
    server = definition.mcp
    server.add_middleware(McpRequestLogContextMiddleware())
    limiter = build_limiter(
        definition.settings.RATE_LIMIT_DEFAULT,
        definition.rate_limit_storage_uri,
        definition.name,
    )
    server.add_middleware(
        McpRateLimitMiddleware(
            limiter,
            definition.settings.RATE_LIMIT_DEFAULT,
            definition.tool_rate_limits,
            key_prefix=definition.name,
        )
    )
    server.add_middleware(McpRefusalMiddleware(definition.error_registry))
    mcp_asgi_app = server.http_app(path=MCP_PATH, stateless_http=True)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(mcp_asgi_app.router.lifespan_context(_app))
            if definition.lifespan is not None:
                await stack.enter_async_context(definition.lifespan)
            if definition.startup_banner is not None:
                logger.info("%s", "\n".join(definition.startup_banner()))
            yield

    version = package_version(definition.distribution)
    app = _CorrelatedFastAPI(
        title=definition.name,
        version=version,
        lifespan=lifespan,
        tracer_provider=provider,
        mcp_endpoint_path=MCP_PATH,
    )
    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts_max_age_seconds=definition.settings.SECURITY_HSTS_MAX_AGE_SECONDS,
    )
    install_rate_limiting(app, limiter)
    install_error_handlers(app, definition.error_registry)
    for router in definition.routers:
        app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": definition.name, "version": version}

    @app.get("/ready")
    async def ready() -> JSONResponse:
        results = await check_readiness(
            definition.probes,
            definition.settings.READINESS_PROBE_TIMEOUT_SECONDS,
        )
        status_code = 200 if is_ready(results) else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ready" if is_ready(results) else "not-ready",
                "service": definition.name,
                "version": version,
                "checks": checks_body(results),
            },
        )

    Instrumentator(
        should_group_status_codes=False,
        excluded_handlers=["/metrics", "/health", "/ready"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    app.router.routes.append(McpPathRoute(mcp_asgi_app))
    return app


__all__ = [
    "MCP_PATH",
    "McpPathRoute",
    "ServiceDefinition",
    "create_service_app",
]
