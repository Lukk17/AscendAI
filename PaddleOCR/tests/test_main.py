from unittest.mock import MagicMock, patch

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.main import create_app


@pytest.fixture
def app_with_lifespan():
    with patch("src.main.ocr_service") as mock_service:
        mock_service.warm_up_engine = MagicMock()
        mock_service._engines = {}
        yield create_app()


async def test_lifespan_executes_warm_up_and_banner(app_with_lifespan):
    # Given. asgi-lifespan drives the ASGI lifespan protocol that httpx does not trigger by
    # default, so warm_up_engine, the MCP session manager startup, and the banner all run.
    transport = ASGITransport(app=app_with_lifespan)

    # When
    async with LifespanManager(app_with_lifespan):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

    # Then
    assert response.status_code == 200


def test_create_app_returns_fastapi_instance():
    # When
    app = create_app()

    # Then
    assert isinstance(app, FastAPI)
