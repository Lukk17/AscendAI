from __future__ import annotations

import asyncio
import logging
import os
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from src.adapters.download_file_manager import run_cleanup_loop
from src.api.exception_handlers import (
    FileSizeExceededError,
    file_size_error_handler,
    global_exception_handler,
    value_error_handler,
)
from src.api.mcp.mcp_server import mcp
from src.api.middleware.force_json_utf8 import ForceJSONUTF8Middleware
from src.api.readiness import readiness_router
from src.api.rest.rest_endpoints import rest_router
from src.config.config import settings
from src.config.logging_config import get_uvicorn_log_config, setup_logging
from src.config.startup_banner import log_startup_banner
from src.observability.request_context import RequestIdMiddleware

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

setup_logging()
logger = logging.getLogger("ascend-audio-scribe")


def _configure_otel() -> None:
    """Activate OTel auto-instrumentation when OTEL_EXPORTER_OTLP_ENDPOINT is set.

    Uses the SDK directly so uvicorn does not need to be launched under
    `opentelemetry-instrument`, and is a strict no-op when the env var is absent.
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

    service_name = os.getenv("OTEL_SERVICE_NAME", "ascend-audio-scribe")
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor().instrument()
    logger.info("[AscendAudioScribe] OTel tracing enabled → %s", endpoint)


# Hold strong refs to background tasks so the loop cannot GC them mid-flight.
_background_tasks: set[asyncio.Task[None]] = set()


def create_app() -> FastAPI:
    _configure_otel()

    mcp_app = mcp.http_app()

    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI) -> AsyncGenerator[None, None]:
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(mcp_app.router.lifespan_context(fastapi_app))

            cleanup_stop = asyncio.Event()
            cleanup_task = asyncio.create_task(run_cleanup_loop(cleanup_stop))
            _background_tasks.add(cleanup_task)
            cleanup_task.add_done_callback(_background_tasks.discard)

            await log_startup_banner()
            try:
                yield
            finally:
                cleanup_stop.set()
                await asyncio.gather(cleanup_task, return_exceptions=True)

    app = FastAPI(
        title="ascend-audio-scribe",
        description="A dynamic speech-to-text service supporting local, OpenAI, and Hugging Face models.",
        version="0.9.0",
        lifespan=lifespan,
    )

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(ForceJSONUTF8Middleware)

    app.add_exception_handler(FileSizeExceededError, file_size_error_handler)
    app.add_exception_handler(ValueError, value_error_handler)
    app.add_exception_handler(Exception, global_exception_handler)

    app.include_router(rest_router)
    app.include_router(readiness_router)

    Instrumentator(
        should_group_status_codes=False,
        excluded_handlers=["/metrics", "/health", "/ready"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    @app.get("/health", tags=["health"])
    def health_check() -> dict[str, str]:
        """Liveness probe. Always 200 once uvicorn binds; readiness is on /ready."""

        return {"status": "ok", "service": "ascend-audio-scribe"}

    # MCP mount must be last so REST routes win.
    app.mount("/", mcp_app)

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=settings.MCP_HOST,
        port=settings.MCP_PORT,
        reload=False,
        log_config=get_uvicorn_log_config(),
    )
