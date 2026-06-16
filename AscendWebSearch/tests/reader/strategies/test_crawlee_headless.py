"""Tests for CrawleeStrategy honouring PLAYWRIGHT_HEADLESS (task 6.5)."""

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
            "src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler.with_beautifulsoup_static_parser",
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
            "src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler.with_beautifulsoup_static_parser",
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
