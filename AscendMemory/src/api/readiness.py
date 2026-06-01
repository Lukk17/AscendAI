import logging
from typing import Any

import httpx
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from src.config.config import PROVIDER_CONFIGS, settings, supported_providers
from src.service.memory_client import get_memory_client

logger = logging.getLogger(__name__)

readiness_router = APIRouter(tags=["health"])

# Probe budget — every dependency probe shares the same wall-clock cap so
# /ready stays responsive when an upstream is slow.
PROBE_TIMEOUT_SECONDS = 3.0


async def _probe_qdrant() -> dict[str, str]:
    """HTTP-level reachability check against Qdrant /healthz."""

    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"http://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}/healthz"
            )
            return {"status": "ok"} if response.status_code == 200 else {"status": "error"}
    except Exception as exc:
        logger.warning("/ready: qdrant probe failed: %s", exc)

        return {"status": "error"}


async def _probe_embedding_api() -> dict[str, str]:
    """Reachability check for the default provider's embedding endpoint.
    OpenAI-compatible base URLs expose /models; LM Studio returns 200 even
    without a valid Authorization header."""

    provider = settings.MEM0_DEFAULT_PROVIDER
    if provider not in PROVIDER_CONFIGS:
        return {"status": "error"}

    cfg = PROVIDER_CONFIGS[provider]
    base_url = getattr(settings, cfg["base_url_setting"], "")
    api_key = getattr(settings, cfg["api_key_setting"], "")

    if not base_url:
        return {"status": "error"}

    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            )
            return {"status": "ok"} if response.status_code < 500 else {"status": "error"}
    except Exception as exc:
        logger.warning("/ready: embedding-api probe failed: %s", exc)

        return {"status": "error"}


def _probe_mem0_client() -> dict[str, str]:
    """Construct (or fetch cached) the default provider's mem0 client.
    Surfaces missing-API-key failures live on every /ready call so a key
    rotation breakage doesn't require a restart to detect."""

    try:
        get_memory_client()
        return {"status": "ok"}
    except Exception as exc:
        logger.warning("/ready: mem0 client probe failed: %s", exc)

        return {"status": "error"}


@readiness_router.get("/ready")
async def ready() -> JSONResponse:
    """Readiness probe. /health is liveness; this is readiness."""

    qdrant_status = await _probe_qdrant()
    embedding_status = await _probe_embedding_api()
    mem0_status = _probe_mem0_client()

    checks: dict[str, dict[str, Any]] = {
        "qdrant": qdrant_status,
        "embedding_api": embedding_status,
        "mem0_client": mem0_status,
        "providers": {"status": "ok", "supported": supported_providers()},
    }
    ok = all(c.get("status") in ("ok", "skipped") for c in checks.values())
    body = {"status": "ready" if ok else "degraded", "checks": checks}

    return JSONResponse(
        status_code=status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=body,
    )
