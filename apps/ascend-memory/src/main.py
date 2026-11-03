import asyncio
import logging

import uvicorn
from ascend_python_common.app import ServiceDefinition, create_service_app
from ascend_python_common.readiness import ProbeResult
from fastapi import APIRouter, FastAPI, Response, status

from src.api import readiness as readiness_module
from src.api.exception_handlers import error_registry
from src.api.mcp.mcp_server import mcp
from src.api.rest.rest_endpoints import rest_router
from src.config.config import settings
from src.config.startup_banner import build_service_banner
from src.service.memory_client import get_memory_client

logger = logging.getLogger("uvicorn")

is_ready = False

_background_tasks: set[asyncio.Task[None]] = set()

WARMUP_RETRY_DELAY_SECONDS = 5
WARMUP_MAX_ATTEMPTS = 60

legacy_router = APIRouter(tags=["health"])


async def warmup_client() -> None:
    global is_ready  # noqa: PLW0603 - module-level flag inspected by /health/legacy
    logger.info(
        "Starting background warmup of AscendMemoryClient... "
        "Wait for 'Background warmup complete' before sending requests."
    )
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


class _WarmupLifespan:
    async def __aenter__(self) -> None:
        warmup_task = asyncio.create_task(warmup_client())
        _background_tasks.add(warmup_task)
        warmup_task.add_done_callback(_background_tasks.discard)

    async def __aexit__(self, *exc_info: object) -> None:
        return None


def service_lifespan() -> _WarmupLifespan:
    return _WarmupLifespan()


@legacy_router.get("/health/legacy")
def legacy_health_check(response: Response) -> dict[str, str]:
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "starting", "detail": "Memory client initializing"}

    return {"status": "ok"}


async def _qdrant_probe() -> ProbeResult:
    return await readiness_module.probe_qdrant()


async def _embedding_probe() -> ProbeResult:
    return await readiness_module.probe_embedding_api()


def _mem0_probe() -> ProbeResult:
    return readiness_module.probe_mem0_client()


def _service_definition() -> ServiceDefinition:
    return ServiceDefinition(
        name="ascend-memory",
        distribution="ascend-memory",
        settings=settings,
        mcp=mcp,
        routers=(rest_router, legacy_router),
        error_registry=error_registry,
        probes={
            "qdrant": _qdrant_probe,
            "embedding_api": _embedding_probe,
            "mem0_client": _mem0_probe,
        },
        lifespan=service_lifespan(),
        rate_limit_storage_uri=settings.REDIS_URL,
        startup_banner=build_service_banner,
    )


def create_app() -> FastAPI:
    return create_service_app(definition)


definition = _service_definition()

app = create_app()

if __name__ == "__main__":  # pragma: no cover
    uvicorn.run(
        "src.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
    )
