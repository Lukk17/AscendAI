"""Tests for CrawleeStrategy honouring PLAYWRIGHT_HEADLESS (task 6.5)."""

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.reader.strategies.crawlee_strategy import CrawleeStrategy
from src.validator.url_validator import URLValidator


def _mock_url_validator() -> URLValidator:
    rules = MagicMock()
    rules.should_block.return_value = False
    return URLValidator(rules)


def _mock_crawler(html: str = "<html><body>content</body></html>") -> MagicMock:
    crawler = MagicMock()
    crawler.router = MagicMock()
    crawler.router.default_handler = lambda f: f
    crawler.pre_navigation_hook = lambda f: f
    crawler.run = AsyncMock()

    # Simulate the result container being populated by the handler
    async def fake_run(urls: list[str]) -> None:
        pass

    crawler.run = AsyncMock(side_effect=fake_run)
    return crawler


_CRAWLER_FACTORY_PATH = (
    "src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler.with_beautifulsoup_static_parser"
)


@pytest.mark.asyncio
async def test_crawlee_uses_playwright_headless_setting():
    """headless kwarg passed to AdaptivePlaywrightCrawler must equal settings.PLAYWRIGHT_HEADLESS."""
    captured: dict[str, Any] = {}

    def fake_crawler_factory(**kwargs: Any) -> MagicMock:
        captured.update(kwargs)
        crawler = MagicMock()
        crawler.router = MagicMock()
        crawler.router.default_handler = lambda f: f
        crawler.pre_navigation_hook = lambda f: f
        crawler.run = AsyncMock()
        return crawler

    with (
        patch(
            _CRAWLER_FACTORY_PATH,
            side_effect=fake_crawler_factory,
        ),
        patch("src.reader.strategies.crawlee_strategy.settings.PLAYWRIGHT_HEADLESS", True),
        patch(
            "src.reader.strategies.crawlee_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.crawlee_strategy.ChallengeDetector.is_login_required", return_value=False
        ),
        patch("src.reader.strategies.crawlee_strategy.ChallengeDetector.is_blocked", return_value=False),
    ):
        strategy = CrawleeStrategy(_mock_url_validator())
        await strategy.get_html("https://example.com")

    pw_kwargs = captured.get("playwright_crawler_specific_kwargs", {})
    assert pw_kwargs.get("headless") is True


@pytest.mark.asyncio
async def test_crawlee_headless_false_when_setting_false():
    """headless=False must be passed when PLAYWRIGHT_HEADLESS=False."""
    captured: dict[str, Any] = {}

    def fake_crawler_factory(**kwargs: Any) -> MagicMock:
        captured.update(kwargs)
        crawler = MagicMock()
        crawler.router = MagicMock()
        crawler.router.default_handler = lambda f: f
        crawler.pre_navigation_hook = lambda f: f
        crawler.run = AsyncMock()
        return crawler

    with (
        patch(
            _CRAWLER_FACTORY_PATH,
            side_effect=fake_crawler_factory,
        ),
        patch("src.reader.strategies.crawlee_strategy.settings.PLAYWRIGHT_HEADLESS", False),
        patch(
            "src.reader.strategies.crawlee_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.crawlee_strategy.ChallengeDetector.is_login_required", return_value=False
        ),
        patch("src.reader.strategies.crawlee_strategy.ChallengeDetector.is_blocked", return_value=False),
    ):
        strategy = CrawleeStrategy(_mock_url_validator())
        await strategy.get_html("https://example.com")

    pw_kwargs = captured.get("playwright_crawler_specific_kwargs", {})
    assert pw_kwargs.get("headless") is False


@pytest.mark.asyncio
async def test_crawlee_get_html_raises_timeout_error_when_crawler_hangs(monkeypatch: pytest.MonkeyPatch):
    """A crawler.run() that never returns (e.g. Crawlee's autoscaler permanently reports the
    system as memory-overloaded, so no request is ever dequeued) must not hang this tier
    forever: get_html() must raise TimeoutError within the configured budget instead."""
    monkeypatch.setattr("src.reader.strategies.crawlee_strategy.settings.EXTRACT_TIMEOUT", 0.05)

    async def hanging_run(urls: list[str]) -> None:
        await asyncio.sleep(999)

    def fake_crawler_factory(**_kwargs: Any) -> MagicMock:
        crawler = MagicMock()
        crawler.router = MagicMock()
        crawler.router.default_handler = lambda f: f
        crawler.pre_navigation_hook = lambda f: f
        crawler.run = AsyncMock(side_effect=hanging_run)
        return crawler

    with (
        patch(_CRAWLER_FACTORY_PATH, side_effect=fake_crawler_factory),
        patch(
            "src.reader.strategies.crawlee_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
    ):
        strategy = CrawleeStrategy(_mock_url_validator())

        with pytest.raises(TimeoutError, match="tier exceeded its"):
            await strategy.get_html("https://example.com")


@pytest.mark.asyncio
async def test_crawlee_get_html_raises_when_cancellation_is_swallowed(monkeypatch: pytest.MonkeyPatch):
    """Crawlee's BasicCrawler.run() catches CancelledError internally and can return
    normally after being cancelled (see asyncio.wait_for docs: a task that suppresses
    the cancellation and returns a value has that value returned, not TimeoutError).
    get_html() must still detect the overrun via elapsed time and raise TimeoutError."""
    monkeypatch.setattr("src.reader.strategies.crawlee_strategy.settings.EXTRACT_TIMEOUT", 0.05)

    async def hangs_then_swallows_cancellation(urls: list[str]) -> None:
        try:
            await asyncio.sleep(999)
        except asyncio.CancelledError:
            await asyncio.sleep(0.05)

    def fake_crawler_factory(**_kwargs: Any) -> MagicMock:
        crawler = MagicMock()
        crawler.router = MagicMock()
        crawler.router.default_handler = lambda f: f
        crawler.pre_navigation_hook = lambda f: f
        crawler.run = AsyncMock(side_effect=hangs_then_swallows_cancellation)
        return crawler

    with (
        patch(_CRAWLER_FACTORY_PATH, side_effect=fake_crawler_factory),
        patch(
            "src.reader.strategies.crawlee_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
    ):
        strategy = CrawleeStrategy(_mock_url_validator())

        with pytest.raises(TimeoutError, match=r"ran .*permanently memory-overloaded"):
            await strategy.get_html("https://example.com")


@pytest.mark.asyncio
async def test_crawlee_sets_memory_mbytes_env_var_before_crawler_construction(
    monkeypatch: pytest.MonkeyPatch,
):
    """CRAWLEE_MEMORY_MBYTES, when configured, must be propagated to the environment
    variable Crawlee itself reads before the crawler is constructed: Crawlee's service
    locator lazily builds and caches its Configuration singleton the first time any
    crawler is constructed in the process and never re-reads the environment afterwards,
    so setting the variable any later would silently have no effect."""
    monkeypatch.setattr("src.reader.strategies.crawlee_strategy.settings.CRAWLEE_MEMORY_MBYTES", 2048)
    monkeypatch.delenv("CRAWLEE_MEMORY_MBYTES", raising=False)

    seen_at_construction: dict[str, str | None] = {}

    def fake_crawler_factory(**_kwargs: Any) -> MagicMock:
        seen_at_construction["value"] = os.environ.get("CRAWLEE_MEMORY_MBYTES")
        crawler = MagicMock()
        crawler.router = MagicMock()
        crawler.router.default_handler = lambda f: f
        crawler.pre_navigation_hook = lambda f: f
        crawler.run = AsyncMock()
        return crawler

    try:
        with (
            patch(_CRAWLER_FACTORY_PATH, side_effect=fake_crawler_factory),
            patch(
                "src.reader.strategies.crawlee_strategy.cookie_manager.get_storage_state",
                new=AsyncMock(return_value=None),
            ),
        ):
            strategy = CrawleeStrategy(_mock_url_validator())
            await strategy.get_html("https://example.com")

        assert seen_at_construction["value"] == "2048"
    finally:
        os.environ.pop("CRAWLEE_MEMORY_MBYTES", None)


@pytest.mark.asyncio
async def test_crawlee_sets_storage_dir_env_var_before_crawler_construction(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
):
    """CRAWLEE_STORAGE_DIR must be propagated to the environment variable Crawlee itself
    reads before the crawler is constructed, for the same reason as CRAWLEE_MEMORY_MBYTES
    above: Crawlee's service locator caches its Configuration singleton on first crawler
    construction and never re-reads the environment afterwards."""
    storage_dir = tmp_path / "storage"
    monkeypatch.setattr(
        "src.reader.strategies.crawlee_strategy.settings.CRAWLEE_STORAGE_DIR", str(storage_dir)
    )
    monkeypatch.delenv("CRAWLEE_STORAGE_DIR", raising=False)

    seen_at_construction: dict[str, str | None] = {}

    def fake_crawler_factory(**_kwargs: Any) -> MagicMock:
        seen_at_construction["value"] = os.environ.get("CRAWLEE_STORAGE_DIR")
        crawler = MagicMock()
        crawler.router = MagicMock()
        crawler.router.default_handler = lambda f: f
        crawler.pre_navigation_hook = lambda f: f
        crawler.run = AsyncMock()
        return crawler

    try:
        with (
            patch(_CRAWLER_FACTORY_PATH, side_effect=fake_crawler_factory),
            patch(
                "src.reader.strategies.crawlee_strategy.cookie_manager.get_storage_state",
                new=AsyncMock(return_value=None),
            ),
        ):
            strategy = CrawleeStrategy(_mock_url_validator())
            await strategy.get_html("https://example.com")

        assert seen_at_construction["value"] == str(storage_dir.resolve())
    finally:
        os.environ.pop("CRAWLEE_STORAGE_DIR", None)
