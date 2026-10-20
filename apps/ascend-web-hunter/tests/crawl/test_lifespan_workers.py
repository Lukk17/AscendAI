from unittest.mock import patch

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
