from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.reader.strategies.novnc_strategy import _monitor_for_cookies


def _build_playwright_factory(*, cookies=None, page_url="http://test.com", goto_error=False):
    page = MagicMock()
    page.url = page_url
    page.goto = AsyncMock(side_effect=RuntimeError("nav") if goto_error else AsyncMock())
    page.evaluate = AsyncMock(return_value="UA")
    context = MagicMock()
    context.cookies = AsyncMock(return_value=cookies or [])
    context.new_page = AsyncMock(return_value=page)
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    factory = MagicMock()
    factory.__aenter__ = AsyncMock(return_value=pw)
    factory.__aexit__ = AsyncMock(return_value=False)

    return factory, browser, context, page


@pytest.mark.asyncio
async def test_monitor_breaks_early_when_url_changes():
    factory, browser, _ctx, _page = _build_playwright_factory(
        cookies=[{"name": "x", "value": "y"}], page_url="http://test.com/dashboard"
    )
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_session_data",
            new=AsyncMock(),
        ) as mock_save,
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
    ):
        await _monitor_for_cookies("http://test.com?login=1", "login")
    mock_save.assert_awaited()
    browser.close.assert_awaited()


@pytest.mark.asyncio
async def test_monitor_handles_goto_failure_and_still_polls():
    factory, browser, _ctx, _page = _build_playwright_factory(
        cookies=[{"name": "x", "value": "y"}],
        page_url="http://test.com/done",
        goto_error=True,
    )
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_session_data",
            new=AsyncMock(),
        ),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
    ):
        await _monitor_for_cookies("http://test.com?login=1", "login")
    browser.close.assert_awaited()


@pytest.mark.asyncio
async def test_monitor_swallows_transient_cookie_sync_error():
    factory, browser, context, _page = _build_playwright_factory(
        cookies=[{"name": "x", "value": "y"}], page_url="http://test.com/done"
    )
    context.cookies = AsyncMock(side_effect=[RuntimeError("transient"), []])
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_session_data",
            new=AsyncMock(),
        ),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
    ):
        await _monitor_for_cookies("http://test.com?login=1", "login")
    browser.close.assert_awaited()


@pytest.mark.asyncio
async def test_monitor_handles_outer_exception_and_closes_browser_in_finally():
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(side_effect=RuntimeError("launch failed"))
    factory = MagicMock()
    factory.__aenter__ = AsyncMock(return_value=pw)
    factory.__aexit__ = AsyncMock(return_value=False)
    with patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory):
        await _monitor_for_cookies("http://test.com", "captcha")


@pytest.mark.asyncio
async def test_monitor_browser_close_failure_is_tolerated():
    factory, browser, _ctx, _page = _build_playwright_factory(
        cookies=[{"name": "x", "value": "y"}], page_url="http://test.com/done"
    )
    browser.close = AsyncMock(side_effect=RuntimeError("close failed"))
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_session_data",
            new=AsyncMock(),
        ),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
    ):
        await _monitor_for_cookies("http://test.com?login=1", "login")
