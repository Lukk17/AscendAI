import logging

import httpx
from ascend_python_common.readiness import ProbeResult

from src.config.config import PROVIDER_CONFIGS, settings
from src.service.memory_client import get_memory_client

logger = logging.getLogger(__name__)


async def probe_qdrant() -> ProbeResult:
    try:
        async with httpx.AsyncClient(timeout=settings.READINESS_PROBE_TIMEOUT_SECONDS) as client:
            response = await client.get(f"http://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}/healthz")
            if response.status_code == 200:
                return ProbeResult(status="ok")
            return ProbeResult(status="error")
    except Exception as exc:
        logger.warning("/ready: qdrant probe failed: %s", exc)
        return ProbeResult(status="error")


async def probe_embedding_api() -> ProbeResult:
    provider = settings.MEM0_DEFAULT_PROVIDER
    if provider not in PROVIDER_CONFIGS:
        return ProbeResult(status="error")

    cfg = PROVIDER_CONFIGS[provider]
    base_url = getattr(settings, cfg["base_url_setting"], "")
    api_key = getattr(settings, cfg["api_key_setting"], "")

    if not base_url:
        return ProbeResult(status="error")

    try:
        async with httpx.AsyncClient(timeout=settings.READINESS_PROBE_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            )
            if response.status_code < 500:
                return ProbeResult(status="ok")
            return ProbeResult(status="error")
    except Exception as exc:
        logger.warning("/ready: embedding-api probe failed: %s", exc)
        return ProbeResult(status="error")


def probe_mem0_client() -> ProbeResult:
    try:
        get_memory_client()
        return ProbeResult(status="ok")
    except Exception as exc:
        logger.warning("/ready: mem0 client probe failed: %s", exc)
        return ProbeResult(status="error")
