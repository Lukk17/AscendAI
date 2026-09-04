"""Tests for read-result cache-aside in WebReader (task 7.1)."""

from unittest.mock import patch

import pytest

from src.reader.web_reader import WebReader, _cache_key


@pytest.mark.asyncio
async def test_cache_hit_skips_strategy_chain() -> None:
    """A repeated request within TTL must return cached result without running strategies."""
    reader = WebReader()
    call_count = 0

    async def _fake_execute(
        name: str,
        strategy,
        url: str,
        *,
        output_format: str | None = None,
    ):
        nonlocal call_count
        call_count += 1
        return {"content": "some content", "status": "success", "mode": name}

    with patch.object(reader, "_execute_strategy", side_effect=_fake_execute):
        result1 = await reader.read("https://example.com/article")
        result2 = await reader.read("https://example.com/article")

    assert result1["status"] == "success"
    assert result2["status"] == "success"
    assert call_count == 1, "strategy chain ran more than once — cache did not work"


@pytest.mark.asyncio
async def test_cache_miss_on_different_output_format() -> None:
    """Different output_format must produce different cache keys."""
    key_text = _cache_key("https://example.com/", False, False, None, "text")
    key_structured = _cache_key("https://example.com/", False, False, None, "structured")
    assert key_text != key_structured


@pytest.mark.asyncio
async def test_cache_miss_on_different_heavy_mode() -> None:
    """Different heavy_mode must produce different cache keys."""
    key_light = _cache_key("https://example.com/", False, False, None, None)
    key_heavy = _cache_key("https://example.com/", True, False, None, None)
    assert key_light != key_heavy


@pytest.mark.asyncio
async def test_cache_entry_expires_after_ttl() -> None:
    """After the TTL has elapsed the cache must be a miss and re-run the chain."""
    from src.reader.web_reader import _cache_key

    reader = WebReader()
    call_count = 0

    async def _fake_execute(
        name: str,
        strategy,
        url: str,
        *,
        output_format: str | None = None,
    ):
        nonlocal call_count
        call_count += 1
        return {"content": "some content", "status": "success", "mode": name}

    url = "https://example.com/article"
    key = _cache_key(url, False, False, None, None)
    # Seed the cache with a stale entry (stored_at far in the past)
    reader._memory_cache[key] = ({"content": "stale", "status": "success", "mode": "1"}, 0.0)

    with (
        patch.object(reader, "_execute_strategy", side_effect=_fake_execute),
        patch("src.reader.web_reader.settings.READ_CACHE_TTL_SECONDS", 1),
    ):
        # First call: cache is stale (stored_at=0.0, TTL=1, now >> 1), should re-run chain
        await reader.read(url)

    assert call_count == 1, "stale cache should have been expired — chain must re-run"


@pytest.mark.asyncio
async def test_cache_hit_increments_metric() -> None:
    """READ_CACHE_HITS_TOTAL must increment on a cache hit."""
    from prometheus_client import REGISTRY

    reader = WebReader()
    call_count = 0

    async def _fake_execute(
        name: str,
        strategy,
        url: str,
        *,
        output_format: str | None = None,
    ):
        nonlocal call_count
        call_count += 1
        return {"content": "some content", "status": "success", "mode": name}

    before = REGISTRY.get_sample_value("read_cache_hits_total") or 0.0

    with patch.object(reader, "_execute_strategy", side_effect=_fake_execute):
        await reader.read("https://cachemetric2.example.com/test")
        await reader.read("https://cachemetric2.example.com/test")

    after = REGISTRY.get_sample_value("read_cache_hits_total") or 0.0
    assert after == before + 1.0


@pytest.mark.asyncio
async def test_read_with_links_cache_hit_skips_strategy_chain() -> None:
    """A cached read_with_links result must not re-run the strategy chain."""
    reader = WebReader()
    url = "https://links-cache.example.com/"

    cached_result = {"content": "cached content", "links": [], "status": "success", "mode": "1-beautifulsoup"}
    key = _cache_key(url, False, True, None, None)
    reader._memory_cache[key] = (cached_result, float("inf"))

    execute_called = False

    async def _fake_execute(name, strategy, url_, *, output_format=None):
        nonlocal execute_called
        execute_called = True
        return {"content": "fresh", "status": "success", "mode": name}

    with patch.object(reader, "_execute_strategy", side_effect=_fake_execute):
        result = await reader.read_with_links(url)

    assert result == cached_result
    assert not execute_called, "cache hit must not invoke the strategy chain"


def test_clear_cache_for_domain_removes_matching_entries_only() -> None:
    reader = WebReader()
    reader._memory_cache["https://allegro.pl/oferta/x|heavy=False|links=False|profile=|fmt=text"] = (
        {"content": "stale allegro", "status": "success", "mode": "1"},
        0.0,
    )
    reader._memory_cache["https://allegro.pl/oferta/y|heavy=True|links=True|profile=work|fmt=text"] = (
        {"content": "stale allegro 2", "status": "success", "mode": "1"},
        0.0,
    )
    reader._memory_cache["https://example.com/z|heavy=False|links=False|profile=|fmt=text"] = (
        {"content": "unrelated", "status": "success", "mode": "1"},
        0.0,
    )

    removed = reader.clear_cache_for_domain("allegro.pl")

    assert removed == 2
    assert len(reader._memory_cache) == 1
    remaining_key = next(iter(reader._memory_cache))
    assert remaining_key.startswith("https://example.com/z")


def test_clear_cache_for_domain_returns_zero_when_nothing_matches() -> None:
    reader = WebReader()
    reader._memory_cache["https://example.com/z|heavy=False|links=False|profile=|fmt=text"] = (
        {"content": "unrelated", "status": "success", "mode": "1"},
        0.0,
    )

    removed = reader.clear_cache_for_domain("never-cached.example.org")

    assert removed == 0
    assert len(reader._memory_cache) == 1


@pytest.mark.asyncio
async def test_cache_is_isolated_per_reader_instance() -> None:
    """Each WebReader instance has its own in-process cache — they do not share state."""
    reader1 = WebReader()
    reader2 = WebReader()

    count1 = 0
    count2 = 0

    async def _fake1(
        name: str,
        strategy,
        url: str,
        *,
        output_format: str | None = None,
    ):
        nonlocal count1
        count1 += 1
        return {"content": "c1", "status": "success", "mode": name}

    async def _fake2(
        name: str,
        strategy,
        url: str,
        *,
        output_format: str | None = None,
    ):
        nonlocal count2
        count2 += 1
        return {"content": "c2", "status": "success", "mode": name}

    with patch.object(reader1, "_execute_strategy", side_effect=_fake1):
        await reader1.read("https://shared.example.com/")
        # second call on reader1 should hit cache
        await reader1.read("https://shared.example.com/")

    with patch.object(reader2, "_execute_strategy", side_effect=_fake2):
        # reader2 has no cache entry — must call chain
        await reader2.read("https://shared.example.com/")

    assert count1 == 1
    assert count2 == 1
