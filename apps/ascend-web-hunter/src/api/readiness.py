import contextlib
import logging

import httpx
import redis.asyncio as redis
from ascend_python_common.readiness import ProbeResult

from src.circuit_breaker.breaker import BreakerState, flaresolverr_breaker, searxng_breaker
from src.config.config import settings

logger = logging.getLogger(__name__)


async def probe_redis() -> ProbeResult:
    if not settings.REDIS_URL:
        return ProbeResult(status="skipped")
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await client.ping()
        return ProbeResult(status="ok")
    except Exception as exc:
        logger.warning("/ready: redis probe failed: %s", exc)
        return ProbeResult(status="error")
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()


async def probe_searxng() -> ProbeResult:
    try:
        async with httpx.AsyncClient(timeout=settings.READINESS_PROBE_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{settings.SEARXNG_BASE_URL.rstrip('/')}/search",
                params={"q": "ping", "format": "html"},
            )
            return ProbeResult(status="ok") if response.status_code == 200 else ProbeResult(status="error")
    except Exception as exc:
        logger.warning("/ready: searxng probe failed: %s", exc)
        return ProbeResult(status="error")


async def probe_flaresolverr() -> ProbeResult:
    try:
        async with httpx.AsyncClient(timeout=settings.READINESS_PROBE_TIMEOUT_SECONDS) as client:
            response = await client.post(
                settings.FLARESOLVERR_URL,
                json={"cmd": "sessions.list"},
            )
            return ProbeResult(status="ok") if response.status_code == 200 else ProbeResult(status="error")
    except Exception as exc:
        logger.warning("/ready: flaresolverr probe failed: %s", exc)
        return ProbeResult(status="error")


def _breaker_result(breaker_state: BreakerState) -> ProbeResult:
    if breaker_state is BreakerState.OPEN:
        return ProbeResult(status="degraded", details={"breaker": "open"})
    if breaker_state is BreakerState.HALF_OPEN:
        return ProbeResult(status="degraded", details={"breaker": "half_open"})
    return ProbeResult(status="ok", details={"breaker": "closed"})


def probe_searxng_breaker() -> ProbeResult:
    return _breaker_result(searxng_breaker.state)


def probe_flaresolverr_breaker() -> ProbeResult:
    return _breaker_result(flaresolverr_breaker.state)
