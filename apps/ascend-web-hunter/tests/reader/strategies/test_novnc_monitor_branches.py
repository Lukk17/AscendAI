"""Unit tests for the monitor timeout, outcome and loop branches."""

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.config import settings
from src.reader.cloudflare.challenge_signals import ChallengeVerdict
from src.reader.novnc.flow_registry import NoVNCFlow, flow_key_for
from src.reader.novnc.window_layout import rect_for_slot
from src.reader.strategies.novnc_strategy import _monitor_for_cookies


def _sample_value(metric_name: str, **labels: str) -> float:
    from prometheus_client import REGISTRY

    return REGISTRY.get_sample_value(metric_name, labels) or 0.0


def _make_flow(
    url: str,
    intervention_type: str,
    profile: str = "default",
    slot: int = 0,
) -> NoVNCFlow:
    window = rect_for_slot(
        slot,
        settings.NOVNC_DISPLAY_SIZE,
        (settings.NOVNC_WINDOW_WIDTH_PX, settings.NOVNC_WINDOW_HEIGHT_PX),
        settings.NOVNC_WINDOW_CASCADE_OFFSET_PX,
    )

    return NoVNCFlow(
        flow_id="b2c3d4e5f6a7",
        key=flow_key_for(url, profile),
        url=url,
        profile=profile,
        intervention_type=intervention_type,
        window=window,
        vnc_url="http://vnc/vnc.html?autoconnect=true",
        started_at=time.time(),
        request_id="test-request",
        lease_started=time.monotonic(),
    )


def _factory(page_url: str, *, goto_ok: bool = True) -> Any:
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
async def test_monitor_exits_via_timeout_loop_condition() -> None:
    """With NOVNC_TIMEOUT_SECONDS=0 the while loop body executes zero times - the
    timeout-exit branch (51->75) is the only path to the finally."""
    # given
    factory, browser, _ = _factory("http://test.com?login=1")
    flow = _make_flow("http://test.com?login=1", "login")

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch("src.reader.strategies.novnc_strategy.cookie_manager.clear_session") as mock_clear,
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 0),
    ):
        await _monitor_for_cookies(flow)

    # then
    browser.close.assert_awaited()
    mock_clear.assert_not_called()


@pytest.mark.asyncio
async def test_monitor_records_timeout_outcome_metric_for_login() -> None:
    # given
    factory, browser, _ = _factory("http://novncmetrictimeout.com?login=1")
    flow = _make_flow("http://novncmetrictimeout.com?login=1", "login")
    before = _sample_value(
        "strategy_attempts_total",
        strategy="6-novnc-monitor",
        outcome="timeout",
        domain="novncmetrictimeout.com",
    )
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch("src.reader.strategies.novnc_strategy.cookie_manager.clear_session") as mock_clear,
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 0),
    ):
        await _monitor_for_cookies(flow)

    # when
    after = _sample_value(
        "strategy_attempts_total",
        strategy="6-novnc-monitor",
        outcome="timeout",
        domain="novncmetrictimeout.com",
    )

    # then
    assert after == before + 1.0
    mock_clear.assert_not_called()


@pytest.mark.asyncio
async def test_monitor_records_rejected_outcome_when_timeout_still_blocked() -> None:
    """A captcha monitor that times out while the page is still a known block
    page must record 'rejected', not the more ambiguous 'timeout'."""
    # given
    page = MagicMock()
    page.url = "http://novncmetricrejected.com"
    page.goto = AsyncMock()
    page.evaluate = AsyncMock(return_value="UA")
    page.content = AsyncMock(return_value="<html><body><div id='cf-challenge-running'></div></body></html>")
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
    flow = _make_flow("http://novncmetricrejected.com", "captcha")

    before = _sample_value(
        "strategy_attempts_total",
        strategy="6-novnc-monitor",
        outcome="rejected",
        domain="novncmetricrejected.com",
    )
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch("src.reader.strategies.novnc_strategy.cookie_manager.clear_session") as mock_clear,
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 0.05),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_COOKIE_SYNC_POLL_SECONDS", 0.01),
        patch(
            "src.reader.strategies.novnc_strategy.assess",
            return_value=ChallengeVerdict(
                score=200,
                threshold=100,
                signals=(),
                vendor=None,
                wall=True,
                has_content=False,
                intervention_type="captcha",
            ),
        ),
    ):
        await _monitor_for_cookies(flow)

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
    mock_clear.assert_not_called()


@pytest.mark.asyncio
async def test_monitor_continues_loop_when_url_did_not_change() -> None:
    """Page URL still matches the original URL -> branch 62->71 (continue) runs once,
    then the timeout window closes the loop."""
    # given
    factory, browser, _ = _factory("http://test.com?login=1")
    flow = _make_flow("http://test.com?login=1", "login")
    sleeps = []

    async def fake_sleep(seconds: Any) -> None:
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
        await _monitor_for_cookies(flow)

    # then
    assert sleeps == [5.0]
