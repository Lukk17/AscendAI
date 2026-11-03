import asyncio
import logging
from typing import Any

import uvicorn
from ascend_python_common.app import ServiceDefinition, create_service_app
from ascend_python_common.errors import McpRefusalMiddleware
from ascend_python_common.rate_limit import McpRateLimitMiddleware
from fastapi import FastAPI
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor

from src.api import readiness as readiness_module
from src.api.exception_handlers import error_registry
from src.api.mcp.mcp_server import mcp
from src.api.rest.rest_endpoints import limiter, rest_router
from src.config.config import settings
from src.config.startup_banner import build_service_banner, log_startup_warnings
from src.service.job_service import job_runner, job_store
from src.service.ocr_service import (
    start_worker_pool,
    stop_worker_pool,
    wait_for_worker_replacements,
)
from src.service.result_store import result_store

logger = logging.getLogger("uvicorn")


class _ServiceLifespan:
    async def __aenter__(self) -> None:
        # The engine warms inside the OCR worker process, the one that actually serves
        # inference (see start_worker_pool). Warming a second engine here, in the main
        # process, would just hold ~316 MiB it never uses for the life of the container.
        start_worker_pool()
        # Both run before the runner takes its first document: the bucket so the banner
        # can report whether results have anywhere to go, and recovery so nothing left
        # waiting or running by the previous process is ever dispatched or polled.
        await asyncio.to_thread(result_store.ensure_bucket)
        job_store.recover_after_restart()
        AioHttpClientInstrumentor().instrument()
        await job_runner.start()
        log_startup_warnings()

    async def __aexit__(self, *exc_info: Any) -> None:
        await job_runner.stop()
        await wait_for_worker_replacements()
        stop_worker_pool()


def service_lifespan() -> _ServiceLifespan:
    return _ServiceLifespan()


def _service_definition() -> ServiceDefinition:
    return ServiceDefinition(
        name="ascend-ocr",
        distribution="ascend-ocr",
        settings=settings,
        mcp=mcp,
        routers=(rest_router,),
        error_registry=error_registry,
        probes={
            "engine": readiness_module.probe_engine,
            "worker_pool": readiness_module.probe_worker_pool,
            "jobs": readiness_module.probe_jobs,
        },
        lifespan=service_lifespan(),
        tool_rate_limits={"ocr_submit": settings.RATE_LIMIT_OCR},
        rate_limit_storage_uri=settings.REDIS_URL,
        startup_banner=build_service_banner,
    )


def create_app() -> FastAPI:
    app = create_service_app(_service_definition())
    app.state.limiter = limiter
    _share_rate_limiter_with_mcp()

    return app


def _share_rate_limiter_with_mcp() -> None:
    """Point the MCP tool limiter at the same limiter the REST decorators use.

    The factory builds its own limiter, which would give REST and MCP submissions
    separate budgets. The REST submit route shares its scope with the ocr_submit tool,
    so both draw from one budget only when both sides hit the same storage.
    """
    mcp.middleware[:] = [
        middleware for middleware in mcp.middleware if not isinstance(middleware, McpRateLimitMiddleware)
    ]
    shared = McpRateLimitMiddleware(
        limiter, settings.RATE_LIMIT_DEFAULT, {"ocr_submit": settings.RATE_LIMIT_OCR}, key_prefix="ascend-ocr"
    )
    position = next(
        (
            index
            for index, middleware in enumerate(mcp.middleware)
            if isinstance(middleware, McpRefusalMiddleware)
        ),
        len(mcp.middleware),
    )
    mcp.middleware.insert(position, shared)


definition = _service_definition()

app = create_app()

if __name__ == "__main__":
    import sys

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    uvicorn.run(
        "src.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        ws="none",
    )
