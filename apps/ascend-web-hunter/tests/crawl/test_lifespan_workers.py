import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.config.config import settings


@pytest.mark.asyncio
async def test_lifespan_starts_one_task_per_worker_and_stops_them() -> None:
    # given
    from src import main as main_module
    from src.reader.novnc.flow_registry import novnc_flow_registry
    from src.runtime.browser_pool import browser_pool

    async def fake_shutdown() -> None:
        return None

    async def fake_stop() -> None:
        return None

    lifespan = main_module.service_lifespan()
    assert lifespan._crawl_tasks == []

    # when
    with (
        patch.object(novnc_flow_registry, "shutdown", fake_shutdown),
        patch.object(browser_pool, "stop", fake_stop),
    ):
        await lifespan.__aenter__()
        assert len(lifespan._crawl_tasks) == settings.CRAWL_WORKER_CONCURRENCY
        assert all(task is not None for task in lifespan._crawl_tasks)
        await lifespan.__aexit__(None, None, None)

    # then every worker task is cancelled
    assert lifespan._crawl_tasks == []


@pytest.mark.asyncio
async def test_lifespan_exit_tolerates_crawl_redis_close_failure() -> None:
    # given a crawl client whose close fails
    from typing import Any
    from unittest.mock import AsyncMock

    from src import main as main_module
    from src.reader.novnc.flow_registry import novnc_flow_registry
    from src.runtime.browser_pool import browser_pool

    async def fake_shutdown() -> None:
        return None

    async def fake_stop() -> None:
        return None

    lifespan = main_module.service_lifespan()

    # when
    with (
        patch.object(novnc_flow_registry, "shutdown", fake_shutdown),
        patch.object(browser_pool, "stop", fake_stop),
    ):
        await lifespan.__aenter__()
        failing: Any = AsyncMock()
        failing.aclose.side_effect = RuntimeError("close failed")
        lifespan._crawl_redis = failing
        await lifespan.__aexit__(None, None, None)

    # then the client is dropped anyway
    assert lifespan._crawl_redis is None
    assert lifespan._crawl_tasks == []


@pytest.mark.asyncio
async def test_lifespan_applies_the_result_expiry_rule_at_worker_startup(
    stub_crawl_result_expiry: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given the real startup step and a worker whose rule applies at once
    from src import main as main_module
    from src.crawl.worker import Worker

    monkeypatch.setattr(main_module._ServiceLifespan, "_start_result_expiry", stub_crawl_result_expiry)
    applied = AsyncMock()
    monkeypatch.setattr(Worker, "apply_result_expiry", applied)
    lifespan = main_module.service_lifespan()

    # when
    await lifespan.__aenter__()
    started = lifespan._result_expiry
    await lifespan.__aexit__(None, None, None)

    # then the rule was applied once before startup finished and the task is cleared on exit
    applied.assert_awaited_once_with()
    assert started is not None
    assert started.done()
    assert lifespan._result_expiry is None


@pytest.mark.asyncio
async def test_lifespan_startup_never_waits_past_the_probe_budget_for_the_expiry_rule(
    stub_crawl_result_expiry: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a store that never answers and a tiny startup budget
    from src import main as main_module
    from src.crawl.worker import Worker

    monkeypatch.setattr(main_module._ServiceLifespan, "_start_result_expiry", stub_crawl_result_expiry)
    monkeypatch.setattr(settings, "STARTUP_PROBE_TIMEOUT_SECONDS", 0.01)
    never = asyncio.Event()

    async def hang(self: Worker) -> None:
        await never.wait()

    monkeypatch.setattr(Worker, "apply_result_expiry", hang)
    lifespan = main_module.service_lifespan()

    # when
    await asyncio.wait_for(lifespan.__aenter__(), timeout=5)
    pending = lifespan._result_expiry
    await lifespan.__aexit__(None, None, None)

    # then startup finished while the rule was still pending and exit cancelled it
    assert pending is not None
    assert pending.cancelled()
    assert lifespan._result_expiry is None
