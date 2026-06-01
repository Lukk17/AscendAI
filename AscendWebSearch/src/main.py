import logging
from contextlib import AsyncExitStack, asynccontextmanager

# Apply compatibility patches BEFORE other heavy imports (especially crawlee).
# The shim must execute before `crawlee` is imported anywhere in the process,
# so the apply_compatibility_patches import lives above the rest of the imports
# by design - the E402 / I001 rules are silenced for this block in pyproject.toml.
from src.config.compat import apply_compatibility_patches

apply_compatibility_patches()

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import Response  # noqa: E402
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest  # noqa: E402

from src.api.exception_handlers import (  # noqa: E402
    global_exception_handler,
    httpx_exception_handler,
    human_intervention_exception_handler,
)
from src.api.exceptions import HumanInterventionRequiredException  # noqa: E402
from src.api.mcp.mcp_server import mcp  # noqa: E402
from src.api.mcp.mcp_server import search_client as mcp_search_client  # noqa: E402
from src.api.readiness import readiness_router  # noqa: E402
from src.api.rest.rest_endpoints import rest_router, rest_router_v2  # noqa: E402
from src.api.rest.rest_endpoints import search_client as rest_search_client  # noqa: E402
from src.config.blocklist_loader import BlocklistLoader  # noqa: E402
from src.config.config import settings  # noqa: E402
from src.config.logging_config import get_uvicorn_log_config, setup_logging  # noqa: E402
from src.config.startup_banner import log_startup_banner  # noqa: E402
from src.observability.request_context import RequestIdMiddleware  # noqa: E402
from src.runtime.browser_pool import browser_pool  # noqa: E402

setup_logging()
logger = logging.getLogger("uvicorn")


def create_app() -> FastAPI:
    mcp_asgi_app = mcp.http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        setup_logging()
        try:
            loader = BlocklistLoader()
            loader.load_rules()
        except Exception as e:
            logger.critical(f"Startup Warning: Failed to initialize Blocklist: {e}")
            raise RuntimeError("Failed to initialize Blocklist") from e

        await browser_pool.start()

        async with AsyncExitStack() as stack:
            await stack.enter_async_context(mcp_asgi_app.router.lifespan_context(app))
            await log_startup_banner()
            try:
                yield
            finally:
                await browser_pool.stop()
                try:
                    await rest_search_client.aclose()
                except Exception as e:
                    logger.warning(f"shutdown: failed to close REST SearxngClient: {e}")
                try:
                    await mcp_search_client.aclose()
                except Exception as e:
                    logger.warning(f"shutdown: failed to close MCP SearxngClient: {e}")

    app = FastAPI(title="AscendWebSearch", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)

    # Starlette's add_exception_handler signature is variant on the exception type and
    # mypy can't see that httpx.HTTPError / HumanInterventionRequiredException are
    # legal narrowings of Exception. Both handlers exist for exactly these subclasses.
    app.add_exception_handler(httpx.HTTPError, httpx_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        HumanInterventionRequiredException,
        human_intervention_exception_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(Exception, global_exception_handler)

    app.include_router(rest_router)
    app.include_router(rest_router_v2)
    app.include_router(readiness_router)

    @app.get("/health", tags=["health"])
    def health_check() -> dict[str, str]:
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
