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
from src.reader.strategies.main_frame_response import MainFrameResponses
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
    page.goto = AsyncMock(side_effect=RuntimeError("nav")) if goto_error else AsyncMock(return_value=None)
    page.content = AsyncMock(return_value="<html><body>ordinary page</body></html>")
    page.evaluate = AsyncMock(return_value="UA")
    page.locator = MagicMock(return_value=MagicMock(count=AsyncMock(return_value=0)))
    context = MagicMock()
    context.route = AsyncMock()
    context.route_web_socket = None
    context.storage_state = AsyncMock(return_value={"cookies": cookies or [], "origins": []})
    context.cookies = AsyncMock(return_value=context.storage_state.return_value["cookies"])
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


_LOGIN_FORM = "<html><body><form><input type='password' name='pw'></form></body></html>"
_ORDINARY_PAGE = "<html><body>ordinary page</body></html>"


def _script_login(context: Any, page: Any, *, first_state_error: bool = False) -> None:
    """The first poll sees a login form without auth cookies, every later poll
    an ordinary page with a fresh auth cookie: a login the human completed."""
    contents = iter([_LOGIN_FORM])
    served: list[str] = []

    def _next_content() -> str:
        served.append(next(contents, _ORDINARY_PAGE))

        return served[-1]

    def _visible_password_inputs(_selector: str) -> MagicMock:
        return MagicMock(count=AsyncMock(return_value=int(served[-1] == _LOGIN_FORM)))

    page.content = AsyncMock(side_effect=_next_content)
    page.locator = MagicMock(side_effect=_visible_password_inputs)
    states: list[Any] = [RuntimeError("transient")] if first_state_error else []
    states.append({"cookies": [], "origins": []})
    pending = iter(states)

    polled: list[dict[str, Any]] = []

    def _next_cookies() -> Any:
        state = next(pending, {"cookies": [{"name": "x", "value": "y", "domain": "test.com"}], "origins": []})
        if isinstance(state, BaseException):
            raise state
        polled.append(state)

        return state["cookies"]

    context.cookies = AsyncMock(side_effect=_next_cookies)
    context.storage_state = AsyncMock(side_effect=lambda: polled[-1])


@pytest.mark.asyncio
async def test_monitor_breaks_early_when_url_changes() -> None:
    # given
    factory, browser, ctx, page = _build_playwright_factory(page_url="http://test.com/dashboard")
    _script_login(ctx, page)
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
        patch("src.reader.strategies.novnc_strategy.asyncio.sleep", new=AsyncMock()),
    ):
        await _monitor_for_cookies(flow)

    # then
    mock_save.assert_awaited()
    mock_clear.assert_not_called()
    browser.close.assert_awaited()


@pytest.mark.asyncio
async def test_monitor_handles_goto_failure_and_still_polls() -> None:
    # given
    factory, browser, ctx, page = _build_playwright_factory(page_url="http://test.com/done", goto_error=True)
    _script_login(ctx, page)
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
async def test_monitor_swallows_transient_cookie_sync_error() -> None:
    """When the cookie read raises transiently the loop swallows the error and keeps going."""
    # given
    factory, browser, context, page = _build_playwright_factory(page_url="http://test.com/done")
    _script_login(context, page, first_state_error=True)
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
    factory, browser, ctx, page = _build_playwright_factory(page_url="http://test.com/done")
    _script_login(ctx, page)
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
        patch("src.reader.strategies.novnc_strategy.asyncio.sleep", new=AsyncMock()),
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
            new=AsyncMock(return_value=("resolved", False)),
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
            new=AsyncMock(return_value=("resolved", False)),
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
async def test_cancel_during_browser_close_still_frees_slot_and_records_outcome() -> None:
    """A cancel that lands while the browser closes must not skip the slot
    release or the outcome metric."""
    # given
    factory, browser, _ctx, _page = _build_playwright_factory(page_url="http://close-cancel.com/1")
    browser.close = AsyncMock(side_effect=asyncio.CancelledError())
    flow = await novnc_flow_registry.reserve(
        key=flow_key_for("https://close-cancel.com/1", "default"),
        url="https://close-cancel.com/1",
        profile="default",
        intervention_type="captcha",
    )
    before = _sample_value(
        "strategy_attempts_total", strategy="6-novnc-monitor", outcome="resolved", domain="close-cancel.com"
    )

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy._poll_once",
            new=AsyncMock(return_value=("resolved", False)),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await _monitor_for_cookies(flow)

    # then
    after = _sample_value(
        "strategy_attempts_total", strategy="6-novnc-monitor", outcome="resolved", domain="close-cancel.com"
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
            new=AsyncMock(return_value=(None, True)),
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
        """An unexpected death in the flow's teardown, distinct from cancellation."""

    async def spy_clear(*args: Any, **kwargs: Any) -> bool:
        clear_calls.append((args, kwargs))

        return await real_clear(*args, **kwargs)

    monkeypatch.setattr(cookie_manager, "redis_client", None)
    real_clear = cookie_manager.clear_session
    clear_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(cookie_manager, "clear_session", spy_clear)
    saved_state = {
        "cookies": [{"name": "li_at", "value": "TOKEN", "domain": ".persist-site.com"}],
        "origins": [],
    }
    page = MagicMock()
    page.url = "https://persist-site.com/login"
    page.goto = AsyncMock(return_value=None)
    page.content = AsyncMock(side_effect=[_LOGIN_FORM, _ORDINARY_PAGE])
    page.evaluate = AsyncMock(return_value="UA")
    page.locator = MagicMock(return_value=MagicMock(count=AsyncMock(side_effect=[1, 0])))
    context = MagicMock()
    context.route = AsyncMock()
    context.route_web_socket = None
    context.storage_state = AsyncMock(side_effect=[{"cookies": [], "origins": []}, saved_state])
    context.cookies = AsyncMock(side_effect=[[], saved_state["cookies"]])
    context.new_page = AsyncMock(return_value=page)
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock(side_effect=_PollBlowUp())
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
    page.goto = AsyncMock(return_value=None)
    page.content = AsyncMock(return_value=content)
    page.evaluate = AsyncMock(return_value="UA")
    context = MagicMock()
    context.route = AsyncMock()
    context.route_web_socket = None
    context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
    context.cookies = AsyncMock(return_value=context.storage_state.return_value["cookies"])
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
    page.goto = AsyncMock(return_value=None)
    page.content = AsyncMock(return_value=f"<html><body>article {planted_fragment}</body></html>")
    page.evaluate = AsyncMock(return_value="UA")
    context = MagicMock()
    context.route = AsyncMock()
    context.route_web_socket = None
    context.storage_state = AsyncMock(
        return_value={"cookies": [{"name": "li_at", "value": planted_cookie_value}], "origins": []}
    )
    context.cookies = AsyncMock(return_value=context.storage_state.return_value["cookies"])
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
async def test_poll_helpers_resolve_a_cleared_captcha_and_a_completed_login() -> None:
    """An accepted page resolves a captcha poll, and a login poll resolves
    once a login wall of the site was seen and a new site cookie followed it."""
    # given
    from src.reader.strategies.novnc_strategy import _FlowProgress, _poll_captcha, _poll_login

    page = MagicMock()
    page.url = "https://direct-site.com/other"
    page.content = AsyncMock(return_value=_READABLE_PAGE)
    page.evaluate = AsyncMock(return_value="UA")
    page.locator = MagicMock(return_value=MagicMock(count=AsyncMock(return_value=0)))
    storage_with_clearance = {
        "cookies": [{"name": "cf_clearance", "value": "abc", "domain": ".direct-site.com"}],
        "origins": [],
    }
    storage_with_login = {
        "cookies": [{"name": "li_at", "value": "TOKEN", "domain": ".direct-site.com"}],
        "origins": [],
    }
    context = MagicMock()
    context.storage_state = AsyncMock(return_value=storage_with_login)
    captcha_flow = _make_flow("https://direct-site.com/", "captcha")
    login_flow = _make_flow("https://direct-site.com/", "login")
    progress = _FlowProgress(site="direct-site.com", login_wall_seen=True, login_wall_entries=frozenset())

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
            page,
            MainFrameResponses(page),
            context,
            storage_with_clearance,
            captcha_flow,
            _FlowProgress(site="direct-site.com"),
        )
        page.content = AsyncMock(return_value=_ORDINARY_PAGE)
        login_resolved = await _poll_login(
            page, MainFrameResponses(page), context, storage_with_login, login_flow, progress
        )

    # then
    assert captcha_resolved is True
    assert login_resolved == "resolved"


# ---------------------------------------------------------------------------
# The monitor's timeout and the lease measure from the same moment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monitor_deadline_runs_from_the_flow_lease_start() -> None:
    """Browser launch and the first navigation spend the flow's own time: a
    flow whose lease started almost a timeout ago stops polling at once."""
    # given
    factory, browser, _ctx, _page = _build_playwright_factory()
    flow = _make_flow("http://late-site.com", "captcha")

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_COOKIE_SYNC_POLL_SECONDS", 0.01),
        patch("src.reader.strategies.novnc_strategy._poll_once", new=AsyncMock(return_value=(None, False))),
    ):
        flow.lease_started = time.monotonic() - 59.8
        await asyncio.wait_for(_monitor_for_cookies(flow), timeout=5.0)

    # then
    browser.close.assert_awaited()


@pytest.mark.asyncio
async def test_initial_navigation_is_bounded_by_the_time_left_on_the_flow() -> None:
    # given
    factory, _browser, _ctx, page = _build_playwright_factory()
    flow = _make_flow("http://late-nav.com", "captcha")

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
        patch(
            "src.reader.strategies.novnc_strategy._poll_once", new=AsyncMock(return_value=("resolved", False))
        ),
    ):
        flow.lease_started = time.monotonic() - 50.0
        await _monitor_for_cookies(flow)

    # then
    timeout_ms = page.goto.call_args.kwargs["timeout"]
    assert 0 < timeout_ms <= 10_000


@pytest.mark.asyncio
async def test_monitor_never_sleeps_past_its_deadline() -> None:
    # given
    factory, _browser, _ctx, _page = _build_playwright_factory()
    flow = _make_flow("http://short-site.com", "captcha")
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def recording_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        await real_sleep(0)

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_COOKIE_SYNC_POLL_SECONDS", 5.0),
        patch("src.reader.strategies.novnc_strategy._poll_once", new=AsyncMock(return_value=(None, False))),
        patch("src.reader.strategies.novnc_strategy.asyncio.sleep", side_effect=recording_sleep),
    ):
        flow.lease_started = time.monotonic() - 59.5
        await asyncio.wait_for(_monitor_for_cookies(flow), timeout=5.0)

    # then
    assert sleeps
    assert all(seconds <= 0.5 for seconds in sleeps)


# ---------------------------------------------------------------------------
# Log lines of a poll carry the flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_log_lines_carry_flow_id_and_slot(caplog: pytest.LogCaptureFixture) -> None:
    """The verdict line of a captcha poll and the transient-error line both
    name the flow and its slot."""
    # given
    factory, _browser, context, _page = _build_playwright_factory()
    context.cookies = AsyncMock(side_effect=[RuntimeError("transient"), [], []])
    flow = _make_flow("http://log-poll.com", "captcha", slot=2)

    # when
    with (
        caplog.at_level("DEBUG"),
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 0.2),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_COOKIE_SYNC_POLL_SECONDS", 0.01),
    ):
        await _monitor_for_cookies(flow)

    # then
    transient = [r.getMessage() for r in caplog.records if "Transient error" in r.getMessage()]
    verdicts = [r.getMessage() for r in caplog.records if "Challenge verdict" in r.getMessage()]
    assert transient
    assert verdicts
    for line in transient + verdicts:
        assert "flow_id=a1b2c3d4e5f6" in line
        assert "slot=2" in line


@pytest.mark.asyncio
async def test_novnc_launches_chromium_with_the_guard_arguments_and_installs_the_chromium_guard() -> None:
    # given
    from src.reader.browser_guard import BrowserFamily, chromium_guard_args

    factory, _, _, _ = _build_playwright_factory(page_url="http://site-a.com/done")
    flow = _make_flow("https://site-a.com/1", "captcha", slot=0)
    install = AsyncMock(return_value=[])

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch("src.reader.strategies.novnc_strategy.install_browser_guard", new=install),
        patch(
            "src.reader.strategies.novnc_strategy._poll_once",
            new=AsyncMock(return_value=("resolved", False)),
        ),
    ):
        await _monitor_for_cookies(flow)

    # then
    argv = factory.__aenter__.return_value.chromium.launch.await_args.kwargs["args"]
    guard_args = list(chromium_guard_args())
    assert argv[-len(guard_args) :] == guard_args
    assert install.await_args is not None
    assert install.await_args.kwargs["family"] is BrowserFamily.CHROMIUM


_FAILED_NAVIGATION_ADDRESS = "chrome-error://chromewebdata/"
_NEVER_NAVIGATED_ADDRESS = "about:blank"
_LOADED_ADDRESS = "http://test.com/"
_CHALLENGE_PAGE = "<html><body><div id='cf-challenge-running'></div></body></html>"
_READABLE_TEXT = " ".join(f"Sentence number {index} of a page a person can read." for index in range(40))
_READABLE_PAGE = f"<html><body><article><h1>Title</h1><p>{_READABLE_TEXT}</p></article></body></html>"
_CLEARANCE_COOKIE = {"name": "cf_clearance", "value": "stored", "domain": "test.com", "path": "/"}
_SHORT_TIMEOUT_SECONDS = 0.05
_SHORT_POLL_SECONDS = 0.01


@pytest.mark.parametrize("address", [_FAILED_NAVIGATION_ADDRESS, _NEVER_NAVIGATED_ADDRESS])
@pytest.mark.parametrize("cookies", [[], [_CLEARANCE_COOKIE]])
@pytest.mark.parametrize("intervention_type", ["captcha", "login"])
async def test_a_window_whose_page_never_loaded_saves_nothing_and_does_not_resolve(
    address: str, cookies: list[dict[str, str]], intervention_type: str
) -> None:
    # given
    factory, _, _, page = _build_playwright_factory(cookies=cookies, page_url=address, goto_error=True)
    page.content = AsyncMock(return_value=_READABLE_PAGE)
    flow = _make_flow(_LOADED_ADDRESS, intervention_type)
    finish = AsyncMock()

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as save,
        patch.object(novnc_flow_registry, "finish", new=finish),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", _SHORT_TIMEOUT_SECONDS),
        patch(
            "src.reader.strategies.novnc_strategy.settings.NOVNC_COOKIE_SYNC_POLL_SECONDS",
            _SHORT_POLL_SECONDS,
        ),
    ):
        await _monitor_for_cookies(flow)

    # then
    save.assert_not_awaited()
    finish.assert_awaited_once_with(flow, "timeout")


async def test_a_page_that_loads_after_a_failed_navigation_is_judged_normally() -> None:
    # given
    factory, _, _, page = _build_playwright_factory(page_url=_FAILED_NAVIGATION_ADDRESS, goto_error=True)
    steps = iter(
        [
            (_LOADED_ADDRESS, _CHALLENGE_PAGE),
            (_FAILED_NAVIGATION_ADDRESS, _READABLE_PAGE),
            (_LOADED_ADDRESS, _READABLE_PAGE),
        ]
    )
    current_content = _READABLE_PAGE
    judged: list[str] = []

    def serve_content() -> str:
        judged.append(current_content)

        return current_content

    async def next_step(_seconds: float) -> None:
        nonlocal current_content
        page.url, current_content = next(steps)

    page.content = AsyncMock(side_effect=serve_content)
    flow = _make_flow(_LOADED_ADDRESS, "captcha")
    finish = AsyncMock()

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as save,
        patch.object(novnc_flow_registry, "finish", new=finish),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
        patch("src.reader.strategies.novnc_strategy.asyncio.sleep", new=next_step),
    ):
        await _monitor_for_cookies(flow)

    # then
    assert judged == [_CHALLENGE_PAGE, _READABLE_PAGE]
    save.assert_awaited_once()
    finish.assert_awaited_once_with(flow, "resolved")


@pytest.mark.asyncio
async def test_browser_calls_have_ended_before_the_browser_closes_and_the_driver_stops() -> None:
    # given
    factory, browser, _ctx, _page = _build_playwright_factory(page_url="http://own-task.com/1")
    flow = await novnc_flow_registry.reserve(
        key=flow_key_for("https://own-task.com/1", "default"),
        url="https://own-task.com/1",
        profile="default",
        intervention_type="captcha",
    )
    launched_in: list[asyncio.Task[Any]] = []
    events: list[str] = []
    real_launch = factory.__aenter__.return_value.chromium.launch

    async def _launch(**options: Any) -> Any:
        current = asyncio.current_task()
        assert current is not None
        launched_in.append(current)

        return await real_launch(**options)

    async def _close() -> None:
        events.append(f"close, browser task done: {launched_in[0].done()}")

    async def _stop(*_args: Any) -> bool:
        events.append("stop")

        return False

    factory.__aenter__.return_value.chromium.launch = _launch
    browser.close = _close
    factory.__aexit__ = _stop

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy._poll_once",
            new=AsyncMock(return_value=("resolved", False)),
        ),
    ):
        await _monitor_for_cookies(flow)

    # then
    assert events == ["close, browser task done: True", "stop"]


async def _cancel_during_driver_start(factory: Any, url: str) -> None:
    flow = await novnc_flow_registry.reserve(
        key=flow_key_for(url, "default"), url=url, profile="default", intervention_type="captcha"
    )
    with patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory):
        task = asyncio.create_task(_monitor_for_cookies(flow))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_cancel_during_driver_start_waits_for_the_driver_and_stops_it() -> None:
    # given
    factory, _browser, _ctx, _page = _build_playwright_factory()
    started = asyncio.Event()

    async def _slow_start() -> Any:
        started.set()
        await asyncio.sleep(0.05)

        return MagicMock()

    factory.__aenter__ = AsyncMock(side_effect=_slow_start)
    before = _sample_value(
        "strategy_attempts_total", strategy="6-novnc-monitor", outcome="cancelled", domain="driver-start.com"
    )

    # when
    await _cancel_during_driver_start(factory, "https://driver-start.com/1")

    # then
    after = _sample_value(
        "strategy_attempts_total", strategy="6-novnc-monitor", outcome="cancelled", domain="driver-start.com"
    )
    assert started.is_set()
    factory.__aexit__.assert_awaited_once()
    assert novnc_flow_registry.local() == []
    assert after == before + 1.0


@pytest.mark.asyncio
async def test_cancel_during_a_driver_start_that_fails_has_nothing_to_stop() -> None:
    # given
    factory, _browser, _ctx, _page = _build_playwright_factory()

    async def _failing_start() -> Any:
        await asyncio.sleep(0.05)

        raise RuntimeError("driver did not start")

    factory.__aenter__ = AsyncMock(side_effect=_failing_start)

    # when
    await _cancel_during_driver_start(factory, "https://driver-failed.com/1")

    # then
    factory.__aexit__.assert_not_awaited()
    assert novnc_flow_registry.local() == []


_PRIVATE_HOP = "http://169.254.169.254/"


@pytest.mark.asyncio
async def test_a_window_whose_navigation_was_refused_closes_as_unsafe_uri() -> None:
    # given
    factory, _, _, _ = _build_playwright_factory(page_url="http://site-a.com/done")
    flow = _make_flow("https://site-a.com/redirects", "captcha", slot=0)
    poll = AsyncMock(return_value=("resolved", False))
    finish = AsyncMock()

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.install_browser_guard",
            new=AsyncMock(return_value=[_PRIVATE_HOP]),
        ),
        patch("src.reader.strategies.novnc_strategy._poll_once", new=poll),
        patch("src.reader.strategies.novnc_strategy.novnc_flow_registry.finish", new=finish),
    ):
        await _monitor_for_cookies(flow)

    # then
    finish.assert_awaited_once_with(flow, "unsafe_uri")
    poll.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_window_whose_later_navigation_was_refused_closes_as_unsafe_uri() -> None:
    # given
    factory, _, _, _ = _build_playwright_factory(page_url="http://site-a.com/done")
    flow = _make_flow("https://site-a.com/page", "captcha", slot=0)
    refused: list[str] = []

    async def poll(*_args: object) -> tuple[None, bool]:
        refused.append(_PRIVATE_HOP)

        return None, False

    finish = AsyncMock()

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.install_browser_guard",
            new=AsyncMock(return_value=refused),
        ),
        patch("src.reader.strategies.novnc_strategy._poll_once", new=poll),
        patch("src.reader.strategies.novnc_strategy.novnc_flow_registry.finish", new=finish),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_COOKIE_SYNC_POLL_SECONDS", 0.01),
    ):
        await _monitor_for_cookies(flow)

    # then
    finish.assert_awaited_once_with(flow, "unsafe_uri")


@pytest.mark.asyncio
async def test_a_window_leaves_through_the_configured_proxy_chained_on_the_tunnel() -> None:
    # given
    factory, browser, _, _ = _build_playwright_factory(page_url="http://site-a.com/done")
    flow = _make_flow("https://site-a.com/page", "captcha", slot=0)

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.proxy_provider.for_playwright",
            return_value={"server": "http://proxy:3128"},
        ),
        patch(
            "src.reader.strategies.novnc_strategy._poll_once",
            new=AsyncMock(return_value=("resolved", False)),
        ),
    ):
        await _monitor_for_cookies(flow)

    # then
    assert browser.new_context.await_args.kwargs["proxy"] == {"server": "chained:http://proxy:3128"}


@pytest.mark.asyncio
async def test_a_window_without_a_proxy_sets_none_on_its_context() -> None:
    # given
    factory, browser, _, _ = _build_playwright_factory(page_url="http://site-a.com/done")
    flow = _make_flow("https://site-a.com/page", "captcha", slot=0)

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch("src.reader.strategies.novnc_strategy.proxy_provider.for_playwright", return_value=None),
        patch(
            "src.reader.strategies.novnc_strategy._poll_once",
            new=AsyncMock(return_value=("resolved", False)),
        ),
    ):
        await _monitor_for_cookies(flow)

    # then
    assert "proxy" not in browser.new_context.await_args.kwargs
