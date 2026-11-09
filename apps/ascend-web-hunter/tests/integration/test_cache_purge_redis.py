"""Read-cache purge subscriber against the real Redis on this computer.

A fake Redis cannot show these two behaviours: a connection the server kills
through CLIENT KILL, and a socket timeout shorter than the quiet stretch of
the channel, which once made the subscriber drop the whole cache every
10 seconds.

The tests read the address from ``REDIS_URL`` (default
``redis://127.0.0.1:6379``), switch to database 15 so they never touch other
data, use a channel and a client name of their own, and close every
connection they open.

Not part of the unit gate: excluded through `--ignore=tests/integration` in
`pyproject.toml`, run alone as `python -m pytest tests/integration -q --no-cov`.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any
from unittest.mock import patch
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
import pytest_asyncio
import redis.asyncio as async_redis

from src.config.config import settings
from src.reader.cache_purge import run_subscriber
from tests.reader.cache_purge_support import domain_key, seeded_reader, wait_until_gone

_INTEGRATION_DATABASE = 15
_SHORT_SOCKET_TIMEOUT_SECONDS = 0.2
_SILENCE_SECONDS = 1.0
_SUBSCRIBE_POLLS = 300
_SUBSCRIBE_POLL_SECONDS = 0.01

RedisFactory = Callable[..., async_redis.Redis]


def _integration_url() -> str:
    parts = urlsplit(settings.REDIS_URL)

    return urlunsplit(parts._replace(path=f"/{_INTEGRATION_DATABASE}"))


@pytest_asyncio.fixture
async def real_redis() -> AsyncIterator[RedisFactory]:
    """Open real clients on the integration database and close every one afterwards.

    The unit conftest swaps ``Redis.from_url`` for fakeredis, so each client is built from its own pool.
    """
    opened: list[async_redis.Redis] = []
    url = _integration_url()

    def open_client(**options: Any) -> async_redis.Redis:
        pool = async_redis.ConnectionPool.from_url(url, decode_responses=True, **options)
        client = async_redis.Redis.from_pool(pool)
        opened.append(client)

        return client

    yield open_client
    for client in opened:
        await client.aclose()


@pytest.fixture
def stop() -> asyncio.Event:
    return asyncio.Event()


@pytest.mark.asyncio
async def test_silence_longer_than_the_socket_timeout_keeps_the_subscription_and_the_cache(
    stop: asyncio.Event, real_redis: RedisFactory
) -> None:
    """A quiet channel is normal: no reconnect, no whole-cache drop, and a later purge still arrives."""
    # given
    client = real_redis(socket_timeout=_SHORT_SOCKET_TIMEOUT_SECONDS)
    channel = f"read_cache_purge_test_{uuid4().hex}"
    kept_key = domain_key("silence-kept.invalid", "a")
    purged_key = domain_key("silence-purged.invalid", "b")
    reader = seeded_reader({kept_key: "kept", purged_key: "purged"})
    subscriptions: list[object] = []
    real_pubsub = client.pubsub

    def counting_pubsub() -> Any:
        subscriptions.append(object())
        return real_pubsub()

    # when
    with (
        patch("src.reader.cache_purge.READ_CACHE_PURGE_CHANNEL", channel),
        patch("src.reader.cache_purge.settings.READ_CACHE_PURGE_RECONNECT_SECONDS", 0.01),
        patch.object(client, "pubsub", counting_pubsub),
    ):
        task = asyncio.create_task(run_subscriber(reader, lambda: client, stop))
        await asyncio.sleep(_SILENCE_SECONDS)
        await client.publish(channel, "silence-purged.invalid")
        await wait_until_gone(reader, purged_key)
        stop.set()
        await task

    # then
    assert len(subscriptions) == 1
    assert kept_key in reader._memory_cache
    assert purged_key not in reader._memory_cache


@pytest.mark.asyncio
async def test_killed_subscriber_connection_reconnects_and_drops_the_cache_once(
    stop: asyncio.Event, caplog: pytest.LogCaptureFixture, real_redis: RedisFactory
) -> None:
    # given
    name = f"purge-test-{uuid4().hex}"
    client = real_redis(client_name=name)
    admin = real_redis()
    channel = f"read_cache_purge_test_{uuid4().hex}"
    stale_key = domain_key("killed-stale.invalid", "a")
    reader = seeded_reader({stale_key: "stale"})
    cleared: list[int] = []
    real_clear = reader.clear_cache

    def counting_clear() -> int:
        cleared.append(1)
        return real_clear()

    # when
    with (
        patch("src.reader.cache_purge.READ_CACHE_PURGE_CHANNEL", channel),
        patch("src.reader.cache_purge.settings.READ_CACHE_PURGE_RECONNECT_SECONDS", 0.01),
        patch.object(reader, "clear_cache", counting_clear),
        caplog.at_level("WARNING", logger="src.reader.cache_purge"),
    ):
        task = asyncio.create_task(run_subscriber(reader, lambda: client, stop))
        for _ in range(_SUBSCRIBE_POLLS):
            if await admin.pubsub_numsub(channel) == [(channel, 1)]:
                break
            await asyncio.sleep(_SUBSCRIBE_POLL_SECONDS)
        for entry in await admin.client_list(_type="pubsub"):
            if entry.get("name") == name:
                await admin.client_kill_filter(_id=entry["id"])
        await wait_until_gone(reader, stale_key)
        await asyncio.sleep(_SILENCE_SECONDS)
        stop.set()
        await task

    # then
    assert cleared == [1]
    lost = [record for record in caplog.records if "connection lost" in record.message]
    assert len(lost) == 1
    assert lost[0].exc_info is not None
