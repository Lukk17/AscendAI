import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from src.api.mcp.mcp_server import mcp
from src.api.rest.rest_endpoints import rest_router
from src.config.logging_config import setup_logging, get_uvicorn_log_config
from src.api.middleware.force_json_utf8 import ForceJSONUTF8Middleware

setup_logging()
logger = logging.getLogger("AudioScribe")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    # Explicitly run the MCP session manager as mounting doesn't always trigger sub-lifespans when main lifespan is overridden
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="AudioScribe",
    description="A dynamic speech-to-text service supporting local, OpenAI, and Hugging Face models.",
    version="0.8.0",
    lifespan=lifespan
)

app.add_middleware(ForceJSONUTF8Middleware)
app.include_router(rest_router)


@app.get("/health", summary="Health Check")
async def health_check():
    return {"status": "ok", "service": "AudioScribe"}


app.mount("/sse-root", mcp.sse_app(mount_path="/sse-root"))
app.mount("/", mcp.streamable_http_app())

if __name__ == "__main__":

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=7017,
        reload=False,
        log_config=get_uvicorn_log_config()
    )
