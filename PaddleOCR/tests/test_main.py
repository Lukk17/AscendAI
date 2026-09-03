from unittest.mock import MagicMock, patch

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.main import create_app


@pytest.fixture
def app_with_lifespan():
    # start_worker_pool()/stop_worker_pool() are mocked so this test doesn't spawn a
    # real OS process and load a real PaddleOCR model just to exercise the lifespan.
    with (
        patch("src.main.ocr_service") as mock_service,
        patch("src.main.start_worker_pool") as mock_start_pool,
        patch("src.main.stop_worker_pool") as mock_stop_pool,
    ):
        mock_service.warm_up_engine = MagicMock()
        mock_service._engines = {}
        yield create_app(), mock_start_pool, mock_stop_pool


async def test_lifespan_executes_warm_up_and_banner(app_with_lifespan):
    # Given. asgi-lifespan drives the ASGI lifespan protocol that httpx does not trigger by
    # default, so warm_up_engine, the MCP session manager startup, and the banner all run.
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
