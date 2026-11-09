"""Concurrent intervention windows: two flows, the cap, and failure isolation."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ascend_python_common.errors.registry import resolve_detail

from src.api.exception_handlers import error_registry
from src.api.exceptions import HumanInterventionRequiredException, NoVNCFlowBusyException
from src.config.config import settings
from src.observability.metrics import NOVNC_ACTIVE_FLOWS
from src.reader.novnc.flow_registry import novnc_flow_registry
from src.reader.strategies.novnc_strategy import NoVNCStrategy, _monitor_for_cookies
from tests.reader.novnc.test_flow_registry import FakeRedis


def _sample_value(metric_name: str, **labels: str) -> float:
    from prometheus_client import REGISTRY

    return REGISTRY.get_sample_value(metric_name, labels) or 0.0


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Any:
    fake = FakeRedis()
    monkeypatch.setattr(novnc_flow_registry, "_redis", fake)
    novnc_flow_registry._local.clear()
    yield fake
    novnc_flow_registry._local.clear()


def _discard_coro(coro: Any) -> Any:
    coro.close()

    return MagicMock(name="monitor-task")


def _build_playwright_factory(page: Any, browser: Any) -> Any:
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    factory = MagicMock()
    factory.__aenter__ = AsyncMock(return_value=pw)
    factory.__aexit__ = AsyncMock(return_value=False)

    return factory


@pytest.mark.asyncio
async def test_two_concurrent_flows_both_get_their_own_window() -> None:
    """Two different sites escalate at once: each gets a 428 with a window of
    its own, a distinct flow_id and a distinct slot."""
    # given
    from src.reader.strategies.novnc_strategy import NoVNCStrategy

    first = NoVNCStrategy("default")
    second = NoVNCStrategy("default")

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch(
            "src.reader.strategies.novnc_strategy.asyncio.create_task",
            side_effect=_discard_coro,
        ) as mock_create_task,
    ):
        with pytest.raises(HumanInterventionRequiredException) as first_exc:
            await first.get_html("https://site-a.com/page")
        with pytest.raises(HumanInterventionRequiredException) as second_exc:
            await second.get_html("https://site-b.com/page")

    # then
    assert first_exc.value.joined is False
    assert second_exc.value.joined is False
    assert first_exc.value.flow_id != second_exc.value.flow_id
    assert first_exc.value.window != second_exc.value.window
    assert first_exc.value.window is not None
    assert second_exc.value.window is not None
    assert first_exc.value.window["slot"] != second_exc.value.window["slot"]
    assert mock_create_task.call_count == 2


@pytest.mark.asyncio
async def test_third_request_is_refused_at_cap_with_counts() -> None:
    """With the cap patched to 2, two distinct domains each get a window and
    the third raises carrying active_flows=2 and max_concurrent_flows=2."""
    # given
    from src.reader.strategies.novnc_strategy import NoVNCStrategy

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch.object(settings, "NOVNC_MAX_CONCURRENT_FLOWS", 2),
        patch(
            "src.reader.strategies.novnc_strategy.asyncio.create_task",
            side_effect=_discard_coro,
        ),
    ):
        with pytest.raises(HumanInterventionRequiredException):
            await NoVNCStrategy("default").get_html("https://site-a.com/page")
        with pytest.raises(HumanInterventionRequiredException):
            await NoVNCStrategy("default").get_html("https://site-b.com/other")
        with pytest.raises(NoVNCFlowBusyException) as exc:
            await NoVNCStrategy("default").get_html("https://site-c.com/later")

    # then
    assert exc.value.active_flows == 2
    assert exc.value.max_concurrent_flows == 2


@pytest.mark.asyncio
async def test_one_failing_flow_leaves_sibling_untouched() -> None:
    """With two flows in flight, one dying inside its poll loop must not
    cancel the sibling, close its browser, free its slot or touch sessions."""
    # given
    from src.reader.cloudflare.challenge_signals import ChallengeVerdict
    from src.reader.novnc.flow_registry import flow_key_for

    class _PollBlowUp(BaseException):
        """An unexpected death inside the poll loop, distinct from cancellation."""

    wall = ChallengeVerdict(
        score=200,
        threshold=100,
        signals=(),
        vendor=None,
        wall=True,
        has_content=False,
        intervention_type="captcha",
    )
    dying = await novnc_flow_registry.reserve(
        key=flow_key_for("https://dying-site.com/1", "default"),
        url="https://dying-site.com/1",
        profile="default",
        intervention_type="captcha",
    )
    steady = await novnc_flow_registry.reserve(
        key=flow_key_for("https://steady-site.com/1", "default"),
        url="https://steady-site.com/1",
        profile="default",
        intervention_type="captcha",
    )
    dying_page = MagicMock()
    dying_page.url = "https://dying-site.com/1"
    dying_page.goto = AsyncMock(return_value=None)
    dying_page.content = AsyncMock(side_effect=_PollBlowUp)
    dying_page.evaluate = AsyncMock(return_value="UA")
    dying_context = MagicMock()
    dying_context.route = AsyncMock()
    dying_context.route_web_socket = None
    dying_context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
    dying_context.cookies = AsyncMock(return_value=dying_context.storage_state.return_value["cookies"])
    dying_context.new_page = AsyncMock(return_value=dying_page)
    dying_browser = MagicMock()
    dying_browser.new_context = AsyncMock(return_value=dying_context)
    dying_browser.close = AsyncMock()
    steady_page = MagicMock()
    steady_page.url = "https://steady-site.com/1"
    steady_page.goto = AsyncMock(return_value=None)
    steady_page.content = AsyncMock(return_value="<html><body>wall</body></html>")
    steady_page.evaluate = AsyncMock(return_value="UA")
    steady_context = MagicMock()
    steady_context.route = AsyncMock()
    steady_context.route_web_socket = None
    steady_context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
    steady_context.cookies = AsyncMock(return_value=steady_context.storage_state.return_value["cookies"])
    steady_context.new_page = AsyncMock(return_value=steady_page)
    steady_browser = MagicMock()
    steady_browser.new_context = AsyncMock(return_value=steady_context)
    steady_browser.close = AsyncMock()

    # when
    with (
        patch(
            "src.reader.strategies.novnc_strategy.async_playwright",
            side_effect=[
                _build_playwright_factory(dying_page, dying_browser),
                _build_playwright_factory(steady_page, steady_browser),
            ],
        ),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch("src.reader.strategies.novnc_strategy.cookie_manager.clear_session") as mock_clear,
        patch(
            "src.reader.strategies.novnc_strategy.assess",
            return_value=wall,
        ),
    ):
        dying_task = asyncio.create_task(_monitor_for_cookies(dying))
        steady_task = asyncio.create_task(_monitor_for_cookies(steady))
        await asyncio.sleep(0.3)
        with pytest.raises(_PollBlowUp):
            await dying_task

        # then
        assert not steady_task.done()
        steady_browser.close.assert_not_awaited()
        assert {flow.flow_id for flow in novnc_flow_registry.local()} == {
            steady.flow_id,
        }
        mock_save.assert_not_awaited()
        mock_clear.assert_not_called()

        # cleanup
        steady_task.cancel()
        await asyncio.gather(steady_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_one_of_each_path_records_exact_counter_deltas() -> None:
    """One new flow, one join, one cap refusal and one reclamation: the exact
    counter deltas, joined=false for the new flow, joined=true for the join,
    and the join leaves the gauge alone."""
    # given
    NOVNC_ACTIVE_FLOWS.set(0)
    before_new = _sample_value("human_intervention_total", intervention_type="captcha", joined="false")
    before_joined = _sample_value("human_intervention_total", intervention_type="captcha", joined="true")
    before_busy = _sample_value("novnc_flow_busy_total")
    before_reclaimed = _sample_value("novnc_flows_reclaimed_total", reason="lease_expired")
    before_gauge = _sample_value("novnc_active_flows")

    def _handled_428(exc: HumanInterventionRequiredException) -> None:
        entry = error_registry.lookup(exc)
        assert entry is not None
        resolve_detail(entry, exc)

    # when: a new flow
    with (
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch("src.reader.strategies.novnc_strategy.asyncio.create_task", side_effect=_discard_coro),
    ):
        with pytest.raises(HumanInterventionRequiredException) as new_exc:
            await NoVNCStrategy("default").get_html("https://delta-a.com/1")
        _handled_428(new_exc.value)
        gauge_after_new = _sample_value("novnc_active_flows")
        # when: a join of the same key
        with pytest.raises(HumanInterventionRequiredException) as join_exc:
            await NoVNCStrategy("default").get_html("https://delta-a.com/2")
        _handled_428(join_exc.value)
        gauge_after_join = _sample_value("novnc_active_flows")
        # when: a refusal past the cap
        with patch.object(settings, "NOVNC_MAX_CONCURRENT_FLOWS", 1):
            with pytest.raises(NoVNCFlowBusyException) as busy_exc:
                await NoVNCStrategy("default").get_html("https://delta-b.com/1")
        busy_entry = error_registry.lookup(busy_exc.value)
        assert busy_entry is not None
        resolve_detail(busy_entry, busy_exc.value)
        # when: a lease reclamation
        [only] = novnc_flow_registry.local()
        only.lease_started -= settings.NOVNC_TIMEOUT_SECONDS + settings.NOVNC_FLOW_LEASE_GRACE_SECONDS + 5.0
        await novnc_flow_registry.sweep()

    # then
    assert (
        _sample_value("human_intervention_total", intervention_type="captcha", joined="false") - before_new
        == 1.0
    )
    assert (
        _sample_value("human_intervention_total", intervention_type="captcha", joined="true") - before_joined
        == 1.0
    )
    assert _sample_value("novnc_flow_busy_total") - before_busy == 1.0
    assert _sample_value("novnc_flows_reclaimed_total", reason="lease_expired") - before_reclaimed == 1.0
    assert gauge_after_new == before_gauge + 1.0
    assert gauge_after_join == gauge_after_new
    assert _sample_value("novnc_active_flows") == 0.0
