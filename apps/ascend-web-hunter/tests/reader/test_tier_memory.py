"""Tests for the per-domain tier memory (task 4.1)."""

import asyncio
import logging
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.reader import tier_memory
from src.reader.cloudflare.cookie_manager import CookieManager

_URL = "https://example.com/article"


class _FakeRedis:
    """Minimal async Redis double honouring setex TTLs and failing on demand."""

    def __init__(self) -> None:
        self.store: dict[str, tuple[str, float]] = {}
        self.fail_get = False
        self.fail_set = False

    async def get(self, key: str) -> str | None:
        if self.fail_get:
            raise RuntimeError("redis down")

        entry = self.store.get(key)
        if entry is None:
            return None

        value, expires_at = entry
        if time.monotonic() >= expires_at:
            del self.store[key]

            return None

        return value

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        if self.fail_set:
            raise RuntimeError("redis down")

        self.store[key] = (value, time.monotonic() + (ex or 0))


@pytest.fixture(autouse=True)
def _isolated_memory() -> Any:
    tier_memory._memory_store.clear()
    yield
    tier_memory._memory_store.clear()


def _manager_with(fake: _FakeRedis | None) -> MagicMock:
    manager = MagicMock()
    manager.redis_client = fake
    manager.registrable_domain = CookieManager.registrable_domain

    return manager


@pytest.mark.asyncio
async def test_set_then_get_returns_tier() -> None:
    # given
    fake = _FakeRedis()

    # when
    with patch("src.reader.tier_memory.cookie_manager", new=_manager_with(fake)):
        await tier_memory.record(_URL, "4b-camoufox")
        remembered = await tier_memory.get(_URL)

    # then
    assert remembered == "4b-camoufox"


@pytest.mark.asyncio
async def test_cheaper_tier_overwrites() -> None:
    # given
    fake = _FakeRedis()

    # when
    with patch("src.reader.tier_memory.cookie_manager", new=_manager_with(fake)):
        await tier_memory.record(_URL, "5-crawlee_adaptive")
        await tier_memory.record(_URL, "1-beautifulsoup")
        remembered = await tier_memory.get(_URL)

    # then
    assert remembered == "1-beautifulsoup"


@pytest.mark.asyncio
async def test_dearer_tier_overwrites() -> None:
    # given
    fake = _FakeRedis()

    # when
    with patch("src.reader.tier_memory.cookie_manager", new=_manager_with(fake)):
        await tier_memory.record(_URL, "1-beautifulsoup")
        await tier_memory.record(_URL, "5-crawlee_adaptive")
        remembered = await tier_memory.get(_URL)

    # then
    assert remembered == "5-crawlee_adaptive"


@pytest.mark.asyncio
async def test_unknown_tier_does_not_overwrite() -> None:
    # given
    fake = _FakeRedis()

    # when
    with patch("src.reader.tier_memory.cookie_manager", new=_manager_with(fake)):
        await tier_memory.record(_URL, "1-beautifulsoup")
        await tier_memory.record(_URL, "9-telepathy")
        remembered = await tier_memory.get(_URL)

    # then
    assert remembered == "1-beautifulsoup"


@pytest.mark.asyncio
async def test_entry_expires() -> None:
    # given
    fake = _FakeRedis()

    # when
    with (
        patch("src.reader.tier_memory.cookie_manager", new=_manager_with(fake)),
        patch("src.reader.tier_memory.settings.TIER_MEMORY_TTL_SECONDS", 0.05),
    ):
        await tier_memory.record(_URL, "4b-camoufox")
        await asyncio.sleep(0.06)
        remembered = await tier_memory.get(_URL)

    # then
    assert remembered is None


@pytest.mark.asyncio
async def test_redis_error_returns_none_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given
    fake = _FakeRedis()
    fake.fail_get = True

    # when
    with (
        patch("src.reader.tier_memory.cookie_manager", new=_manager_with(fake)),
        caplog.at_level(logging.WARNING, logger="src.reader.tier_memory"),
    ):
        remembered = await tier_memory.get(_URL)

    # then
    assert remembered is None
    assert any("failed to load tier memory" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_record_redis_error_falls_back_without_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given
    fake = _FakeRedis()
    fake.fail_set = True

    # when
    with (
        patch("src.reader.tier_memory.cookie_manager", new=_manager_with(fake)),
        caplog.at_level(logging.WARNING, logger="src.reader.tier_memory"),
    ):
        await tier_memory.record(_URL, "4b-camoufox")

    # then
    assert any("failed to save tier memory" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_memory_fallback_without_redis() -> None:
    # when
    with patch("src.reader.tier_memory.cookie_manager", new=_manager_with(None)):
        await tier_memory.record(_URL, "4b-camoufox")
        remembered = await tier_memory.get(_URL)

    # then
    assert remembered == "4b-camoufox"


@pytest.mark.asyncio
async def test_memory_fallback_entry_expires() -> None:
    # when
    with (
        patch("src.reader.tier_memory.cookie_manager", new=_manager_with(None)),
        patch("src.reader.tier_memory.settings.TIER_MEMORY_TTL_SECONDS", 0.05),
    ):
        await tier_memory.record(_URL, "4b-camoufox")
        await asyncio.sleep(0.06)
        remembered = await tier_memory.get(_URL)

    # then
    assert remembered is None


@pytest.mark.asyncio
async def test_bytes_value_is_decoded() -> None:
    # given
    fake = _FakeRedis()
    raw_store: dict[str, tuple[Any, float]] = fake.store
    raw_store["tier_memory:example.com"] = (b"4b-camoufox", time.monotonic() + 60)

    # when
    with patch("src.reader.tier_memory.cookie_manager", new=_manager_with(fake)):
        remembered = await tier_memory.get(_URL)

    # then
    assert remembered == "4b-camoufox"


@pytest.mark.asyncio
async def test_memory_fallback_without_a_record_is_none() -> None:
    # when
    with patch("src.reader.tier_memory.cookie_manager", new=_manager_with(None)):
        remembered = await tier_memory.get(_URL)

    # then
    assert remembered is None
