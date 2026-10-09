from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import uvicorn
from ascend_python_common.app import ServiceDefinition, create_service_app

from src.adapters.download_file_manager import run_cleanup_loop
from src.api import readiness as readiness_module
from src.api.exception_handlers import error_registry
from src.api.mcp.mcp_server import mcp
from src.api.middleware.force_json_utf8 import ForceJSONUTF8Middleware
from src.api.rest.rest_endpoints import rest_router
from src.config.config import settings
from src.config.startup_banner import build_service_banner

if TYPE_CHECKING:
    from ascend_python_common.readiness import ProbeResult
    from fastapi import FastAPI

logger = logging.getLogger("ascend-audio-scribe")

# Hold strong refs to background tasks so the loop cannot GC them mid-flight.
_background_tasks: set[asyncio.Task[None]] = set()


class _CleanupLifespan:
    async def __aenter__(self) -> None:
        cleanup_stop = asyncio.Event()
        self._cleanup_stop = cleanup_stop
        cleanup_task = asyncio.create_task(run_cleanup_loop(cleanup_stop))
        self._cleanup_task = cleanup_task
        _background_tasks.add(cleanup_task)
        cleanup_task.add_done_callback(_background_tasks.discard)

    async def __aexit__(self, *exc_info: object) -> None:
        self._cleanup_stop.set()
        await asyncio.gather(self._cleanup_task, return_exceptions=True)


def service_lifespan() -> _CleanupLifespan:
    return _CleanupLifespan()


def _ffmpeg_probe() -> ProbeResult:
    return readiness_module.probe_ffmpeg()


def _tempdir_probe() -> ProbeResult:
    return readiness_module.probe_temp_dir()


def _service_definition() -> ServiceDefinition:
    return ServiceDefinition(
        name="ascend-audio-scribe",
        distribution="ascend-audio-scribe",
        settings=settings,
        mcp=mcp,
        routers=(rest_router,),
        error_registry=error_registry,
        probes={
            "ffmpeg": _ffmpeg_probe,
            "tempdir": _tempdir_probe,
        },
        lifespan=service_lifespan(),
        tool_rate_limits={
            "transcribe_local": settings.RATE_LIMIT_TRANSCRIBE,
            "transcribe_openai": settings.RATE_LIMIT_TRANSCRIBE,
            "transcribe_hf": settings.RATE_LIMIT_TRANSCRIBE,
            "transcribe_audacity": settings.RATE_LIMIT_TRANSCRIBE,
        },
        rate_limit_storage_uri=settings.REDIS_URL,
        startup_banner=build_service_banner,
    )


def create_app() -> FastAPI:
    app = create_service_app(_service_definition())
    app.add_middleware(ForceJSONUTF8Middleware)
    return app


definition = _service_definition()

app = create_service_app(definition)
app.add_middleware(ForceJSONUTF8Middleware)

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=False,
    )
