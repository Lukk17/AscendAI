from unittest.mock import patch

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.main import create_app
from src.observability.metrics import ENGINE_CACHE_EVICTIONS_TOTAL


@pytest.fixture
def app_with_lifespan():
    # start_worker_pool()/stop_worker_pool() are mocked so this test doesn't spawn a
    # real OS process and load a real PaddleOCR model just to exercise the lifespan.
    with (
        patch("src.main.start_worker_pool") as mock_start_pool,
        patch("src.main.stop_worker_pool") as mock_stop_pool,
    ):
        yield create_app(), mock_start_pool, mock_stop_pool


async def test_lifespan_starts_worker_pool_and_banner(app_with_lifespan):
    # Given. asgi-lifespan drives the ASGI lifespan protocol that httpx does not trigger by
    # default, so start_worker_pool, the MCP session manager startup, and the banner all run.
    app, mock_start_pool, mock_stop_pool = app_with_lifespan
    transport = ASGITransport(app=app)

    # When
    async with (
        LifespanManager(app),
        AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        response = await client.get("/health")
        mock_start_pool.assert_called_once()
        mock_stop_pool.assert_not_called()

    # Then
    assert response.status_code == 200
    mock_stop_pool.assert_called_once()


def test_create_app_returns_fastapi_instance():
    # When
    app = create_app()

    # Then
    assert isinstance(app, FastAPI)


async def test_metrics_endpoint_reports_eviction_counter():
    # Given. Multiprocess mode (src/__init__.py) merges every process's own file in
    # PROMETHEUS_MULTIPROC_DIR at scrape time instead of reading in-process state, so
    # this also proves the merge path itself works, not just that the counter exists.
    ENGINE_CACHE_EVICTIONS_TOTAL.labels(language="metrics-endpoint-probe").inc()
    app = create_app()
    transport = ASGITransport(app=app)

    # When
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/metrics")

    # Then
    assert response.status_code == 200
    assert "paddleocr_engine_cache_evictions_total" in response.text
