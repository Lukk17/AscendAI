"""Tests for read-result cache-aside in WebReader (task 7.1)."""

from typing import Any
from unittest.mock import patch

import pytest

from src.reader.strategies.base_strategy import FetchedHtml, validators_of
from src.reader.web_reader import ReadCacheKey, WebReader, _cache_key


@pytest.mark.asyncio
async def test_cache_hit_skips_strategy_chain() -> None:
    """A repeated request within TTL must return cached result without running strategies."""
    # given
    reader = WebReader()
    call_count = 0

    async def _fake_execute(
        name: str,
        strategy: Any,
        url: str,
        *,
        output_format: str | None = None,
        extraction_schema: Any = None,
        escalate_failures: bool = False,
    ) -> Any:
        nonlocal call_count
        call_count += 1
        return {"content": "some content", "status": "success", "mode": name}

    # when
    with patch.object(reader, "_execute_strategy", side_effect=_fake_execute):
        result1 = await reader.read("https://example.com/article")
        result2 = await reader.read("https://example.com/article")

    # then
    assert result1["status"] == "success"
    assert result2["status"] == "success"
    assert call_count == 1, "strategy chain ran more than once - cache did not work"


@pytest.mark.asyncio
async def test_cache_miss_on_different_output_format() -> None:
    """Different output_format must produce different cache keys."""
    # given
    key_text = _cache_key("https://example.com/", False, False, None, "text")

    # when
    key_structured = _cache_key("https://example.com/", False, False, None, "structured")

    # then
    assert key_text != key_structured


@pytest.mark.asyncio
async def test_cache_miss_on_different_heavy_mode() -> None:
    """Different heavy_mode must produce different cache keys."""
    # given
    key_light = _cache_key("https://example.com/", False, False, None, None)

    # when
    key_heavy = _cache_key("https://example.com/", True, False, None, None)

    # then
    assert key_light != key_heavy


@pytest.mark.asyncio
async def test_cache_entry_expires_after_ttl() -> None:
    """After the TTL has elapsed the cache must be a miss and re-run the chain."""
    # given
    from src.reader.web_reader import _cache_key

    reader = WebReader()
    call_count = 0

    async def _fake_execute(
        name: str,
        strategy: Any,
        url: str,
        *,
        output_format: str | None = None,
        extraction_schema: Any = None,
        escalate_failures: bool = False,
    ) -> Any:
        nonlocal call_count
        call_count += 1
        return {"content": "some content", "status": "success", "mode": name}

    url = "https://example.com/article"
    key = _cache_key(url, False, False, None, None)
    # Seed the cache with a stale entry (stored_at far in the past)
    reader._memory_cache[key] = ({"content": "stale", "status": "success", "mode": "1"}, 0.0)

    # when
    with (
        patch.object(reader, "_execute_strategy", side_effect=_fake_execute),
        patch("src.reader.web_reader.settings.READ_CACHE_TTL_SECONDS", 1),
    ):
        # First call: cache is stale (stored_at=0.0, TTL=1, now >> 1), should re-run chain
        await reader.read(url)

    # then
    assert call_count == 1, "stale cache should have been expired - chain must re-run"


@pytest.mark.asyncio
async def test_cache_hit_increments_metric() -> None:
    """READ_CACHE_HITS_TOTAL must increment on a cache hit."""
    # given
    from prometheus_client import REGISTRY

    reader = WebReader()
    call_count = 0

    async def _fake_execute(
        name: str,
        strategy: Any,
        url: str,
        *,
        output_format: str | None = None,
        extraction_schema: Any = None,
        escalate_failures: bool = False,
    ) -> Any:
        nonlocal call_count
        call_count += 1
        return {"content": "some content", "status": "success", "mode": name}

    before = REGISTRY.get_sample_value("read_cache_hits_total") or 0.0

    with patch.object(reader, "_execute_strategy", side_effect=_fake_execute):
        await reader.read("https://cachemetric2.example.com/test")
        await reader.read("https://cachemetric2.example.com/test")

    # when
    after = REGISTRY.get_sample_value("read_cache_hits_total") or 0.0

    # then
    assert after == before + 1.0


@pytest.mark.asyncio
async def test_read_with_links_cache_hit_skips_strategy_chain() -> None:
    """A cached read_with_links result must not re-run the strategy chain."""
    # given
    reader = WebReader()
    url = "https://links-cache.example.com/"

    cached_result = {"content": "cached content", "links": [], "status": "success", "mode": "1-beautifulsoup"}
    key = _cache_key(url, False, True, None, None)
    reader._memory_cache[key] = (cached_result, float("inf"))

    execute_called = False

    async def _fake_execute(
        name: Any,
        strategy: Any,
        url_: Any,
        *,
        output_format: Any = None,
        extraction_schema: Any = None,
        escalate_failures: bool = False,
    ) -> Any:
        nonlocal execute_called
        execute_called = True
        return {"content": "fresh", "status": "success", "mode": name}

    # when
    with patch.object(reader, "_execute_strategy", side_effect=_fake_execute):
        result = await reader.read_with_links(url)

    # then
    assert result == cached_result
    assert not execute_called, "cache hit must not invoke the strategy chain"


@pytest.mark.asyncio
async def test_read_with_links_with_another_link_filter_answers_its_own_links() -> None:
    # given
    reader = WebReader()
    url = "https://links-filter.example.com/"
    html = '<html><body><p>words</p><a href="/job/1">job</a><a href="/blog/2">blog</a></body></html>'

    async def _fake_execute_html(
        name: Any, strategy: Any, url_: Any, *, escalate_failures: bool = False
    ) -> str:
        return html

    # when
    with (
        patch.object(reader, "_execute_html_strategy", side_effect=_fake_execute_html),
        patch.object(reader.validator, "validate", return_value=True),
    ):
        await reader.read_with_links(url, link_filter="/job/")
        second = await reader.read_with_links(url, link_filter="/blog/")

    # then
    assert second["links"] == {1: "https://links-filter.example.com/blog/2"}


_VALIDATED_HTML = FetchedHtml(
    "<html><body><p>" + "cached words " * 20 + '<a href="/next">next</a></p></body></html>',
    {"etag": '"g1"', "last-modified": "Fri"},
)


@pytest.mark.asyncio
async def test_linked_page_read_keeps_the_page_and_a_cache_hit_returns_the_same_page() -> None:
    # given a tier whose final answer carried ETag and Last-Modified
    reader = WebReader()
    url = "https://links-validators.example.com/"
    tier_reads = 0

    async def _fake_execute_html(
        name: Any, strategy: Any, url_: Any, *, escalate_failures: bool = False
    ) -> str:
        nonlocal tier_reads
        tier_reads += 1
        return _VALIDATED_HTML

    # when the page is read twice
    with (
        patch.object(reader, "_execute_html_strategy", side_effect=_fake_execute_html),
        patch.object(reader.validator, "validate", return_value=True),
    ):
        first = await reader.read_linked_page(url)
        second = await reader.read_linked_page(url)

    # then both reads keep the validators of the one tier read
    assert validators_of(first.page) == ('"g1"', "Fri")
    assert validators_of(second.page) == ('"g1"', "Fri")
    assert tier_reads == 1


@pytest.mark.asyncio
async def test_page_read_keeps_the_page_of_the_tier_and_a_cache_hit_returns_the_same_page() -> None:
    # given a tier whose final answer carried ETag and Last-Modified
    reader = WebReader()
    url = "https://page-validators.example.com/"
    tier_reads = 0

    async def _tier_html(name: Any, strategy: Any, url_: Any) -> str:
        nonlocal tier_reads
        tier_reads += 1
        return _VALIDATED_HTML

    # when the page is read twice in a formatted output
    with (
        patch.object(reader, "_novnc_or_tier_html", side_effect=_tier_html),
        patch.object(reader.validator, "validate", return_value=True),
    ):
        first = await reader.read_page(url, output_format="structured")
        second = await reader.read_page(url, output_format="structured")

    # then both reads keep the page of the one tier read
    assert first.page == _VALIDATED_HTML
    assert validators_of(second.page) == ('"g1"', "Fri")
    assert tier_reads == 1


@pytest.mark.asyncio
async def test_public_reads_answer_plain_dicts_without_the_page() -> None:
    # given a tier whose final answer carried ETag and Last-Modified
    reader = WebReader()

    async def _tier_html(name: Any, strategy: Any, url_: Any) -> str:
        return _VALIDATED_HTML

    # when
    with (
        patch.object(reader, "_novnc_or_tier_html", side_effect=_tier_html),
        patch.object(reader.validator, "validate", return_value=True),
    ):
        linked = await reader.read_with_links("https://public-links.example.com/")
        formatted = await reader.read("https://public-read.example.com/", output_format="structured")

    # then
    assert type(linked) is dict
    assert set(linked) == {"content", "links", "status", "mode"}
    assert type(formatted) is dict
    assert "etag" not in formatted
    assert "last_modified" not in formatted


def test_clear_cache_for_domain_removes_matching_entries_only() -> None:
    # given
    reader = WebReader()
    reader._memory_cache[_cache_key("https://allegro.pl/oferta/x", False, False, None, "text")] = (
        {"content": "stale allegro", "status": "success", "mode": "1"},
        0.0,
    )
    reader._memory_cache[_cache_key("https://allegro.pl/oferta/y", True, True, "work", "text")] = (
        {"content": "stale allegro 2", "status": "success", "mode": "1"},
        0.0,
    )
    reader._memory_cache[_cache_key("https://example.com/z", False, False, None, "text")] = (
        {"content": "unrelated", "status": "success", "mode": "1"},
        0.0,
    )

    # when
    removed = reader.clear_cache_for_domain("allegro.pl")

    # then
    assert removed == 2
    assert len(reader._memory_cache) == 1
    remaining_key = next(iter(reader._memory_cache))
    assert remaining_key.url == "https://example.com/z"


def test_clear_cache_for_domain_returns_zero_when_nothing_matches() -> None:
    # given
    reader = WebReader()
    reader._memory_cache[_cache_key("https://example.com/z", False, False, None, "text")] = (
        {"content": "unrelated", "status": "success", "mode": "1"},
        0.0,
    )

    # when
    removed = reader.clear_cache_for_domain("never-cached.example.org")

    # then
    assert removed == 0
    assert len(reader._memory_cache) == 1


@pytest.mark.asyncio
async def test_cache_is_isolated_per_reader_instance() -> None:
    """Each WebReader instance has its own in-process cache - they do not share state."""
    # given
    reader1 = WebReader()
    reader2 = WebReader()

    count1 = 0
    count2 = 0

    async def _fake1(
        name: str,
        strategy: Any,
        url: str,
        *,
        output_format: str | None = None,
        extraction_schema: Any = None,
        escalate_failures: bool = False,
    ) -> Any:
        nonlocal count1
        count1 += 1
        return {"content": "c1", "status": "success", "mode": name}

    async def _fake2(
        name: str,
        strategy: Any,
        url: str,
        *,
        output_format: str | None = None,
        extraction_schema: Any = None,
        escalate_failures: bool = False,
    ) -> Any:
        nonlocal count2
        count2 += 1
        return {"content": "c2", "status": "success", "mode": name}

    with patch.object(reader1, "_execute_strategy", side_effect=_fake1):
        await reader1.read("https://shared.example.com/")
        # second call on reader1 should hit cache
        await reader1.read("https://shared.example.com/")

    # when
    with patch.object(reader2, "_execute_strategy", side_effect=_fake2):
        # reader2 has no cache entry - must call chain
        await reader2.read("https://shared.example.com/")

    # then
    assert count1 == 1
    assert count2 == 1


def _named_key(name: str) -> ReadCacheKey:
    return _cache_key(f"https://{name}.example/", False, False, None, None)


def test_cache_write_evicts_the_oldest_entry_past_the_bound() -> None:
    # given
    reader = WebReader()

    # when
    with patch("src.reader.web_reader._READ_CACHE_MAX_ENTRIES", 2):
        reader._cache_put(_named_key("first"), {"content": "1"})
        reader._cache_put(_named_key("second"), {"content": "2"})
        reader._cache_put(_named_key("third"), {"content": "3"})

    # then
    assert list(reader._memory_cache) == [_named_key("second"), _named_key("third")]


def test_cache_rewrite_of_a_key_makes_it_the_newest() -> None:
    # given
    reader = WebReader()

    # when
    with patch("src.reader.web_reader._READ_CACHE_MAX_ENTRIES", 2):
        reader._cache_put(_named_key("first"), {"content": "1"})
        reader._cache_put(_named_key("second"), {"content": "2"})
        reader._cache_put(_named_key("first"), {"content": "1 again"})
        reader._cache_put(_named_key("third"), {"content": "3"})

    # then
    assert list(reader._memory_cache) == [_named_key("first"), _named_key("third")]
    assert reader._memory_cache[_named_key("first")][0] == {"content": "1 again"}


def test_cache_write_drops_expired_entries_nobody_reads() -> None:
    # given
    reader = WebReader()

    # when
    with (
        patch("src.reader.web_reader.settings.READ_CACHE_TTL_SECONDS", 10),
        patch("src.reader.web_reader.time.monotonic", side_effect=[0.0, 5.0, 12.0]),
    ):
        reader._cache_put(_named_key("stale"), {"content": "old"})
        reader._cache_put(_named_key("fresh"), {"content": "new"})
        reader._cache_put(_named_key("latest"), {"content": "newest"})

    # then
    assert list(reader._memory_cache) == [_named_key("fresh"), _named_key("latest")]


_FRESH_HTML = FetchedHtml("<html><body><p>" + "fresh words " * 20 + "</p></body></html>", {})
_PREFILLED = {"content": "another tenant's read", "links": {}, "status": "success", "mode": "1"}


@pytest.mark.asyncio
async def test_linked_page_read_without_the_read_cache_fetches_fresh_and_stores_nothing() -> None:
    # given a read cache prefilled for the URL
    reader = WebReader()
    url = "https://crawl-linked.example.com/"
    key = _cache_key(url, False, True, None, None)
    reader._memory_cache[key] = (_PREFILLED, float("inf"))
    tier_reads = 0

    async def _fake_execute_html(
        name: Any, strategy: Any, url_: Any, *, escalate_failures: bool = False
    ) -> str:
        nonlocal tier_reads
        tier_reads += 1
        return _FRESH_HTML

    # when the page is read past the cache
    with (
        patch.object(reader, "_execute_html_strategy", side_effect=_fake_execute_html),
        patch.object(reader.validator, "validate", return_value=True),
    ):
        result = await reader.read_linked_page(url, use_read_cache=False)

    # then the read fetched the page and the cache still holds only the prefilled entry
    assert tier_reads == 1
    assert "fresh words" in result["content"]
    assert reader._memory_cache == {key: (_PREFILLED, float("inf"))}


@pytest.mark.asyncio
async def test_page_read_without_the_read_cache_fetches_fresh_and_stores_nothing() -> None:
    # given a read cache prefilled for the URL in the requested format
    reader = WebReader()
    url = "https://crawl-page.example.com/"
    key = _cache_key(url, False, False, None, "structured")
    reader._memory_cache[key] = (_PREFILLED, float("inf"))
    tier_reads = 0

    async def _tier_html(name: Any, strategy: Any, url_: Any) -> str:
        nonlocal tier_reads
        tier_reads += 1
        return _FRESH_HTML

    # when the page is read past the cache
    with (
        patch.object(reader, "_novnc_or_tier_html", side_effect=_tier_html),
        patch.object(reader.validator, "validate", return_value=True),
    ):
        result = await reader.read_page(url, output_format="structured", use_read_cache=False)

    # then the read fetched the page and the cache still holds only the prefilled entry
    assert tier_reads == 1
    assert "fresh words" in result["content"]
    assert reader._memory_cache == {key: (_PREFILLED, float("inf"))}


@pytest.mark.asyncio
async def test_routed_document_read_without_the_read_cache_stores_nothing() -> None:
    # given a document URL the router converts
    from src.reader.document_router import RouteResult

    reader = WebReader()
    url = "https://crawl-doc.example.com/report.pdf"

    # when the document is read past the cache
    with patch(
        "src.reader.web_reader.route_document",
        return_value=RouteResult("pdf", "converted text", None),
    ):
        result = await reader.read_page(url, use_read_cache=False)

    # then the converted text answers and the cache stays empty
    assert result["content"] == "converted text"
    assert reader._memory_cache == {}


def test_reads_whose_joined_fields_would_read_alike_have_different_cache_keys() -> None:
    # given
    url = "https://example.com/"

    # when
    profile_carries_the_format = _cache_key(url, False, False, "a|fmt=b", "c")
    format_carries_the_rest = _cache_key(url, False, False, "a", "b|fmt=c")

    # then
    assert profile_carries_the_format != format_carries_the_rest


def test_purging_a_domain_reads_the_address_field_of_the_key() -> None:
    # given
    reader = WebReader()
    kept = _cache_key("https://other.org/x|https://example.com/", False, False, None, None)
    purged = _cache_key("https://www.example.com/a", False, False, None, None)
    reader._cache_put(kept, {"content": "kept"})
    reader._cache_put(purged, {"content": "purged"})

    # when
    removed = reader.clear_cache_for_domain("example.com")

    # then
    assert removed == 1
    assert reader._cache_get(kept) == {"content": "kept"}
    assert reader._cache_get(purged) is None
