"""Tests for PlaywrightStrategy storage_state injection (task 2.3)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.reader.cloudflare.challenge_signals import ChallengeVerdict
from src.reader.strategies.playwright_strategy import PlaywrightStrategy
from src.validator.url_validator import URLValidator


def _accepted_clean_verdict() -> ChallengeVerdict:
    return ChallengeVerdict(
        score=0,
        threshold=100,
        signals=(),
        vendor=None,
        wall=False,
        has_content=True,
        intervention_type="captcha",
    )


def _make_url_validator() -> URLValidator:
    rules = MagicMock()
    rules.should_block.return_value = False
    return URLValidator(rules)


def _make_browser_and_context(
    html: str = "<html><body><article><p>" + "word " * 30 + "</p></article></body></html>",
) -> tuple[MagicMock, MagicMock]:
    goto_response = MagicMock(status=200)
    goto_response.all_headers = AsyncMock(return_value={})
    page = MagicMock()
    page.goto = AsyncMock(return_value=goto_response)
    page.content = AsyncMock(return_value=html)
    page.url = "https://linkedin.com/feed"
    page.wait_for_load_state = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.evaluate = AsyncMock(return_value=0)
    page.route = AsyncMock()

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()
    context.cookies = AsyncMock(return_value=[])
    context.route = AsyncMock()
    context.route_web_socket = None
    page.context = context

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    return browser, context


@pytest.mark.asyncio
async def test_playwright_injects_storage_state_when_present() -> None:
    """When a session is stored, new_context must be called with storage_state."""
    # given
    stored_state: dict[str, Any] = {
        "cookies": [{"name": "li_at", "value": "TOKEN", "domain": ".linkedin.com", "path": "/"}],
        "origins": [],
    }

    browser, context = _make_browser_and_context()

    # when
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
            "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "DefaultUA", _make_url_validator())
        await strategy.get_html("https://linkedin.com/feed")

    # then
    call_kwargs = browser.new_context.call_args.kwargs
    assert "storage_state" in call_kwargs
    assert call_kwargs["storage_state"] == stored_state


@pytest.mark.asyncio
async def test_playwright_omits_storage_state_when_absent() -> None:
    """When no session is stored, new_context must NOT receive storage_state."""
    # given
    browser, context = _make_browser_and_context()

    # when
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
            "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "DefaultUA", _make_url_validator())
        await strategy.get_html("https://example.com")

    # then
    call_kwargs = browser.new_context.call_args.kwargs
    assert "storage_state" not in call_kwargs


def _make_failing_browser(goto_error: Exception) -> tuple[MagicMock, MagicMock]:
    goto_response = MagicMock(status=200)
    goto_response.all_headers = AsyncMock(return_value={})
    page = MagicMock()
    page.goto = AsyncMock(side_effect=goto_error)
    page.content = AsyncMock(return_value="<html></html>")
    page.url = "https://example.com/redirect"
    page.wait_for_load_state = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.evaluate = AsyncMock(return_value=0)
    page.route = AsyncMock()

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()
    context.cookies = AsyncMock(return_value=[])
    context.route = AsyncMock()
    context.route_web_socket = None
    page.context = context

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    return browser, context


@pytest.mark.asyncio
async def test_playwright_refused_navigation_raises_unsafe_uri() -> None:
    # given
    from ascend_python_common.uri_guard import UnsafeUriError
    from playwright.async_api import Error as PlaywrightError

    browser, _ = _make_failing_browser(PlaywrightError("net::ERR_BLOCKED_BY_CLIENT"))

    # when / then
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
            "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
        patch(
            "src.reader.strategies.playwright_strategy.install_browser_guard",
            new=AsyncMock(return_value=["http://169.254.169.254/"]),
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "DefaultUA", _make_url_validator())
        with pytest.raises(UnsafeUriError):
            await strategy.get_html("https://example.com/redirect")


@pytest.mark.asyncio
async def test_playwright_plain_navigation_error_propagates() -> None:
    # given
    from playwright.async_api import Error as PlaywrightError

    browser, _ = _make_failing_browser(PlaywrightError("net::ERR_CONNECTION_REFUSED"))

    # when / then
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
            "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "DefaultUA", _make_url_validator())
        with pytest.raises(PlaywrightError):
            await strategy.get_html("https://example.com/down")


@pytest.mark.asyncio
async def test_playwright_recorded_navigation_raises_post_render() -> None:
    # given
    from ascend_python_common.uri_guard import UnsafeUriError

    browser, context = _make_browser_and_context()

    # when / then
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
            "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
        patch(
            "src.reader.strategies.browser_read.assess",
            return_value=_accepted_clean_verdict(),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.install_browser_guard",
            new=AsyncMock(return_value=["http://169.254.169.254/"]),
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "DefaultUA", _make_url_validator())
        with pytest.raises(UnsafeUriError):
            await strategy.get_html("https://example.com/article")


@pytest.mark.asyncio
async def test_playwright_restores_a_local_storage_only_login() -> None:
    """A saved login the site keeps only in localStorage reaches the browser context."""
    # given
    from src.reader.cloudflare.cookie_manager import PRODUCED_BY_NOVNC, CookieManager

    CookieManager._instance = None
    manager = CookieManager()
    manager._memory_store = {}
    manager.redis_client = None
    login: dict[str, Any] = {
        "cookies": [],
        "origins": [
            {"origin": "https://app.example.com", "localStorage": [{"name": "auth_token", "value": "TOKEN"}]}
        ],
    }
    await manager.save_storage_state(
        "https://app.example.com", login, "UA/1.0", None, PRODUCED_BY_NOVNC, replaces_login=True
    )
    browser, _context = _make_browser_and_context()

    # when
    with (
        patch(
            "src.reader.strategies.playwright_strategy.browser_pool.get_browser",
            new=AsyncMock(return_value=browser),
        ),
        patch("src.reader.strategies.playwright_strategy.cookie_manager", manager),
        patch("src.reader.strategies.playwright_strategy.Stealth.apply_stealth_async", new=AsyncMock()),
        patch(
            "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "DefaultUA", _make_url_validator())
        await strategy.get_html("https://app.example.com/dashboard")

    # then
    assert browser.new_context.call_args.kwargs["storage_state"] == login
