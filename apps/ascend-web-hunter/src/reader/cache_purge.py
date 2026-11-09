"""Cross-container read-cache purge over Redis pub/sub.

The read cache stays in each process. When a session clear purges one
domain, the clearing container purges its own cache and publishes the
registrable domain on the ``read_cache_purge`` channel. Every container runs
one subscriber task (started and cancelled by the lifespan in ``src/main.py``)
that drops that domain's cached entries when a message arrives. A quiet
channel is normal and never counts as a lost connection. Redis keeps
no message for a subscriber that is not connected, so after the subscriber
reconnects it drops its whole read cache once. It waits
``READ_CACHE_PURGE_RECONNECT_SECONDS`` between two connection attempts. A
Redis error is logged once as a WARNING and never fails the clear.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any, Protocol

from src.config.config import settings
from src.reader.cloudflare.cookie_manager import cookie_manager

logger = logging.getLogger(__name__)

READ_CACHE_PURGE_CHANNEL = "read_cache_purge"

_MESSAGE_WAIT_SECONDS = 1.0

ClientFactory = Callable[[], Any | None]


class PurgeReader(Protocol):
    """The two cache drops one subscriber needs from its container's reader."""

    def clear_cache(self) -> int: ...
    def clear_cache_for_domain(self, domain: str) -> int: ...


async def publish_purge(domain: str) -> bool:
    """Publish one domain purge, never raising."""
    client = cookie_manager.redis_client
    if client is None:
        return False
    try:
        await client.publish(READ_CACHE_PURGE_CHANNEL, domain)
    except Exception:
        logger.warning("read_cache_purge: publish failed for %s", domain)

        return False

    return True


def _message_domain(message: Any) -> str | None:
    if not isinstance(message, dict):
        return None
    if message.get("type") != "message":
        return None
    domain = message.get("data")
    if isinstance(domain, bytes):
        try:
            return domain.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(domain, str):
        return domain

    return None


async def _wait_reconnect(stop: asyncio.Event) -> None:
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=settings.READ_CACHE_PURGE_RECONNECT_SECONDS)


async def _unsubscribe(pubsub: Any) -> None:
    try:
        await pubsub.unsubscribe(READ_CACHE_PURGE_CHANNEL)
    except Exception:
        logger.warning("read_cache_purge: unsubscribe failed")


async def _close(pubsub: Any) -> None:
    aclose = getattr(pubsub, "aclose", None)
    if aclose is None:
        return
    try:
        await aclose()
    except Exception:
        logger.warning("read_cache_purge: close failed")


async def run_subscriber(
    reader: PurgeReader,
    get_client: ClientFactory,
    stop: asyncio.Event,
) -> None:
    """Drop purged domains until *stop* is set, surviving reconnects."""
    first_connection = True
    while not stop.is_set():
        client = get_client()
        if client is None:
            await _wait_reconnect(stop)
            continue
        try:
            pubsub = client.pubsub()
        except Exception:
            logger.warning("read_cache_purge: subscribe failed, retrying")
            await _wait_reconnect(stop)
            continue
        try:
            await pubsub.subscribe(READ_CACHE_PURGE_CHANNEL)
        except Exception:
            logger.warning("read_cache_purge: subscribe failed, retrying")
            await _close(pubsub)
            await _wait_reconnect(stop)
            continue
        if not first_connection:
            reader.clear_cache()
        first_connection = False
        try:
            while not stop.is_set():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=_MESSAGE_WAIT_SECONDS
                )
                domain = _message_domain(message)
                if domain is not None:
                    reader.clear_cache_for_domain(domain)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("read_cache_purge: connection lost, retrying", exc_info=True)
        finally:
            await _unsubscribe(pubsub)
            await _close(pubsub)
        await _wait_reconnect(stop)
