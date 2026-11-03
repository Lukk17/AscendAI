"""Unit tests for the browser-death watch: a dead Chromium frees its slot fast."""

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.config import settings
from src.reader.novnc.flow_registry import NoVNCFlow, flow_key_for, novnc_flow_registry
from src.reader.novnc.window_layout import rect_for_slot
from src.reader.strategies.novnc_strategy import _monitor_for_cookies
from tests.reader.novnc.test_flow_registry import FakeRedis


def _sample_value(metric_name: str, **labels: str) -> float:
    from prometheus_client import REGISTRY

    return REGISTRY.get_sample_value(metric_name, labels) or 0.0


def _make_flow(url: str, intervention_type: str) -> NoVNCFlow:
    window = rect_for_slot(
        0,
        settings.NOVNC_DISPLAY_SIZE,
        (settings.NOVNC_WINDOW_WIDTH_PX, settings.NOVNC_WINDOW_HEIGHT_PX),
        settings.NOVNC_WINDOW_CASCADE_OFFSET_PX,
    )

    return NoVNCFlow(
        flow_id="c3d4e5f6a7b8",
        key=flow_key_for(url, "default"),
        url=url,
        profile="default",
        intervention_type=intervention_type,
        window=window,
        vnc_url="http://vnc/vnc.html?autoconnect=true",
        started_at=time.time(),
        request_id="test-request",
        lease_started=time.monotonic(),
    )


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Any:
    fake = FakeRedis()
    monkeypatch.setattr(novnc_flow_registry, "_redis", fake)
    novnc_flow_registry._local.clear()
    yield fake
    novnc_flow_registry._local.clear()


def _build_factory(
    *,
    connected: bool = True,
    page_closed: bool = False,
    poll_error: Exception | None = None,
) -> Any:
    page = MagicMock()
    page.url = "https://dead-site.com/"
    page.goto = AsyncMock()
    page.content = AsyncMock(return_value="<html><body><div id='cf-challenge-running'></div></body></html>")
    page.evaluate = AsyncMock(return_value="UA")
    page.is_closed = MagicMock(return_value=page_closed)
    context = MagicMock()
    context.route = AsyncMock()
    context.route_web_socket = None
    if poll_error is not None:
        context.storage_state = AsyncMock(side_effect=poll_error)
    else:
        context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
    context.new_page = AsyncMock(return_value=page)
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    browser.is_connected = MagicMock(return_value=connected)
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    factory = MagicMock()
    factory.__aenter__ = AsyncMock(return_value=pw)
    factory.__aexit__ = AsyncMock(return_value=False)

    return factory


async def _run_monitor_until_free(flow: NoVNCFlow, factory: Any, domain: str) -> float:
    before = _sample_value(
        "strategy_attempts_total",
        strategy="6-novnc-monitor",
        outcome="browser_closed",
        domain=domain,
    )
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 600),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_COOKIE_SYNC_POLL_SECONDS", 0.01),
    ):
        await asyncio.wait_for(_monitor_for_cookies(flow), timeout=10)

    return (
        _sample_value(
            "strategy_attempts_total",
            strategy="6-novnc-monitor",
            outcome="browser_closed",
            domain=domain,
        )
        - before
    )


@pytest.mark.asyncio
async def test_dead_connection_frees_slot_without_waiting_for_timeout() -> None:
    # given a reserved flow whose Chromium connection is already down
    url = "https://dead-conn.com/"
    flow = await novnc_flow_registry.reserve(
        key=flow_key_for(url, "default"),
        url=url,
        profile="default",
        intervention_type="captcha",
    )
    factory = _build_factory(connected=False)

    # when the monitor runs with a long timeout
    delta = await _run_monitor_until_free(flow, factory, "dead-conn.com")

    # then the slot is free and the browser_closed outcome is recorded
    assert novnc_flow_registry.local() == []
    assert delta == 1.0


@pytest.mark.asyncio
async def test_closed_page_frees_slot_without_waiting_for_timeout() -> None:
    # given a reserved flow whose only page is already closed
    url = "https://dead-page.com/"
    flow = await novnc_flow_registry.reserve(
        key=flow_key_for(url, "default"),
        url=url,
        profile="default",
        intervention_type="captcha",
    )
    factory = _build_factory(page_closed=True)

    # when the monitor runs with a long timeout
    delta = await _run_monitor_until_free(flow, factory, "dead-page.com")

    # then the slot is free and the browser_closed outcome is recorded
    assert novnc_flow_registry.local() == []
    assert delta == 1.0


@pytest.mark.asyncio
async def test_browser_error_mid_poll_frees_slot_without_waiting_for_timeout() -> None:
    # given a reserved flow whose polls fail with a browser-gone error
    url = "https://dead-poll.com/"
    flow = await novnc_flow_registry.reserve(
        key=flow_key_for(url, "default"),
        url=url,
        profile="default",
        intervention_type="captcha",
    )
    factory = _build_factory(poll_error=RuntimeError("Target closed"))

    # when the monitor runs with a long timeout
    delta = await _run_monitor_until_free(flow, factory, "dead-poll.com")

    # then the slot is free and the browser_closed outcome is recorded
    assert novnc_flow_registry.local() == []
    assert delta == 1.0
