"""Tests for Fingerprint value object and anti-bot evasion wiring (task 4.1, 4.3)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.reader.fingerprint import Fingerprint, get_default_fingerprint
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
    return browser, context


def test_default_fingerprint_is_internally_consistent() -> None:
    """locale, timezone, and geolocation must all agree on the same real-world location."""
    fp = get_default_fingerprint()
    assert isinstance(fp, Fingerprint)
    assert fp.locale.startswith("en")
    assert "America" in fp.timezone_id or "US" in fp.timezone_id or "New_York" in fp.timezone_id
    lat = fp.geolocation["latitude"]
    lon = fp.geolocation["longitude"]
    # New York is roughly 40-41N, 73-75W
    assert 39.0 <= lat <= 42.0, f"latitude {lat!r} not in New York range"
    assert -76.0 <= lon <= -72.0, f"longitude {lon!r} not in New York range"


def test_fingerprint_ua_not_empty() -> None:
    fp = get_default_fingerprint()
    assert fp.user_agent
    assert "Chrome" in fp.user_agent or "Firefox" in fp.user_agent or "Safari" in fp.user_agent


def test_fingerprint_viewport_is_desktop() -> None:
    fp = get_default_fingerprint()
    assert fp.viewport_width >= 1280
    assert fp.viewport_height >= 720


@pytest.mark.asyncio
async def test_playwright_uses_fingerprint_locale_and_timezone() -> None:
    """PlaywrightStrategy must pass the Fingerprint's locale and timezone to new_context."""
    fp = get_default_fingerprint()
    browser, _ = _make_browser_and_context()
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
    ):
        strategy = PlaywrightStrategy(lambda: fp.user_agent, _make_url_validator(), fingerprint=fp)
        await strategy.get_html("https://example.com")

    call_kwargs = browser.new_context.call_args.kwargs
    assert call_kwargs["locale"] == fp.locale
    assert call_kwargs["timezone_id"] == fp.timezone_id
    assert call_kwargs["geolocation"] == fp.geolocation


@pytest.mark.asyncio
async def test_playwright_no_proxy_when_unconfigured() -> None:
    """When proxy is not configured, new_context must NOT receive a 'proxy' kwarg."""
    fp = get_default_fingerprint()
    browser, _ = _make_browser_and_context()
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
    ):
        strategy = PlaywrightStrategy(lambda: fp.user_agent, _make_url_validator(), fingerprint=fp)
        await strategy.get_html("https://example.com")

    call_kwargs = browser.new_context.call_args.kwargs
    assert "proxy" not in call_kwargs


@pytest.mark.asyncio
async def test_playwright_passes_proxy_when_configured() -> None:
    """When proxy is configured, new_context must receive the proxy kwarg."""
    fp = get_default_fingerprint()
    browser, _ = _make_browser_and_context()
    proxy = {"server": "socks5://proxy.internal:1080"}
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
        patch("src.reader.strategies.playwright_strategy.proxy_provider.for_playwright", return_value=proxy),
    ):
        strategy = PlaywrightStrategy(lambda: fp.user_agent, _make_url_validator(), fingerprint=fp)
        await strategy.get_html("https://example.com")

    call_kwargs = browser.new_context.call_args.kwargs
    assert call_kwargs.get("proxy") == proxy
