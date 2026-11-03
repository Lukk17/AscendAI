from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI


def _no_banner_network() -> tuple[Any, ...]:
    from ascend_python_common.startup_banner import BannerCheck

    return (
        patch(
            "src.config.startup_banner._searxng_check_sync",
            return_value=BannerCheck(
                label="SearXNG", target="http://localhost:9020/healthz", status="Connected"
            ),
        ),
        patch(
            "src.config.startup_banner._redis_check_sync",
            return_value=BannerCheck(label="Redis", target="redis://127.0.0.1:6379/0", status="Connected"),
        ),
    )


@pytest.mark.asyncio
async def test_lifespan_raises_when_blocklist_not_loaded() -> None:
    """The lifespan must fail hard if the blocklist singleton was somehow never loaded."""
    # given
    from src import main as main_module
    from src.config.blocklist_loader import blocklist_loader

    original_state = blocklist_loader.state

    # when
    with patch.object(blocklist_loader, "_state", None):
        # Build a fresh app so we exercise the new lifespan.
        app = main_module.create_app()
        with pytest.raises(RuntimeError):
            async with LifespanManager(app):
                pass

    # then
    assert blocklist_loader.state == original_state


@pytest.mark.asyncio
async def test_lifespan_logs_warning_when_rest_search_client_close_fails() -> None:
    # given
    from src import main as main_module

    # when / then
    with (
        patch.object(
            main_module.rest_search_client,  # type: ignore[attr-defined]
            "aclose",
            new=AsyncMock(side_effect=RuntimeError("rest close failed")),
        ),
        patch.object(
            main_module.mcp_search_client,  # type: ignore[attr-defined]
            "aclose",
            new=AsyncMock(),
        ),
        _no_banner_network()[0],
        _no_banner_network()[1],
    ):
        app: FastAPI = main_module.create_app()
        async with LifespanManager(app):
            pass


@pytest.mark.asyncio
async def test_lifespan_logs_warning_when_browser_pool_stop_fails() -> None:
    # given
    from src import main as main_module
    from src.runtime.browser_pool import browser_pool

    # when / then
    with (
        patch.object(
            browser_pool,
            "stop",
            new=AsyncMock(side_effect=RuntimeError("stop failed")),
        ),
        _no_banner_network()[0],
        _no_banner_network()[1],
    ):
        app: FastAPI = main_module.create_app()
        async with LifespanManager(app):
            pass


@pytest.mark.asyncio
async def test_lifespan_logs_warning_when_mcp_search_client_close_fails() -> None:
    # given
    from src import main as main_module

    # when / then
    with (
        patch.object(
            main_module.rest_search_client,  # type: ignore[attr-defined]
            "aclose",
            new=AsyncMock(),
        ),
        patch.object(
            main_module.mcp_search_client,  # type: ignore[attr-defined]
            "aclose",
            new=AsyncMock(side_effect=RuntimeError("mcp close failed")),
        ),
        _no_banner_network()[0],
        _no_banner_network()[1],
    ):
        app: FastAPI = main_module.create_app()
        async with LifespanManager(app):
            pass


@pytest.mark.asyncio
async def test_lifespan_runs_sweeper_and_cancels_it_on_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lifespan sweeps local flows on the configured interval and cancels
    the sweeper on exit."""
    # given
    import asyncio

    from src import main as main_module
    from src.config.config import settings
    from src.reader.novnc.flow_registry import novnc_flow_registry

    monkeypatch.setattr(settings, "NOVNC_FLOW_SWEEP_INTERVAL_SECONDS", 0.05)
    sweeps: list[int] = []

    async def counting_sweep() -> list[Any]:
        sweeps.append(1)

        return []

    monkeypatch.setattr(novnc_flow_registry, "sweep", counting_sweep)
    lifespan = main_module.service_lifespan()

    # when
    await lifespan.__aenter__()
    await asyncio.sleep(0.16)
    task = lifespan._novnc_sweeper
    assert task is not None
    await lifespan.__aexit__(None, None, None)

    # then
    assert len(sweeps) >= 2
    assert task.cancelled()


@pytest.mark.asyncio
async def test_lifespan_exit_shuts_down_flows_before_browser_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shutdown drains the intervention flows before the browser pool stops."""
    # given
    from src import main as main_module
    from src.reader.novnc.flow_registry import novnc_flow_registry
    from src.runtime.browser_pool import browser_pool

    calls: list[str] = []

    async def fake_shutdown() -> None:
        calls.append("shutdown")

    async def fake_stop() -> None:
        calls.append("stop")

    monkeypatch.setattr(novnc_flow_registry, "shutdown", fake_shutdown)
    monkeypatch.setattr(browser_pool, "stop", fake_stop)
    lifespan = main_module.service_lifespan()

    # when
    await lifespan.__aenter__()
    await lifespan.__aexit__(None, None, None)

    # then
    assert calls == ["shutdown", "stop"]


@pytest.mark.asyncio
async def test_lifespan_exit_cancels_live_flow_monitor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live flow's monitor is cancelled and its browser closed when the
    lifespan exits."""
    # given
    import asyncio

    from src import main as main_module
    from src.reader.novnc.flow_registry import flow_key_for, novnc_flow_registry
    from src.reader.strategies.novnc_strategy import _monitor_for_cookies
    from tests.reader.novnc.test_flow_registry import FakeRedis

    fake = FakeRedis()
    monkeypatch.setattr(novnc_flow_registry, "_redis", fake)
    flow = await novnc_flow_registry.reserve(
        key=flow_key_for("https://exit-site.com/1", "default"),
        url="https://exit-site.com/1",
        profile="default",
        intervention_type="captcha",
    )
    page = MagicMock()
    page.url = "https://exit-site.com/1"
    page.goto = AsyncMock()
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
    lifespan = main_module.service_lifespan()

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ),
        patch(
            "src.reader.strategies.novnc_strategy._poll_once",
            new=AsyncMock(return_value=(False, True)),
        ),
    ):
        task = asyncio.create_task(_monitor_for_cookies(flow))
        novnc_flow_registry.attach_task(flow.flow_id, task)
        await asyncio.sleep(0.1)
        await lifespan.__aenter__()
        await lifespan.__aexit__(None, None, None)

    # then
    assert task.done()
    browser.close.assert_awaited()
    assert novnc_flow_registry.local() == []
    assert await fake.get("novnc_flow:exit-site.com:default") is None


@pytest.mark.asyncio
async def test_sweeper_survives_failing_sweep(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One failing sweep is logged and the task keeps running afterwards."""
    # given
    import asyncio

    from src import main as main_module
    from src.config.config import settings
    from src.reader.novnc.flow_registry import novnc_flow_registry

    monkeypatch.setattr(settings, "NOVNC_FLOW_SWEEP_INTERVAL_SECONDS", 0.05)
    calls = {"count": 0}

    async def flaky_sweep() -> list[Any]:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")

        return []

    monkeypatch.setattr(novnc_flow_registry, "sweep", flaky_sweep)
    lifespan = main_module.service_lifespan()

    # when
    with caplog.at_level("WARNING", logger="uvicorn"):
        await lifespan.__aenter__()
        await asyncio.sleep(0.16)
        task = lifespan._novnc_sweeper
        assert task is not None
        still_running = not task.done()
        await lifespan.__aexit__(None, None, None)

    # then
    assert still_running
    assert calls["count"] >= 2
    assert any("sweep failed" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_lifespan_exit_tolerates_shutdown_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing flow shutdown is logged and the browser pool still stops."""
    # given
    from src import main as main_module
    from src.reader.novnc.flow_registry import novnc_flow_registry
    from src.runtime.browser_pool import browser_pool

    calls: list[str] = []

    async def boom() -> None:
        calls.append("shutdown")
        raise RuntimeError("boom")

    async def stopped() -> None:
        calls.append("stop")

    monkeypatch.setattr(novnc_flow_registry, "shutdown", boom)
    monkeypatch.setattr(browser_pool, "stop", stopped)
    lifespan = main_module.service_lifespan()

    # when
    await lifespan.__aenter__()
    await lifespan.__aexit__(None, None, None)

    # then
    assert calls == ["shutdown", "stop"]


@pytest.mark.asyncio
async def test_lifespan_starts_purge_subscriber_and_cancels_it_on_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lifespan subscribes to the read-cache purge channel and cancels the
    subscriber on exit (task 5.5)."""
    # given
    from src import main as main_module
    from src.reader.novnc.flow_registry import novnc_flow_registry
    from src.runtime.browser_pool import browser_pool

    async def fake_shutdown() -> None:
        return None

    async def fake_stop() -> None:
        return None

    monkeypatch.setattr(novnc_flow_registry, "shutdown", fake_shutdown)
    monkeypatch.setattr(browser_pool, "stop", fake_stop)
    lifespan = main_module.service_lifespan()

    # when
    await lifespan.__aenter__()
    task = lifespan._purge_subscriber
    assert task is not None
    await lifespan.__aexit__(None, None, None)

    # then
    assert task.cancelled()
    assert lifespan._purge_subscriber is None
    assert lifespan._purge_stop.is_set()


@pytest.mark.asyncio
async def test_lifespan_exit_without_enter_skips_sweeper_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exiting a lifespan that never entered cancels nothing but still drains."""
    # given
    from src import main as main_module
    from src.reader.novnc.flow_registry import novnc_flow_registry
    from src.runtime.browser_pool import browser_pool

    calls: list[str] = []

    async def fake_shutdown() -> None:
        calls.append("shutdown")

    async def fake_stop() -> None:
        calls.append("stop")

    monkeypatch.setattr(novnc_flow_registry, "shutdown", fake_shutdown)
    monkeypatch.setattr(browser_pool, "stop", fake_stop)
    lifespan = main_module.service_lifespan()
    assert lifespan._novnc_sweeper is None

    # when
    await lifespan.__aexit__(None, None, None)

    # then
    assert lifespan._novnc_sweeper is None
    assert calls == ["shutdown", "stop"]
