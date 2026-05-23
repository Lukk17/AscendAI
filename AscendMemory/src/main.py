import asyncio
import logging
from contextlib import asynccontextmanager, AsyncExitStack

import uvicorn
from fastapi import FastAPI, Response, status, Request

from src.api.mcp.mcp_server import mcp
from src.api.rest.rest_endpoints import rest_router
from src.config.config import settings
from src.config.logging_config import setup_logging, get_uvicorn_log_config
from src.config.startup_banner import log_startup_banner
from src.service.memory_client import get_memory_client

setup_logging()
logger = logging.getLogger("uvicorn")

is_ready = False

# Hold a strong reference to the background warmup task so the asyncio event loop
# (which only keeps weak references to tasks) cannot GC it before completion.
_background_tasks: set[asyncio.Task] = set()

WARMUP_RETRY_DELAY_SECONDS = 5
WARMUP_MAX_ATTEMPTS = 60  # 60 * 5s = 5 minutes of cold-boot tolerance


async def warmup_client():
    """Background task to initialize the heavy memory client.

    Retries with a fixed backoff so a transient cold-boot failure (e.g. Qdrant
    not yet reachable on the docker network) does not leave /health stuck at 503
    forever. The flag flips to True on the first successful probe and stays True.
    """
    global is_ready
    logger.info(
        "Starting background warmup of AscendMemoryClient... Please wait for 'Background warmup complete' before sending requests.")
    for attempt in range(1, WARMUP_MAX_ATTEMPTS + 1):
        try:
            client = get_memory_client()
            logger.info(f"Performing active connection check (attempt {attempt}/{WARMUP_MAX_ATTEMPTS})...")
            client.search(query="startup_warmup", user_id="system_warmup")
            is_ready = True
            logger.info("Background warmup complete. AscendMemoryClient is ready.")
            return
        except Exception as e:
            if attempt >= WARMUP_MAX_ATTEMPTS:
                logger.error(
                    f"Background warmup failed after {WARMUP_MAX_ATTEMPTS} attempts; /health will stay 503 until "
                    f"a manual restart. Last error: {e}")
                return
            logger.warning(
                f"Warmup attempt {attempt}/{WARMUP_MAX_ATTEMPTS} failed ({e}); retrying in "
                f"{WARMUP_RETRY_DELAY_SECONDS}s")
            await asyncio.sleep(WARMUP_RETRY_DELAY_SECONDS)


def create_app() -> FastAPI:
    mcp_asgi_app = mcp.http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging()
        warmup_task = asyncio.create_task(warmup_client())
        _background_tasks.add(warmup_task)
        warmup_task.add_done_callback(_background_tasks.discard)

        # Initialize MCP server lifespan
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(mcp_asgi_app.router.lifespan_context(app))
            await log_startup_banner()
            yield

    app = FastAPI(title="AscendMemory", lifespan=lifespan)
    app.include_router(rest_router)

    @app.middleware("http")
    async def log_request_receipt(request: Request, call_next):
        path = request.url.path
        if path != "/health":
            logger.info(f"Received Request: {request.method} {path}")
        response = await call_next(request)
        return response

    @app.get("/health")
    def health_check(response: Response):
        if not is_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "starting", "detail": "Memory client initializing"}
        return {"status": "ok"}

    # Mount must be last to avoid capturing specific routes
    app.mount("/", mcp_asgi_app)
    
    return app


# Global instance for uvicorn
app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        log_config=get_uvicorn_log_config()
    )
