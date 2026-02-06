import logging
from contextlib import asynccontextmanager, AsyncExitStack

import uvicorn
from fastapi import FastAPI

from src.api.mcp.mcp_server import mcp
from src.api.middleware.force_json_utf8 import ForceJSONUTF8Middleware
from src.api.rest.rest_endpoints import rest_router
from src.config.logging_config import setup_logging, get_uvicorn_log_config

setup_logging()
logger = logging.getLogger("AudioScribe")


def create_app() -> FastAPI:
    # Initialize MCP app locally to ensure fresh instance per app
    mcp_app = mcp.http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging()
        # Initialize MCP server lifespan
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(mcp_app.router.lifespan_context(app))
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

    # Mount MCP last to allow REST routes to take precedence
    app.mount("/", mcp_app)

    return app


# Global instance for uvicorn
app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=7017,
        reload=False,
        log_config=get_uvicorn_log_config()
    )
