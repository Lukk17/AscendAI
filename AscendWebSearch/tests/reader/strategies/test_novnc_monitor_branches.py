from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.reader.strategies.novnc_strategy import _monitor_for_cookies


def _factory(page_url: str, *, goto_ok: bool = True):
    page = MagicMock()
    page.url = page_url
    page.goto = AsyncMock() if goto_ok else AsyncMock(side_effect=RuntimeError("nav"))
    page.evaluate = AsyncMock(return_value="UA")
    context = MagicMock()
    context.cookies = AsyncMock(return_value=[{"name": "k", "value": "v"}])
    context.new_page = AsyncMock(return_value=page)
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    factory = MagicMock()
    factory.__aenter__ = AsyncMock(return_value=pw)
    factory.__aexit__ = AsyncMock(return_value=False)

    return factory, browser, page


@pytest.mark.asyncio
async def test_monitor_exits_via_timeout_loop_condition():
    """With NOVNC_TIMEOUT_SECONDS=0 the while loop body executes zero times — the
    timeout-exit branch (51->75) is the only path to the finally."""
    factory, browser, _ = _factory("http://test.com?login=1")
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 0),
    ):
        await _monitor_for_cookies("http://test.com?login=1", "login")
    browser.close.assert_awaited()


@pytest.mark.asyncio
async def test_monitor_continues_loop_when_url_did_not_change():
    """Page URL still matches the original URL -> branch 62->71 (continue) runs once,
    then the timeout window closes the loop."""
    factory, browser, _ = _factory("http://test.com?login=1")
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        raise RuntimeError("abort loop after one iteration")

    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_session_data",
            new=AsyncMock(),
        ),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
        patch("src.reader.strategies.novnc_strategy.asyncio.sleep", side_effect=fake_sleep),
    ):
        await _monitor_for_cookies("http://test.com?login=1", "login")
    assert sleeps == [5.0]
