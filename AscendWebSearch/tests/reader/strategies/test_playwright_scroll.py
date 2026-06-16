"""Tests for Playwright scroll wiring (task 5.3)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.reader.strategies.playwright_strategy import PlaywrightStrategy
from src.validator.url_validator import URLValidator


def _make_url_validator() -> URLValidator:
    rules = MagicMock()
    rules.should_block.return_value = False
    return URLValidator(rules)


def _make_browser_and_page() -> tuple[MagicMock, MagicMock, MagicMock]:
    page = MagicMock()
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.content = AsyncMock(return_value="<html><body>loaded content</body></html>")
    page.url = "https://example.com/page"
    page.wait_for_load_state = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.route = AsyncMock()
    page.evaluate = AsyncMock(return_value=0)

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    return browser, context, page


@pytest.mark.asyncio
async def test_scroll_called_configured_number_of_times() -> None:
    """PlaywrightStrategy must call window.scrollBy exactly SCROLL_ITERATIONS times."""
    scroll_iters = 3
    scroll_step = 1200
    browser, _, page = _make_browser_and_page()
    with (
        patch(
            "src.reader.strategies.playwright_strategy.browser_pool.get_browser",
            new=AsyncMock(return_value=browser),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch("src.reader.strategies.playwright_strategy.Stealth.apply_stealth_async", new=AsyncMock()),
        patch(
            "src.reader.strategies.playwright_strategy.ChallengeDetector.is_login_required",
            return_value=False,
        ),
        patch("src.reader.strategies.playwright_strategy.ChallengeDetector.is_blocked", return_value=False),
        patch(
            "src.reader.strategies.playwright_strategy.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
        patch("src.reader.strategies.playwright_strategy.proxy_provider.for_playwright", return_value=None),
        patch("src.reader.strategies.playwright_strategy.settings.SCROLL_ITERATIONS", scroll_iters),
        patch("src.reader.strategies.playwright_strategy.settings.SCROLL_STEP_PX", scroll_step),
    ):
        strategy = PlaywrightStrategy(lambda: "UA", _make_url_validator())
        await strategy.get_html("https://example.com/page")

    scroll_calls = [c for c in page.evaluate.await_args_list if "scrollBy" in str(c)]
    assert len(scroll_calls) == scroll_iters


@pytest.mark.asyncio
async def test_scroll_uses_configured_step_px() -> None:
    """Each scroll call must use SCROLL_STEP_PX pixels."""
    scroll_step = 2500
    browser, _, page = _make_browser_and_page()
    with (
        patch(
            "src.reader.strategies.playwright_strategy.browser_pool.get_browser",
            new=AsyncMock(return_value=browser),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch("src.reader.strategies.playwright_strategy.Stealth.apply_stealth_async", new=AsyncMock()),
        patch(
            "src.reader.strategies.playwright_strategy.ChallengeDetector.is_login_required",
            return_value=False,
        ),
        patch("src.reader.strategies.playwright_strategy.ChallengeDetector.is_blocked", return_value=False),
        patch(
            "src.reader.strategies.playwright_strategy.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
        patch("src.reader.strategies.playwright_strategy.proxy_provider.for_playwright", return_value=None),
        patch("src.reader.strategies.playwright_strategy.settings.SCROLL_ITERATIONS", 1),
        patch("src.reader.strategies.playwright_strategy.settings.SCROLL_STEP_PX", scroll_step),
    ):
        strategy = PlaywrightStrategy(lambda: "UA", _make_url_validator())
        await strategy.get_html("https://example.com/page")

    scroll_calls = [c for c in page.evaluate.await_args_list if "scrollBy" in str(c)]
    assert len(scroll_calls) == 1
    assert str(scroll_step) in str(scroll_calls[0])
