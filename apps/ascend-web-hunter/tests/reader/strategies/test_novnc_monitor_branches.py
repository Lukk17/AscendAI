from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.reader.strategies.novnc_strategy import _monitor_for_cookies


def _sample_value(metric_name: str, **labels: str) -> float:
    from prometheus_client import REGISTRY

    return REGISTRY.get_sample_value(metric_name, labels) or 0.0


def _factory(page_url: str, *, goto_ok: bool = True):
    page = MagicMock()
    page.url = page_url
    page.goto = AsyncMock() if goto_ok else AsyncMock(side_effect=RuntimeError("nav"))
    page.evaluate = AsyncMock(return_value="UA")
    context = MagicMock()
    context.storage_state = AsyncMock(return_value={"cookies": [{"name": "k", "value": "v"}], "origins": []})
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
    """With NOVNC_TIMEOUT_SECONDS=0 the while loop body executes zero times - the
    timeout-exit branch (51->75) is the only path to the finally."""
    # given
    factory, browser, _ = _factory("http://test.com?login=1")

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 0),
    ):
        await _monitor_for_cookies("http://test.com?login=1", "login")

    # then
    browser.close.assert_awaited()


@pytest.mark.asyncio
async def test_monitor_records_timeout_outcome_metric_for_login():
    # given
    factory, browser, _ = _factory("http://novncmetrictimeout.com?login=1")
    before = _sample_value(
        "strategy_attempts_total",
        strategy="6-novnc-monitor",
        outcome="timeout",
        domain="novncmetrictimeout.com",
    )
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 0),
    ):
        await _monitor_for_cookies("http://novncmetrictimeout.com?login=1", "login")

    # when
    after = _sample_value(
        "strategy_attempts_total",
        strategy="6-novnc-monitor",
        outcome="timeout",
        domain="novncmetrictimeout.com",
    )

    # then
    assert after == before + 1.0


@pytest.mark.asyncio
async def test_monitor_records_rejected_outcome_when_timeout_still_blocked():
    """A captcha monitor that times out while the page is still a known block
    page must record 'rejected', not the more ambiguous 'timeout'."""
    # given
    page = MagicMock()
    page.url = "http://novncmetricrejected.com"
    page.goto = AsyncMock()
    page.evaluate = AsyncMock(return_value="UA")
    page.content = AsyncMock(return_value="<html><body>Just a moment...</body></html>")
    context = MagicMock()
    context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
    context.new_page = AsyncMock(return_value=page)
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    factory = MagicMock()
    factory.__aenter__ = AsyncMock(return_value=pw)
    factory.__aexit__ = AsyncMock(return_value=False)

    before = _sample_value(
        "strategy_attempts_total",
        strategy="6-novnc-monitor",
        outcome="rejected",
        domain="novncmetricrejected.com",
    )
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 0.05),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_COOKIE_SYNC_POLL_SECONDS", 0.01),
    ):
        await _monitor_for_cookies("http://novncmetricrejected.com", "captcha")

    # when
    after = _sample_value(
        "strategy_attempts_total",
        strategy="6-novnc-monitor",
        outcome="rejected",
        domain="novncmetricrejected.com",
    )

    # then
    assert after == before + 1.0
    browser.close.assert_awaited()


@pytest.mark.asyncio
async def test_monitor_continues_loop_when_url_did_not_change():
    """Page URL still matches the original URL -> branch 62->71 (continue) runs once,
    then the timeout window closes the loop."""
    # given
    factory, browser, _ = _factory("http://test.com?login=1")
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        raise RuntimeError("abort loop after one iteration")

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
        patch("src.reader.strategies.novnc_strategy.asyncio.sleep", side_effect=fake_sleep),
    ):
        await _monitor_for_cookies("http://test.com?login=1", "login")

    # then
    assert sleeps == [5.0]
