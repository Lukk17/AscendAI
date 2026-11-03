"""Task 5.5: the read-cache purge reaches every container over Redis pub/sub."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest

from src.reader.cache_purge import (
    _message_domain,
    publish_purge,
    run_subscriber,
)
from src.reader.web_reader import WebReader


class _FakePubSub:
    def __init__(self, owner: "_FakeRedis") -> None:
        self.owner = owner
        self.queue: list[Any] = []
        self.subscribed = False
        owner.subscribers.append(self)

    async def subscribe(self, _channel: str) -> None:
        if self.owner.fail_subscribe:
            self.owner.fail_subscribe = False
            raise ConnectionError("subscribe blew up")
        self.subscribed = True

    async def unsubscribe(self, _channel: str) -> None:
        if self.owner.fail_unsubscribe:
            raise ConnectionError("unsubscribe blew up")

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        while not self.owner.stop.is_set():
            if self.queue:
                yield {"type": "message", "channel": "read_cache_purge", "data": self.queue.pop(0)}
            elif self.owner.explode_listen:
                self.owner.explode_listen = False
                raise ConnectionError("connection lost")
            else:
                await asyncio.sleep(0.01)


class _FakeRedis:
    def __init__(self, stop: asyncio.Event, fail_publish: bool = False) -> None:
        self.stop = stop
        self.subscribers: list[_FakePubSub] = []
        self.published: list[tuple[str, str]] = []
        self.fail_publish = fail_publish
        self.fail_subscribe = False
        self.fail_unsubscribe = False
        self.fail_close = False
        self.explode_listen = False

    async def publish(self, channel: str, message: str) -> int:
        if self.fail_publish:
            raise ConnectionError("publish blew up")
        self.published.append((channel, message))
        for subscriber in self.subscribers:
            subscriber.queue.append(message)
        return len(self.subscribers)

    def pubsub(self) -> _FakePubSub:
        return _FakePubSub(self)


class _ClosingFakePubSub(_FakePubSub):
    def __init__(self, owner: "_FakeRedis") -> None:
        super().__init__(owner)
        self.closed = False

    async def aclose(self) -> None:
        if self.owner.fail_close:
            raise ConnectionError("close blew up")
        self.closed = True


class _ClosingFakeRedis(_FakeRedis):
    def pubsub(self) -> _ClosingFakePubSub:
        return _ClosingFakePubSub(self)


class _PubsubRaisesRedis(_FakeRedis):
    def __init__(self, stop: asyncio.Event) -> None:
        super().__init__(stop)
        self.pubsub_calls = 0

    def pubsub(self) -> _FakePubSub:
        self.pubsub_calls += 1
        if self.pubsub_calls == 1:
            raise ConnectionError("pubsub blew up")
        return super().pubsub()


@pytest.fixture
def stop() -> asyncio.Event:
    return asyncio.Event()


def _seeded_reader(entries: dict[str, str]) -> WebReader:
    reader = WebReader()
    for key, content in entries.items():
        reader._memory_cache[key] = ({"content": content, "status": "success", "mode": "t"}, 9999999999.0)
    return reader


def _domain_key(domain: str, path: str) -> str:
    return f"https://{domain}/{path}|heavy=False|links=False|profile=|fmt=text|tier=|schema="


@pytest.mark.asyncio
async def test_clear_through_first_reader_drops_second_reader_entry(stop: asyncio.Event) -> None:
    # given
    fake = _FakeRedis(stop)
    first = _seeded_reader({_domain_key("example.com", "a"): "first"})
    second = _seeded_reader({_domain_key("example.com", "b"): "second"})
    first_task = asyncio.create_task(run_subscriber(first, lambda: fake, stop))
    second_task = asyncio.create_task(run_subscriber(second, lambda: fake, stop))
    await asyncio.sleep(0.05)

    # when
    dropped = first.clear_cache_for_domain("example.com")
    await fake.publish("read_cache_purge", "example.com")
    await asyncio.sleep(0.1)
    stop.set()
    await asyncio.gather(first_task, second_task)

    # then
    assert dropped == 1
    assert first._memory_cache == {}
    assert second._memory_cache == {}


@pytest.mark.asyncio
async def test_count_returned_is_the_first_reader_own(stop: asyncio.Event) -> None:
    # given
    fake = _FakeRedis(stop)
    first = _seeded_reader({_domain_key("example.com", "a"): "first"})
    second = _seeded_reader({_domain_key("other.com", "b"): "second"})
    second_task = asyncio.create_task(run_subscriber(second, lambda: fake, stop))
    await asyncio.sleep(0.05)

    # when
    dropped = first.clear_cache_for_domain("example.com")
    await fake.publish("read_cache_purge", "example.com")
    await asyncio.sleep(0.1)
    stop.set()
    await second_task

    # then
    assert dropped == 1
    assert second._memory_cache != {}


@pytest.mark.asyncio
async def test_subscriber_drops_whole_cache_once_after_reconnect(stop: asyncio.Event) -> None:
    # given
    fake = _FakeRedis(stop)
    reader = _seeded_reader(
        {_domain_key("example.com", "a"): "stale", _domain_key("other.com", "b"): "fresh"}
    )
    fake.explode_listen = True
    task = asyncio.create_task(run_subscriber(reader, lambda: fake, stop))

    # when
    with patch("src.reader.cache_purge.settings.READ_CACHE_PURGE_RECONNECT_SECONDS", 0.01):
        await asyncio.sleep(0.15)
        stop.set()
        await task

    # then
    assert reader._memory_cache == {}


@pytest.mark.asyncio
async def test_subscribe_failure_warns_and_retries(
    stop: asyncio.Event, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    fake = _FakeRedis(stop)
    fake.fail_subscribe = True
    reader = _seeded_reader({})

    # when
    with (
        patch("src.reader.cache_purge.settings.READ_CACHE_PURGE_RECONNECT_SECONDS", 0.01),
        caplog.at_level("WARNING"),
    ):
        task = asyncio.create_task(run_subscriber(reader, lambda: fake, stop))
        await asyncio.sleep(0.1)
        stop.set()
        await task

    # then
    assert any("subscribe failed" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_missing_client_waits_for_reconnect(stop: asyncio.Event) -> None:
    # given
    reader = _seeded_reader({})
    calls = {"count": 0}

    def missing() -> None:
        calls["count"] += 1
        return

    # when
    with patch("src.reader.cache_purge.settings.READ_CACHE_PURGE_RECONNECT_SECONDS", 0.01):
        task = asyncio.create_task(run_subscriber(reader, missing, stop))
        await asyncio.sleep(0.05)
        stop.set()
        await task

    # then
    assert calls["count"] >= 1


@pytest.mark.asyncio
async def test_publish_without_client_is_false() -> None:
    # when
    with patch("src.reader.cache_purge.cookie_manager.redis_client", None):
        published = await publish_purge("example.com")

    # then
    assert published is False


@pytest.mark.asyncio
async def test_publish_error_warns_and_is_false(
    stop: asyncio.Event, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    fake = _FakeRedis(stop, fail_publish=True)

    # when
    with patch("src.reader.cache_purge.cookie_manager.redis_client", fake), caplog.at_level("WARNING"):
        published = await publish_purge("example.com")

    # then
    assert published is False
    assert any("publish failed" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_publish_ok_is_true(stop: asyncio.Event) -> None:
    # given
    fake = _FakeRedis(stop)

    # when
    with patch("src.reader.cache_purge.cookie_manager.redis_client", fake):
        published = await publish_purge("example.com")

    # then
    assert published is True
    assert fake.published == [("read_cache_purge", "example.com")]


@pytest.mark.asyncio
async def test_unsubscribe_failure_warns(stop: asyncio.Event, caplog: pytest.LogCaptureFixture) -> None:
    # given
    fake = _FakeRedis(stop)
    fake.fail_unsubscribe = True
    reader = _seeded_reader({})

    # when
    with (
        patch("src.reader.cache_purge.settings.READ_CACHE_PURGE_RECONNECT_SECONDS", 0.01),
        caplog.at_level("WARNING"),
    ):
        task = asyncio.create_task(run_subscriber(reader, lambda: fake, stop))
        await asyncio.sleep(0.05)
        stop.set()
        await task

    # then
    assert any("unsubscribe failed" in record.message for record in caplog.records)


def test_message_domain_shapes() -> None:
    assert _message_domain({"type": "message", "data": "example.com"}) == "example.com"
    assert _message_domain({"type": "message", "data": b"example.com"}) == "example.com"
    assert _message_domain({"type": "subscribe", "data": "example.com"}) is None
    assert _message_domain("example.com") is None
    assert _message_domain({"type": "message", "data": 42}) is None
    assert _message_domain({"type": "message", "data": b"\xff\xfe"}) is None
    assert _message_domain({"type": "message"}) is None


def test_process_reader_adapter_clears_every_instance() -> None:
    # given
    from src.main import _ProcessPurgeReader

    first = _seeded_reader({_domain_key("adapter-one.example", "a"): "first"})
    second = _seeded_reader({_domain_key("adapter-one.example", "b"): "second"})

    # when
    dropped = _ProcessPurgeReader.clear_cache_for_domain("adapter-one.example")

    # then
    assert dropped == 2
    assert first._memory_cache == {}
    assert second._memory_cache == {}


def test_process_reader_adapter_counts_remaining() -> None:
    # given
    from src.main import _ProcessPurgeReader

    first = _seeded_reader({_domain_key("adapter-two.example", "a"): "first"})
    second = _seeded_reader({_domain_key("adapter-two.example", "b"): "second"})

    # when
    total = _ProcessPurgeReader.clear_cache()

    # then
    assert first._memory_cache == {}
    assert second._memory_cache == {}
    assert total >= 2


@pytest.mark.asyncio
async def test_non_message_shapes_skip_the_purge(stop: asyncio.Event) -> None:
    # given
    fake = _FakeRedis(stop)
    reader = _seeded_reader({_domain_key("example.com", "a"): "kept"})

    # when
    with patch("src.reader.cache_purge.settings.READ_CACHE_PURGE_RECONNECT_SECONDS", 0.01):
        task = asyncio.create_task(run_subscriber(reader, lambda: fake, stop))
        for _ in range(100):
            if fake.subscribers:
                break
            await asyncio.sleep(0.01)
        fake.subscribers[0].queue.append({"type": "subscribe", "data": "example.com"})
        for _ in range(100):
            if not fake.subscribers[0].queue:
                break
            await asyncio.sleep(0.01)
        stop.set()
        await task

    # then
    assert reader._memory_cache != {}


@pytest.mark.asyncio
async def test_stop_during_listen_breaks_out(stop: asyncio.Event) -> None:
    # given
    class _StopMidListenPubSub(_FakePubSub):
        async def listen(self) -> AsyncIterator[dict[str, Any]]:
            yield {"type": "message", "channel": "read_cache_purge", "data": "example.com"}
            stop.set()
            yield {"type": "message", "channel": "read_cache_purge", "data": "example.com"}

    class _StoppingRedis(_FakeRedis):
        def pubsub(self) -> _FakePubSub:
            return _StopMidListenPubSub(self)

    fake = _StoppingRedis(stop)
    reader = _seeded_reader({_domain_key("example.com", "a"): "kept"})

    # when
    with patch("src.reader.cache_purge.settings.READ_CACHE_PURGE_RECONNECT_SECONDS", 0.01):
        await asyncio.wait_for(
            run_subscriber(reader, lambda: fake, stop),
            timeout=5,
        )

    # then
    assert reader._memory_cache == {}


@pytest.mark.asyncio
async def test_subscribe_failure_closes_pubsub(stop: asyncio.Event, caplog: pytest.LogCaptureFixture) -> None:
    # given
    fake = _ClosingFakeRedis(stop)
    fake.fail_subscribe = True
    reader = _seeded_reader({})

    # when
    with (
        patch("src.reader.cache_purge.settings.READ_CACHE_PURGE_RECONNECT_SECONDS", 0.01),
        caplog.at_level("WARNING"),
    ):
        task = asyncio.create_task(run_subscriber(reader, lambda: fake, stop))
        for _ in range(200):
            if len(fake.subscribers) >= 2:
                break
            await asyncio.sleep(0.01)
        stop.set()
        await task

    # then
    closing = [s for s in fake.subscribers if isinstance(s, _ClosingFakePubSub)]
    assert len(closing) >= 2
    assert all(s.closed for s in closing)
    assert any("subscribe failed" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_reconnect_closes_previous_pubsub(stop: asyncio.Event) -> None:
    # given
    fake = _ClosingFakeRedis(stop)
    fake.explode_listen = True
    reader = _seeded_reader({_domain_key("example.com", "a"): "stale"})

    # when
    with patch("src.reader.cache_purge.settings.READ_CACHE_PURGE_RECONNECT_SECONDS", 0.01):
        task = asyncio.create_task(run_subscriber(reader, lambda: fake, stop))
        for _ in range(200):
            if len(fake.subscribers) >= 2:
                break
            await asyncio.sleep(0.01)
        stop.set()
        await task

    # then
    closing = [s for s in fake.subscribers if isinstance(s, _ClosingFakePubSub)]
    assert len(closing) >= 2
    assert all(s.closed for s in closing)
    assert reader._memory_cache == {}


@pytest.mark.asyncio
async def test_close_failure_warns_and_continues(
    stop: asyncio.Event, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    fake = _ClosingFakeRedis(stop)
    fake.fail_close = True
    reader = _seeded_reader({})

    # when
    with (
        patch("src.reader.cache_purge.settings.READ_CACHE_PURGE_RECONNECT_SECONDS", 0.01),
        caplog.at_level("WARNING"),
    ):
        task = asyncio.create_task(run_subscriber(reader, lambda: fake, stop))
        await asyncio.sleep(0.1)
        stop.set()
        await task

    # then
    assert any("close failed" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_pubsub_creation_failure_retries_without_close(
    stop: asyncio.Event, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    fake = _PubsubRaisesRedis(stop)
    reader = _seeded_reader({_domain_key("example.com", "a"): "kept"})

    # when
    with (
        patch("src.reader.cache_purge.settings.READ_CACHE_PURGE_RECONNECT_SECONDS", 0.01),
        caplog.at_level("WARNING"),
    ):
        task = asyncio.create_task(run_subscriber(reader, lambda: fake, stop))
        await asyncio.sleep(0.1)
        stop.set()
        await task

    # then
    assert fake.pubsub_calls >= 2
    assert any("subscribe failed" in record.message for record in caplog.records)
