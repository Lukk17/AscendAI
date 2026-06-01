import logging
import re
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware.correlation_id import (
    CORRELATION_ID_HEADER,
    CorrelationIdLogFilter,
    CorrelationIdMiddleware,
    get_correlation_id,
)


@pytest.fixture
def app_with_correlation():
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/echo")
    def echo() -> dict[str, str]:
        return {"correlation_id": get_correlation_id()}

    return app


@pytest.fixture
def client(app_with_correlation):
    return TestClient(app_with_correlation)


class TestCorrelationIdMiddleware:
    def test_generates_uuid_when_header_absent(self, client):
        # When
        response = client.get("/echo")

        # Then
        assert response.status_code == 200
        cid = response.json()["correlation_id"]
        assert re.fullmatch(r"[0-9a-f-]{36}", cid)
        assert response.headers[CORRELATION_ID_HEADER] == cid

    def test_uses_inbound_header(self, client):
        # Given
        inbound = "abc-123"

        # When
        response = client.get("/echo", headers={CORRELATION_ID_HEADER: inbound})

        # Then
        assert response.json()["correlation_id"] == inbound
        assert response.headers[CORRELATION_ID_HEADER] == inbound

    async def test_passes_through_non_http_scope(self):
        # Given
        called = {"count": 0}

        async def fake_app(scope, receive, send):
            called["count"] += 1

        receive = AsyncMock()
        send = AsyncMock()
        middleware = CorrelationIdMiddleware(fake_app)

        # When
        await middleware({"type": "lifespan"}, receive, send)

        # Then
        assert called["count"] == 1


class TestCorrelationIdLogFilter:
    def test_injects_correlation_id_into_record(self):
        # Given
        filter_obj = CorrelationIdLogFilter()
        record = logging.LogRecord("t", logging.INFO, "", 0, "msg", (), None)

        # When
        result = filter_obj.filter(record)

        # Then
        assert result is True
        assert hasattr(record, "correlation_id")
