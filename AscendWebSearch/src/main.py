import logging
from contextlib import asynccontextmanager

# Apply compatibility patches BEFORE other heavy imports (especially crawlee)
from src.config.compat import apply_compatibility_patches

apply_compatibility_patches()

import httpx
import uvicorn
from fastapi import FastAPI

from src.api.exception_handlers import httpx_exception_handler, global_exception_handler
from src.api.mcp.mcp_server import mcp
from src.api.rest.rest_endpoints import rest_router
from src.config.blocklist_loader import BlocklistLoader
from src.config.config import settings
from src.config.logging_config import setup_logging, get_uvicorn_log_config

setup_logging()
logger = logging.getLogger("uvicorn")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    try:
        loader = BlocklistLoader()
        loader.load_rules()
    except Exception as e:
        logger.critical(f"Startup Warning: Failed to initialize Blocklist: {e}")
        # Fail hard as requested
        raise RuntimeError("Failed to initialize Blocklist") from e
    yield


app = FastAPI(title="AscendWebSearch", lifespan=lifespan)

app.add_exception_handler(httpx.HTTPError, httpx_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

app.include_router(rest_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}


# Mount must be last to avoid capturing specific routes
mcp_asgi_app = mcp.http_app()
app.mount("/", mcp_asgi_app)

if __name__ == "__main__":
    import sys
    import asyncio

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    uvicorn.run(
        "src.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        log_config=get_uvicorn_log_config()
    )
