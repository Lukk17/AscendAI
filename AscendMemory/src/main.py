import asyncio
import logging
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, status, Request

from src.api.mcp.mcp_server import mcp
from src.api.rest.rest_endpoints import rest_router
from src.config.config import settings
from src.service.memory_client import get_memory_client

# Configure logging
LOG_FORMAT = "[%(asctime)s] %(levelname)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format=LOG_FORMAT,
    datefmt=DATE_FORMAT
)

# Unify Uvicorn loggers to specific format
for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
    log = logging.getLogger(logger_name)
    log.setLevel(settings.LOG_LEVEL)
    for handler in log.handlers:
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

logger = logging.getLogger("uvicorn")

# Flag to track readiness
is_ready = False

async def warmup_client():
    """Background task to initialize the heavy memory client."""
    global is_ready
    logger.info("Starting background warmup of AscendMemoryClient... Please wait for 'Background warmup complete' before sending requests.")
    try:
        # Force initialization
        client = get_memory_client()
        # Perform a dummy search to force connection to Qdrant and Embedder
        logger.info("Performing active connection check (Dummy Search)...")
        client.search(query="startup_warmup", user_id="system_warmup")
        is_ready = True
        logger.info("Background warmup complete. AscendMemoryClient is ready.")
    except Exception as e:
        logger.error(f"Background warmup failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start warmup in background
    asyncio.create_task(warmup_client())
    yield


mcp_asgi_app = mcp.http_app()

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


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT
    )
