"""Tests for PlaywrightStrategy storage_state injection (task 2.3)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.reader.strategies.playwright_strategy import PlaywrightStrategy
from src.validator.url_validator import URLValidator


def _make_url_validator() -> URLValidator:
    rules = MagicMock()
    rules.should_block.return_value = False
    return URLValidator(rules)


def _make_browser_and_context(html: str = "<html><body>content</body></html>") -> tuple[MagicMock, MagicMock]:
    page = MagicMock()
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.content = AsyncMock(return_value=html)
    page.url = "https://linkedin.com/feed"
    page.wait_for_load_state = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.evaluate = AsyncMock(return_value=0)
    page.route = AsyncMock()

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    return browser, context


@pytest.mark.asyncio
async def test_playwright_injects_storage_state_when_present():
    """When a session is stored, new_context must be called with storage_state."""
    stored_state: dict[str, Any] = {
        "cookies": [{"name": "li_at", "value": "TOKEN", "domain": ".linkedin.com", "path": "/"}],
        "origins": [],
    }

    browser, context = _make_browser_and_context()
    with (
        patch(
            "src.reader.strategies.playwright_strategy.browser_pool.get_browser",
            new=AsyncMock(return_value=browser),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=stored_state),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.cookie_manager.get_user_agent",
            new=AsyncMock(return_value="UA/1.0"),
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
    ):
        strategy = PlaywrightStrategy(lambda: "DefaultUA", _make_url_validator())
        await strategy.get_html("https://linkedin.com/feed")

    call_kwargs = browser.new_context.call_args.kwargs
    assert "storage_state" in call_kwargs
    assert call_kwargs["storage_state"] == stored_state


@pytest.mark.asyncio
async def test_playwright_omits_storage_state_when_absent():
    """When no session is stored, new_context must NOT receive storage_state."""
    browser, context = _make_browser_and_context()
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
    ):
        strategy = PlaywrightStrategy(lambda: "DefaultUA", _make_url_validator())
        await strategy.get_html("https://example.com")

    call_kwargs = browser.new_context.call_args.kwargs
    assert "storage_state" not in call_kwargs
