import logging
import os
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from src.api.exception_handlers import (
    blocklist_refresh_throttled_handler,
    blocklist_validation_error_handler,
    global_exception_handler,
    httpx_exception_handler,
    human_intervention_exception_handler,
    novnc_flow_busy_exception_handler,
)
from src.api.exceptions import HumanInterventionRequiredException, NoVNCFlowBusyException
from src.api.mcp.mcp_server import mcp
from src.api.mcp.mcp_server import search_client as mcp_search_client
from src.api.readiness import readiness_router
from src.api.rest.blocklist_endpoints import blocklist_router
from src.api.rest.rest_endpoints import rest_router, rest_router_v2
from src.api.rest.rest_endpoints import search_client as rest_search_client
from src.config.blocklist_loader import (
    BlocklistRefreshThrottledError,
    BlocklistValidationError,
    blocklist_loader,
)
from src.config.config import settings
from src.config.logging_config import get_uvicorn_log_config, setup_logging
from src.config.startup_banner import log_startup_banner
from src.observability.request_context import RequestIdMiddleware
from src.runtime.browser_pool import browser_pool

setup_logging()
logger = logging.getLogger("uvicorn")


def _configure_otel() -> None:
    """Activate OTel auto-instrumentation when OTEL_EXPORTER_OTLP_ENDPOINT is set.

    A no-op when the env var is absent so local development is unaffected.
    """
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    service_name = os.getenv("OTEL_SERVICE_NAME", "ascend-web-hunter")
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor().instrument()
    logger.info("OTel tracing enabled → %s", endpoint)


def create_app() -> FastAPI:
    _configure_otel()

    mcp_asgi_app = mcp.http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        setup_logging()
        # The blocklist is already loaded by the time this runs: url_validator.py's
        # module-level singleton loads it from disk at import time, well before
        # create_app() is even called. This just confirms the invariant held and
        # fails fast if it somehow did not.
        if blocklist_loader.state is None:
            logger.critical("Startup Warning: Blocklist was not loaded")
            raise RuntimeError("Blocklist was not loaded before startup")
        rule_count = blocklist_loader.state.rule_count
        logger.info(f"Blocklist ready: {rule_count} rules from {blocklist_loader.blocklist_path}")

        await browser_pool.start()

        async with AsyncExitStack() as stack:
            await stack.enter_async_context(mcp_asgi_app.router.lifespan_context(app))
            await log_startup_banner()
            try:
                yield
            finally:
                await browser_pool.stop()
                try:
                    await rest_search_client.aclose()
                except Exception as e:
                    logger.warning(f"shutdown: failed to close REST SearxngClient: {e}")
                try:
                    await mcp_search_client.aclose()
                except Exception as e:
                    logger.warning(f"shutdown: failed to close MCP SearxngClient: {e}")

    app = FastAPI(title="ascend-web-hunter", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)

    # Starlette's add_exception_handler signature is variant on the exception type and
    # mypy can't see that httpx.HTTPError / HumanInterventionRequiredException are
    # legal narrowings of Exception. Both handlers exist for exactly these subclasses.
    app.add_exception_handler(httpx.HTTPError, httpx_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        HumanInterventionRequiredException,
        human_intervention_exception_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        NoVNCFlowBusyException,
        novnc_flow_busy_exception_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        BlocklistValidationError,
        blocklist_validation_error_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        BlocklistRefreshThrottledError,
        blocklist_refresh_throttled_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(Exception, global_exception_handler)

    app.include_router(rest_router)
    app.include_router(rest_router_v2)
    app.include_router(blocklist_router)
    app.include_router(readiness_router)

    Instrumentator(
        should_group_status_codes=False,
        excluded_handlers=["/metrics", "/health", "/ready"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    @app.get("/health", tags=["health"])
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    # Mount must be last to avoid capturing specific routes
    app.mount("/", mcp_asgi_app)

    return app


# Global instance for uvicorn
app = create_app()

if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    uvicorn.run(
        "src.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        log_config=get_uvicorn_log_config(),
    )
