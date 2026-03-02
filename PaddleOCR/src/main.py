import logging
import uvicorn
from contextlib import asynccontextmanager, AsyncExitStack
from fastapi import FastAPI
from src.api.exception_handlers import register_exception_handlers
from src.api.mcp.mcp_server import mcp
from src.api.rest.rest_endpoints import rest_router
from src.config.config import settings
from src.config.logging_config import setup_logging, get_uvicorn_log_config
from src.model.ocr_models import HealthResponse
from src.service.ocr_service import ocr_service

setup_logging()
logger = logging.getLogger("uvicorn")

SERVICE_VERSION: str = "0.1.0"


def create_app() -> FastAPI:
    mcp_asgi_app = mcp.http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging()
        logger.info("Starting PaddleOCR service")
        ocr_service.warm_up_engine(settings.DEFAULT_LANGUAGE)

        async with AsyncExitStack() as stack:
            await stack.enter_async_context(mcp_asgi_app.router.lifespan_context(app))
            yield

    app = FastAPI(title="PaddleOCR", lifespan=lifespan)

    register_exception_handlers(app)
    app.include_router(rest_router)

    @app.get("/health", response_model=HealthResponse)
    def health_check() -> HealthResponse:
        return HealthResponse(status="ok", version=SERVICE_VERSION)

    app.mount("/", mcp_asgi_app)

    return app


app = create_app()

if __name__ == "__main__":
    import sys
    import asyncio

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    uvicorn.run(
        "src.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        log_config=get_uvicorn_log_config(),
    )
