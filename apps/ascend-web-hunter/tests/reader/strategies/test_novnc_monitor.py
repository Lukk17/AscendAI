"""Unit tests for the per-flow NoVNC monitor: launch, teardown and outcomes."""

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.config import settings
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.novnc.flow_registry import NoVNCFlow, flow_key_for, novnc_flow_registry
from src.reader.novnc.window_layout import rect_for_slot
from src.reader.strategies.novnc_strategy import _monitor_for_cookies
from tests.reader.novnc.test_flow_registry import FakeRedis


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
        flow_id="a1b2c3d4e5f6",
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


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Any:
    fake = FakeRedis()
    monkeypatch.setattr(novnc_flow_registry, "_redis", fake)
    novnc_flow_registry._local.clear()
    yield fake
    novnc_flow_registry._local.clear()


def _build_playwright_factory(
    *, cookies: Any = None, page_url: str = "http://test.com", goto_error: Any = False
) -> Any:
    page = MagicMock()
    page.url = page_url
    page.goto = AsyncMock(side_effect=RuntimeError("nav") if goto_error else AsyncMock())
    page.content = AsyncMock(return_value="<html><body>ordinary page</body></html>")
    page.evaluate = AsyncMock(return_value="UA")
    context = MagicMock()
    # Monitor now calls storage_state(), not cookies()
    context.storage_state = AsyncMock(return_value={"cookies": cookies or [], "origins": []})
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
async def test_monitor_breaks_early_when_url_changes() -> None:
    # given
    factory, browser, _ctx, _page = _build_playwright_factory(
        cookies=[{"name": "x", "value": "y"}], page_url="http://test.com/dashboard"
    )
    flow = _make_flow("http://test.com?login=1", "login")

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch("src.reader.strategies.novnc_strategy.cookie_manager.clear_session") as mock_clear,
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
        patch(
            "src.reader.strategies.novnc_strategy.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
    ):
        await _monitor_for_cookies(flow)

    # then
    mock_save.assert_awaited()
    mock_clear.assert_not_called()
    browser.close.assert_awaited()


@pytest.mark.asyncio
async def test_monitor_handles_goto_failure_and_still_polls() -> None:
    # given
    factory, browser, _ctx, _page = _build_playwright_factory(
        cookies=[{"name": "x", "value": "y"}],
        page_url="http://test.com/done",
        goto_error=True,
    )
    flow = _make_flow("http://test.com?login=1", "login")

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
        patch(
            "src.reader.strategies.novnc_strategy.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
    ):
        await _monitor_for_cookies(flow)

    # then
    browser.close.assert_awaited()


@pytest.mark.asyncio
async def test_monitor_swallows_transient_cookie_sync_error() -> None:
    """When storage_state() raises transiently the loop swallows the error and keeps going."""
    # given
    factory, browser, context, _page = _build_playwright_factory(
        cookies=[{"name": "x", "value": "y"}], page_url="http://test.com/done"
    )
    # First call raises; the except block catches it and continues.
    # Second call succeeds and the URL change causes an early break.
    context.storage_state = AsyncMock(side_effect=[RuntimeError("transient"), {"cookies": [], "origins": []}])
    flow = _make_flow("http://test.com?login=1", "login")

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
        patch(
            "src.reader.strategies.novnc_strategy.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
        patch("src.reader.strategies.novnc_strategy.asyncio.sleep", new=AsyncMock()),
    ):
        await _monitor_for_cookies(flow)

    # then
    browser.close.assert_awaited()


@pytest.mark.asyncio
async def test_monitor_handles_outer_exception_and_closes_browser_in_finally() -> None:
    # given
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(side_effect=RuntimeError("launch failed"))
    factory = MagicMock()
    factory.__aenter__ = AsyncMock(return_value=pw)
    factory.__aexit__ = AsyncMock(return_value=False)
    flow = _make_flow("http://test.com", "captcha")

    # when / then
    with patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory):
        await _monitor_for_cookies(flow)


@pytest.mark.asyncio
async def test_monitor_browser_close_failure_is_tolerated() -> None:
    # given
    factory, browser, _ctx, _page = _build_playwright_factory(
        cookies=[{"name": "x", "value": "y"}], page_url="http://test.com/done"
    )
    browser.close = AsyncMock(side_effect=RuntimeError("close failed"))
    flow = _make_flow("http://test.com?login=1", "login")

    # when / then
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
        patch(
            "src.reader.strategies.novnc_strategy.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
    ):
        await _monitor_for_cookies(flow)


@pytest.mark.asyncio
async def test_two_flows_launch_without_shared_port_and_with_distinct_positions() -> None:
    """Neither launch carries 9222, both carry port 0 on loopback, and their
    --window-position values differ."""
    # given
    factory_a, _, _, _ = _build_playwright_factory(page_url="http://site-a.com/done")
    factory_b, _, _, _ = _build_playwright_factory(page_url="http://site-b.com/done")
    flow_a = _make_flow("https://site-a.com/1", "captcha", slot=0)
    flow_b = _make_flow("https://site-b.com/2", "captcha", slot=1)

    # when
    with (
        patch(
            "src.reader.strategies.novnc_strategy.async_playwright",
            side_effect=[factory_a, factory_b],
        ),
        patch(
            "src.reader.strategies.novnc_strategy._poll_once",
            new=AsyncMock(return_value=(True, False)),
        ),
    ):
        await asyncio.gather(_monitor_for_cookies(flow_a), _monitor_for_cookies(flow_b))

    # then
    launch_args_a = factory_a.__aenter__.return_value.chromium.launch.await_args
    launch_args_b = factory_b.__aenter__.return_value.chromium.launch.await_args
    argv_a = launch_args_a.kwargs["args"]
    argv_b = launch_args_b.kwargs["args"]
    assert not any("9222" in arg for arg in argv_a)
    assert not any("9222" in arg for arg in argv_b)
    assert "--remote-debugging-port=0" in argv_a
    assert "--remote-debugging-port=0" in argv_b
    assert "--remote-debugging-address=127.0.0.1" in argv_a
    assert "--remote-debugging-address=127.0.0.1" in argv_b
    position_a = next(arg for arg in argv_a if arg.startswith("--window-position="))
    position_b = next(arg for arg in argv_b if arg.startswith("--window-position="))
    assert position_a != position_b
    size_a = next(arg for arg in argv_a if arg.startswith("--window-size="))
    assert size_a == f"--window-size={flow_a.window.width},{flow_a.window.height}"


@pytest.mark.asyncio
async def test_monitor_close_failure_still_releases_slot_and_records_outcome() -> None:
    """A browser that refuses to close must not skip the slot release or the
    outcome metric."""
    # given
    factory, browser, _ctx, _page = _build_playwright_factory(
        cookies=[{"name": "x", "value": "y"}], page_url="http://slot-site.com/done"
    )
    browser.close = AsyncMock(side_effect=RuntimeError("close failed"))
    flow = await novnc_flow_registry.reserve(
        key=flow_key_for("https://slot-site.com/1", "default"),
        url="https://slot-site.com/1",
        profile="default",
        intervention_type="login",
    )
    before = _sample_value(
        "strategy_attempts_total",
        strategy="6-novnc-monitor",
        outcome="resolved",
        domain="slot-site.com",
    )

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy._poll_once",
            new=AsyncMock(return_value=(True, False)),
        ),
    ):
        await _monitor_for_cookies(flow)

    # then
    after = _sample_value(
        "strategy_attempts_total",
        strategy="6-novnc-monitor",
        outcome="resolved",
        domain="slot-site.com",
    )
    assert novnc_flow_registry.local() == []
    assert after == before + 1.0


@pytest.mark.asyncio
async def test_cancelling_monitor_closes_browser_frees_slot_and_records_cancelled() -> None:
    """Cancelling a running monitor closes its browser, frees its slot,
    records the cancelled outcome, and surfaces CancelledError to the caller."""
    # given
    factory, browser, _ctx, _page = _build_playwright_factory(
        cookies=[{"name": "x", "value": "y"}], page_url="http://cancel-site.com/1"
    )
    flow = await novnc_flow_registry.reserve(
        key=flow_key_for("https://cancel-site.com/1", "default"),
        url="https://cancel-site.com/1",
        profile="default",
        intervention_type="captcha",
    )
    before = _sample_value(
        "strategy_attempts_total",
        strategy="6-novnc-monitor",
        outcome="cancelled",
        domain="cancel-site.com",
    )

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch("src.reader.strategies.novnc_strategy.cookie_manager.clear_session") as mock_clear,
        patch(
            "src.reader.strategies.novnc_strategy._poll_once",
            new=AsyncMock(return_value=(False, True)),
        ),
    ):
        task = asyncio.create_task(_monitor_for_cookies(flow))
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    # then
    after = _sample_value(
        "strategy_attempts_total",
        strategy="6-novnc-monitor",
        outcome="cancelled",
        domain="cancel-site.com",
    )
    browser.close.assert_awaited()
    assert novnc_flow_registry.local() == []
    assert after == before + 1.0
    mock_clear.assert_not_called()


@pytest.mark.asyncio
async def test_capture_survives_later_failure_of_own_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    """A capture already persisted must still be present and unmodified after
    a later failure of the flow that made it, and teardown never clears."""

    # given
    class _PollBlowUp(BaseException):
        """An unexpected death inside the poll loop, distinct from cancellation."""

    async def spy_clear(*args: Any, **kwargs: Any) -> bool:
        clear_calls.append((args, kwargs))

        return await real_clear(*args, **kwargs)

    monkeypatch.setattr(cookie_manager, "redis_client", None)
    real_clear = cookie_manager.clear_session
    clear_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(cookie_manager, "clear_session", spy_clear)
    saved_state = {"cookies": [{"name": "li_at", "value": "TOKEN"}], "origins": []}
    page = MagicMock()
    page.url = "https://persist-site.com/login"
    page.goto = AsyncMock()
    page.evaluate = AsyncMock(return_value="UA")
    context = MagicMock()
    context.storage_state = AsyncMock(side_effect=[saved_state, _PollBlowUp()])
    context.new_page = AsyncMock(return_value=page)
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    factory = MagicMock()
    factory.__aenter__ = AsyncMock(return_value=pw)
    factory.__aexit__ = AsyncMock(return_value=False)
    flow = _make_flow("https://persist-site.com/login", "login")

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch("src.reader.strategies.novnc_strategy.asyncio.sleep", new=AsyncMock()),
        patch(
            "src.reader.strategies.novnc_strategy.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
    ):
        with pytest.raises(_PollBlowUp):
            await _monitor_for_cookies(flow)
        record = await cookie_manager.get_storage_state(flow.url, flow.profile)

    # then
    assert record is not None
    assert record["cookies"] == saved_state["cookies"]
    assert clear_calls == []


def _outcome_factory(page_url: str, content: str) -> Any:
    page = MagicMock()
    page.url = page_url
    page.goto = AsyncMock()
    page.content = AsyncMock(return_value=content)
    page.evaluate = AsyncMock(return_value="UA")
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

    return factory


def _wall_verdict() -> Any:
    from src.reader.cloudflare.challenge_signals import ChallengeVerdict

    return ChallengeVerdict(
        score=200,
        threshold=100,
        signals=(),
        vendor=None,
        wall=True,
        has_content=False,
        intervention_type="captcha",
    )


def _content_verdict() -> Any:
    from src.reader.cloudflare.challenge_signals import ChallengeVerdict

    return ChallengeVerdict(
        score=0,
        threshold=100,
        signals=(),
        vendor=None,
        wall=False,
        has_content=True,
        intervention_type="captcha",
    )


def _delta(outcome: str, domain: str, before: float) -> float:
    return (
        _sample_value("strategy_attempts_total", strategy="6-novnc-monitor", outcome=outcome, domain=domain)
        - before
    )


@pytest.mark.asyncio
async def test_resolved_outcome_maps_to_accepted_poll() -> None:
    # given
    domain = "outcome-resolved.com"
    before = _sample_value(
        "strategy_attempts_total", strategy="6-novnc-monitor", outcome="resolved", domain=domain
    )
    factory = _outcome_factory("https://outcome-resolved.com/", "<html><body>ok</body></html>")

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ),
        patch("src.reader.strategies.novnc_strategy.assess", return_value=_content_verdict()),
    ):
        await _monitor_for_cookies(_make_flow("https://outcome-resolved.com/", "captcha"))

    # then
    assert _delta("resolved", domain, before) == 1.0


@pytest.mark.asyncio
async def test_timeout_outcome_maps_to_unrun_loop() -> None:
    # given
    domain = "outcome-timeout.com"
    before = _sample_value(
        "strategy_attempts_total", strategy="6-novnc-monitor", outcome="timeout", domain=domain
    )
    factory = _outcome_factory("https://outcome-timeout.com/?login=1", "<html><body>ok</body></html>")

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ),
        patch("src.reader.strategies.novnc_strategy.cookie_manager.clear_session") as mock_clear,
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 0),
    ):
        await _monitor_for_cookies(_make_flow("https://outcome-timeout.com/?login=1", "login"))

    # then
    assert _delta("timeout", domain, before) == 1.0
    mock_clear.assert_not_called()


@pytest.mark.asyncio
async def test_rejected_outcome_maps_to_blocked_timeout() -> None:
    # given
    domain = "outcome-rejected.com"
    before = _sample_value(
        "strategy_attempts_total", strategy="6-novnc-monitor", outcome="rejected", domain=domain
    )
    factory = _outcome_factory("https://outcome-rejected.com/", "<html><body>wall</body></html>")

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ),
        patch("src.reader.strategies.novnc_strategy.cookie_manager.clear_session") as mock_clear,
        patch("src.reader.strategies.novnc_strategy.assess", return_value=_wall_verdict()),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 0.05),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_COOKIE_SYNC_POLL_SECONDS", 0.01),
    ):
        await _monitor_for_cookies(_make_flow("https://outcome-rejected.com/", "captcha"))

    # then
    assert _delta("rejected", domain, before) == 1.0
    mock_clear.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_outcome_maps_to_cancelled_monitor() -> None:
    # given
    domain = "outcome-cancelled.com"
    before = _sample_value(
        "strategy_attempts_total", strategy="6-novnc-monitor", outcome="cancelled", domain=domain
    )
    factory = _outcome_factory("https://outcome-cancelled.com/", "<html><body>wall</body></html>")

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ),
        patch("src.reader.strategies.novnc_strategy.cookie_manager.clear_session") as mock_clear,
        patch("src.reader.strategies.novnc_strategy.assess", return_value=_wall_verdict()),
    ):
        task = asyncio.create_task(
            _monitor_for_cookies(_make_flow("https://outcome-cancelled.com/", "captcha"))
        )
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    mock_clear.assert_not_called()

    # then
    assert _delta("cancelled", domain, before) == 1.0


@pytest.mark.asyncio
async def test_monitor_log_lines_carry_flow_id_and_slot_but_no_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every monitor log line names the flow and its slot, and no line leaks
    the cookie value or the page content the monitor read."""
    # given
    from src.reader.cloudflare.challenge_signals import ChallengeVerdict

    planted_cookie_value = "SECRET_COOKIE_VALUE_abc123"
    planted_fragment = "SECRET_PAGE_FRAGMENT_xyz"
    page = MagicMock()
    page.url = "https://secret-site.com/"
    page.goto = AsyncMock()
    page.content = AsyncMock(return_value=f"<html><body>article {planted_fragment}</body></html>")
    page.evaluate = AsyncMock(return_value="UA")
    context = MagicMock()
    context.storage_state = AsyncMock(
        return_value={"cookies": [{"name": "li_at", "value": planted_cookie_value}], "origins": []}
    )
    context.new_page = AsyncMock(return_value=page)
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    factory = MagicMock()
    factory.__aenter__ = AsyncMock(return_value=pw)
    factory.__aexit__ = AsyncMock(return_value=False)
    flow = _make_flow("https://secret-site.com/", "captcha")

    # when
    with (
        caplog.at_level("DEBUG", logger="src.reader.strategies.novnc_strategy"),
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ),
        patch(
            "src.reader.strategies.novnc_strategy.assess",
            return_value=ChallengeVerdict(
                score=0,
                threshold=100,
                signals=(),
                vendor=None,
                wall=False,
                has_content=True,
                intervention_type="captcha",
            ),
        ),
    ):
        await _monitor_for_cookies(flow)

    # then
    lines = [
        record.getMessage()
        for record in caplog.records
        if record.name == "src.reader.strategies.novnc_strategy"
    ]
    assert lines, "the monitor must log its flow"
    for line in lines:
        assert flow.flow_id in line
        assert f"slot={flow.window.slot}" in line
    assert not any(planted_cookie_value in record.getMessage() for record in caplog.records)
    assert not any(planted_fragment in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_poll_helpers_without_flow_resolve_with_plain_url_log() -> None:
    """Direct poll calls without a flow (proactive checks outside a monitor)
    resolve the same way and log the plain URL."""
    # given
    from src.reader.strategies.novnc_strategy import _poll_captcha, _poll_login

    page = MagicMock()
    page.url = "https://direct-site.com/other"
    page.content = AsyncMock(return_value="<html><body>wall</body></html>")
    page.evaluate = AsyncMock(return_value="UA")
    storage_with_clearance = {"cookies": [{"name": "cf_clearance", "value": "abc"}], "origins": []}

    # when
    with (
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ),
        patch(
            "src.reader.strategies.novnc_strategy.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
    ):
        captcha_resolved, _ = await _poll_captcha(
            page, "https://direct-site.com/", storage_with_clearance, None
        )
        login_resolved = await _poll_login(page, "https://direct-site.com/", storage_with_clearance, None)

    # then
    assert captcha_resolved is True
    assert login_resolved is True
