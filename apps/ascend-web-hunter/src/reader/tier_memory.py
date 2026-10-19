"""Per-domain tier memory in Redis (design D3).

Key ``tier_memory:{registrable_domain}``, value the tier name that last
returned accepted content, TTL ``TIER_MEMORY_TTL_SECONDS``. A success at a
cheaper tier than the remembered one overwrites it; a dearer tier never does.
A Redis failure is logged and answered with ``None`` (get) or dropped
(record): the read climbs the full ladder instead of failing.
"""

import logging
import time

from src.config.config import settings
from src.observability.metrics import REDIS_OPS_TOTAL
from src.reader.cloudflare.cookie_manager import cookie_manager

logger = logging.getLogger(__name__)

_KEY_PREFIX = "tier_memory:"

_memory_store: dict[str, tuple[str, float]] = {}


def _key(url: str) -> str:
    return f"{_KEY_PREFIX}{cookie_manager.registrable_domain(url)}"


def _is_cheaper(candidate: str, stored: str) -> bool:
    """True when *candidate* climbs earlier in the ladder than *stored*.

    Deferred import: `web_reader` imports this module, so a top-level import
    would cycle back into it.
    """
    from src.reader.web_reader import TIER_ORDER

    order: list[str] = list(TIER_ORDER)
    try:
        return order.index(candidate) < order.index(stored)
    except ValueError:
        return False


def _memory_get(key: str) -> str | None:
    entry = _memory_store.get(key)
    if entry is None:
        return None

    tier, stored_at = entry
    if time.monotonic() - stored_at > settings.TIER_MEMORY_TTL_SECONDS:
        del _memory_store[key]

        return None

    return tier


async def get(url: str) -> str | None:
    """Return the remembered tier for the registrable domain of *url*, or None."""
    key = _key(url)
    client = cookie_manager.redis_client
    if client is None:
        return _memory_get(key)

    try:
        raw = await client.get(key)
    except Exception as exc:
        REDIS_OPS_TOTAL.labels(op="get", result="error").inc()
        logger.warning("[tier_memory] failed to load tier memory from Redis: %s", exc)

        return None

    if raw is None:
        REDIS_OPS_TOTAL.labels(op="get", result="miss").inc()

        return None

    REDIS_OPS_TOTAL.labels(op="get", result="hit").inc()
    if isinstance(raw, bytes):
        return raw.decode("utf-8")

    value: str = raw

    return value


async def record(url: str, tier: str) -> None:
    """Remember *tier* for the registrable domain of *url*, unless the stored
    tier climbs earlier in the ladder already."""
    key = _key(url)
    stored = await get(url)
    if stored is not None and not _is_cheaper(tier, stored):
        return

    client = cookie_manager.redis_client
    if client is not None:
        try:
            await client.set(key, tier, ex=settings.TIER_MEMORY_TTL_SECONDS)
            REDIS_OPS_TOTAL.labels(op="set", result="success").inc()

            return
        except Exception as exc:
            REDIS_OPS_TOTAL.labels(op="set", result="error").inc()
            logger.warning("[tier_memory] failed to save tier memory to Redis: %s", exc)

    _memory_store[key] = (tier, time.monotonic())
