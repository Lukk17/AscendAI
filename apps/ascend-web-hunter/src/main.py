import asyncio
import logging
from typing import TYPE_CHECKING

import uvicorn
from ascend_python_common.app import ServiceDefinition, create_service_app

from src.api import readiness as readiness_module
from src.api.exception_handlers import error_registry
from src.api.mcp.mcp_server import mcp
from src.api.mcp.mcp_server import search_client as mcp_search_client
from src.api.rest.blocklist_endpoints import blocklist_router
from src.api.rest.rest_endpoints import rest_router, rest_router_v2, rest_session_router
from src.api.rest.rest_endpoints import search_client as rest_search_client
from src.config.blocklist_loader import blocklist_loader
from src.config.config import settings
from src.config.startup_banner import build_service_banner
from src.reader.cache_purge import run_subscriber
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.novnc.flow_registry import novnc_flow_registry
from src.reader.web_reader import clear_all_caches, purge_domain_everywhere
from src.runtime.browser_pool import browser_pool

if TYPE_CHECKING:
    from ascend_python_common.readiness import ProbeResult
    from fastapi import FastAPI

logger = logging.getLogger("uvicorn")


async def _novnc_sweep_loop() -> None:
    """Periodically reclaim expired local flows. A failing sweep is logged
    and the loop continues: the sweeper must never raise out of itself."""
    while True:
        await asyncio.sleep(settings.NOVNC_FLOW_SWEEP_INTERVAL_SECONDS)
        try:
            await novnc_flow_registry.sweep()
        except Exception as exc:
            logger.warning("shutdown: NoVNC sweep failed: %s", exc)


class _ProcessPurgeReader:
    """PurgeReader over every live WebReader of this process (design D7)."""

    @staticmethod
    def clear_cache() -> int:
        return clear_all_caches()

    @staticmethod
    def clear_cache_for_domain(domain: str) -> int:
        return purge_domain_everywhere(domain)


class _ServiceLifespan:
    def __init__(self) -> None:
        self._novnc_sweeper: asyncio.Task[None] | None = None
        self._purge_subscriber: asyncio.Task[None] | None = None
        self._purge_stop = asyncio.Event()

    async def __aenter__(self) -> None:
        if blocklist_loader.state is None:
            logger.critical("Startup Warning: Blocklist was not loaded")
            raise RuntimeError("Blocklist was not loaded before startup")
        rule_count = blocklist_loader.state.rule_count
        logger.info("Blocklist ready: %s rules from %s", rule_count, blocklist_loader.blocklist_path)
        await browser_pool.start()
        self._novnc_sweeper = asyncio.create_task(_novnc_sweep_loop())
        self._purge_stop = asyncio.Event()
        self._purge_subscriber = asyncio.create_task(
            run_subscriber(
                _ProcessPurgeReader(),
                lambda: cookie_manager.redis_client,
                self._purge_stop,
            )
        )

    async def __aexit__(self, *exc_info: object) -> None:
        if self._purge_subscriber is not None:
            self._purge_stop.set()
            self._purge_subscriber.cancel()
            await asyncio.gather(self._purge_subscriber, return_exceptions=True)
            self._purge_subscriber = None
        if self._novnc_sweeper is not None:
            self._novnc_sweeper.cancel()
            await asyncio.gather(self._novnc_sweeper, return_exceptions=True)
            self._novnc_sweeper = None
        try:
            await novnc_flow_registry.shutdown()
        except Exception as exc:
            logger.warning("shutdown: failed to stop NoVNC flows: %s", exc)
        try:
            await browser_pool.stop()
        except Exception as exc:
            logger.warning("shutdown: failed to stop browser pool: %s", exc)
        try:
            await rest_search_client.aclose()
        except Exception as exc:
            logger.warning("shutdown: failed to close REST SearxngClient: %s", exc)
        try:
            await mcp_search_client.aclose()
        except Exception as exc:
            logger.warning("shutdown: failed to close MCP SearxngClient: %s", exc)


def service_lifespan() -> _ServiceLifespan:
    return _ServiceLifespan()


async def _redis_probe() -> "ProbeResult":
    return await readiness_module.probe_redis()


async def _searxng_probe() -> "ProbeResult":
    return await readiness_module.probe_searxng()


def _searxng_breaker_probe() -> "ProbeResult":
    return readiness_module.probe_searxng_breaker()


async def _flaresolverr_probe() -> "ProbeResult":
    return await readiness_module.probe_flaresolverr()


def _flaresolverr_breaker_probe() -> "ProbeResult":
    return readiness_module.probe_flaresolverr_breaker()


def _service_definition() -> ServiceDefinition:
    return ServiceDefinition(
        name="ascend-web-hunter",
        distribution="ascend-web-hunter",
        settings=settings,
        mcp=mcp,
        routers=(rest_router, rest_router_v2, rest_session_router, blocklist_router),
        error_registry=error_registry,
        probes={
            "redis": _redis_probe,
            "searxng": _searxng_probe,
            "searxng_breaker": _searxng_breaker_probe,
            "flaresolverr": _flaresolverr_probe,
            "flaresolverr_breaker": _flaresolverr_breaker_probe,
        },
        lifespan=service_lifespan(),
        startup_banner=build_service_banner,
        rate_limit_storage_uri=settings.REDIS_URL,
    )


def create_app() -> "FastAPI":
    return create_service_app(_service_definition())


definition = _service_definition()

app = create_service_app(definition)

if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    uvicorn.run(
        "src.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
    )
