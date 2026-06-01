import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

import uvicorn
from fastapi import FastAPI, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src.api.exception_handlers import global_exception_handler, value_error_handler
from src.api.mcp.mcp_server import mcp
from src.api.readiness import readiness_router
from src.api.rest.rest_endpoints import rest_router
from src.config.config import settings
from src.config.logging_config import get_uvicorn_log_config, setup_logging
from src.config.startup_banner import log_startup_banner
from src.observability.request_context import RequestIdMiddleware
from src.service.memory_client import get_memory_client

setup_logging()
logger = logging.getLogger("uvicorn")

is_ready = False

# Hold a strong reference to the background warmup task so the asyncio event
# loop (which only keeps weak references to tasks) cannot GC it before
# completion.
_background_tasks: set[asyncio.Task[None]] = set()

WARMUP_RETRY_DELAY_SECONDS = 5
WARMUP_MAX_ATTEMPTS = 60  # 60 * 5s = 5 minutes of cold-boot tolerance


async def warmup_client() -> None:
    """Background task to initialize the heavy memory client.

    Retries with a fixed backoff so a transient cold-boot failure (e.g.
    Qdrant not yet reachable on the docker network) does not leave /health
    stuck at 503 forever. The flag flips to True on the first successful
    probe and stays True.
    """

    global is_ready  # noqa: PLW0603 — module-level flag inspected by /health/legacy
    logger.info(
        "Starting background warmup of AscendMemoryClient... "
        "Wait for 'Background warmup complete' before sending requests."
    )
    for attempt in range(1, WARMUP_MAX_ATTEMPTS + 1):  # pragma: no branch — loop always returns inside
        try:
            client = get_memory_client()
            logger.info(f"Performing active connection check (attempt {attempt}/{WARMUP_MAX_ATTEMPTS})...")
            # Note: search now uses mem0 2.x signature (top_k, filters).
            # Calling through AscendMemoryClient.search keeps that detail
            # hidden from the warmup logic.
            client.search(query="startup_warmup", user_id="system_warmup")
            is_ready = True
            logger.info("Background warmup complete. AscendMemoryClient is ready.")
            return
        except Exception as e:
            if attempt >= WARMUP_MAX_ATTEMPTS:
                logger.exception(
                    f"Background warmup failed after {WARMUP_MAX_ATTEMPTS} attempts; "
                    "/health/legacy will stay 503 until a manual restart."
                )
                return
            logger.warning(
                f"Warmup attempt {attempt}/{WARMUP_MAX_ATTEMPTS} failed ({e}); "
                f"retrying in {WARMUP_RETRY_DELAY_SECONDS}s"
            )

            await asyncio.sleep(WARMUP_RETRY_DELAY_SECONDS)


def create_app() -> FastAPI:
    mcp_asgi_app = mcp.http_app()

    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI) -> AsyncIterator[None]:
        # setup_logging already ran at module import; the duplicate call in
        # the old lifespan was redundant. Drop it.
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(mcp_asgi_app.router.lifespan_context(fastapi_app))
            # Start the warmup task AFTER the MCP lifespan has entered so
            # that any MCP-driven settings hooks are visible.
            warmup_task = asyncio.create_task(warmup_client())
            _background_tasks.add(warmup_task)
            warmup_task.add_done_callback(_background_tasks.discard)

            await log_startup_banner()
            yield

    app = FastAPI(title="AscendMemory", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)

    app.add_exception_handler(ValueError, value_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, global_exception_handler)

    app.include_router(rest_router)
    app.include_router(readiness_router)

    @app.get("/health", tags=["health"])
    def health_check() -> dict[str, str]:
        """Liveness probe. Always returns 200 when the process is alive so
        Kubernetes / Docker do not restart the container during the
        Qdrant warmup window. Readiness (`is_ready`) is reported on
        /ready, not here."""

        return {"status": "ok"}

    @app.get("/health/legacy", tags=["health"])
    def legacy_health_check(response: Response) -> dict[str, str]:
        """Backwards-compatible combined liveness+readiness response for
        callers still on the old contract (returns 503 until warmup
        completes). New callers should switch to /health + /ready."""

        if not is_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "starting", "detail": "Memory client initializing"}

        return {"status": "ok"}

    @app.get("/metrics", tags=["observability"])
    def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # Mount must be last to avoid capturing specific routes
    app.mount("/", mcp_asgi_app)

    return app


# Global instance for uvicorn
app = create_app()

if __name__ == "__main__":  # pragma: no cover
    uvicorn.run(
        "src.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        log_config=get_uvicorn_log_config(),
    )
