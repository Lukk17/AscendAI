import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from importlib.metadata import version as get_package_version
from typing import Literal

import uvicorn
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from src.api.exception_handlers import register_exception_handlers
from src.api.mcp.mcp_server import mcp
from src.api.middleware.correlation_id import CorrelationIdMiddleware
from src.api.middleware.rate_limit import configure_rate_limiting
from src.api.middleware.security_headers import SecurityHeadersMiddleware
from src.api.rest.rest_endpoints import rest_router
from src.config.config import settings
from src.config.logging_config import get_uvicorn_log_config, setup_logging
from src.config.startup_banner import log_startup_banner
from src.model.ocr_models import HealthResponse, ReadinessResponse
from src.observability.metrics import is_engine_warm
from src.observability.tracing import configure_tracing
from src.service.ocr_service import (
    get_queue_depth,
    is_accepting_work,
    start_worker_pool,
    stop_worker_pool,
    sweep_scratch_dir,
)

logger = logging.getLogger("uvicorn")

SERVICE_VERSION: str = get_package_version("ascend-ocr")


def create_app() -> FastAPI:
    setup_logging()
    mcp_asgi_app = mcp.http_app()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info("Starting ascend-ocr service")
        # Reclaims anything a previous container process left behind: a killed worker
        # never runs its own cleanup (see sweep_scratch_dir).
        sweep_scratch_dir()
        # The engine warms inside the OCR worker process, the one that actually serves
        # inference (see start_worker_pool). Warming a second engine here, in the main
        # process, would just hold ~316 MiB it never uses for the life of the container.
        start_worker_pool()

        async with AsyncExitStack() as stack:
            stack.callback(stop_worker_pool)
            await stack.enter_async_context(mcp_asgi_app.router.lifespan_context(_app))
            log_startup_banner()

            yield

    fastapi_app = FastAPI(title="ascend-ocr", lifespan=lifespan)

    fastapi_app.add_middleware(SecurityHeadersMiddleware)
    fastapi_app.add_middleware(CorrelationIdMiddleware)

    configure_rate_limiting(fastapi_app)
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(rest_router)

    Instrumentator().instrument(fastapi_app).expose(fastapi_app, endpoint="/metrics", include_in_schema=False)

    configure_tracing(fastapi_app)

    @fastapi_app.get("/health")
    def health_check() -> HealthResponse:
        return HealthResponse(status="ok", version=SERVICE_VERSION)

    @fastapi_app.get("/ready")
    def readiness_check() -> ReadinessResponse:
        # Reads the worker process's own warm-up signal (see is_engine_warm) rather
        # than triggering one: an orchestrator polling /ready must never itself cause
        # a warm-up, or it would keep the service permanently busy.
        engine_warm = is_engine_warm(settings.DEFAULT_LANGUAGE)
        # Distinguishes busy (still ready, a queued request will be served) from
        # genuinely unable (pool unusable, a replacement or rebuild in progress, or the
        # in-flight job past its own budget and not yet reclaimed).
        accepting_work = is_accepting_work()
        status: Literal["ready", "not-ready"] = "ready" if engine_warm and accepting_work else "not-ready"

        return ReadinessResponse(
            status=status,
            version=SERVICE_VERSION,
            engine_warm=engine_warm,
            accepting_work=accepting_work,
            queue_depth=get_queue_depth(),
        )

    fastapi_app.mount("/", mcp_asgi_app)

    return fastapi_app


app = create_app()

if __name__ == "__main__":
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
