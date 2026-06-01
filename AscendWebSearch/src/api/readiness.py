import contextlib
import logging

import httpx
import redis.asyncio as redis
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from src.config.config import settings

logger = logging.getLogger(__name__)

readiness_router = APIRouter(tags=["health"])

# Probe budget: every dependency probe shares the same 3-second wall clock.
# The /ready endpoint itself should return within a few seconds for k8s
# probe configurations that expect sub-10s timeouts.
PROBE_TIMEOUT_SECONDS = 3.0


async def _probe_redis() -> dict[str, str]:
    if not settings.REDIS_URL:
        return {"status": "skipped"}

    client = redis.from_url(settings.REDIS_URL, decode_responses=True)

    try:
        await client.ping()

        return {"status": "ok"}
    except Exception as exc:
        # Log the full exception (includes the DSN, credentials) server-side; never echo
        # it to an unauthenticated /ready caller. Returning only "error" prevents the
        # endpoint from being used as a recon primitive.
        logger.warning("/ready: redis probe failed: %s", exc)

        return {"status": "error"}
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()


async def _probe_searxng() -> dict[str, str]:
    """SearXNG's root may return 200 even when search is broken. Hit /search with a
    cheap query and require 200 to count as ready."""
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{settings.SEARXNG_BASE_URL.rstrip('/')}/search",
                params={"q": "ping", "format": "html"},
            )

            return {"status": "ok"} if response.status_code == 200 else {"status": "error"}
    except Exception as exc:
        logger.warning("/ready: searxng probe failed: %s", exc)

        return {"status": "error"}


async def _probe_flaresolverr() -> dict[str, str]:
    """FlareSolverr only accepts POST. A GET against /v1 returns 405, which the original
    'status<500' probe treated as ready. Use POST sessions.list for a real signal."""
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
            response = await client.post(
                settings.FLARESOLVERR_URL,
                json={"cmd": "sessions.list"},
            )

            return {"status": "ok"} if response.status_code == 200 else {"status": "error"}
    except Exception as exc:
        logger.warning("/ready: flaresolverr probe failed: %s", exc)

        return {"status": "error"}


@readiness_router.get("/ready")
async def ready() -> JSONResponse:
    """Readiness probe. /health is liveness; this is readiness."""
    checks = {
        "redis": await _probe_redis(),
        "searxng": await _probe_searxng(),
        "flaresolverr": await _probe_flaresolverr(),
    }
    ok = all(c.get("status") in ("ok", "skipped") for c in checks.values())
    body = {"status": "ready" if ok else "degraded", "checks": checks}

    return JSONResponse(
        status_code=status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=body,
    )
