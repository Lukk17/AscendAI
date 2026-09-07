from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware.security_headers import SecurityHeadersMiddleware


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "yes"}

    return TestClient(app)


class TestSecurityHeadersMiddleware:
    def test_hsts_header_present(self, client):
        # When
        response = client.get("/ping")

        # Then
        assert "max-age=63072000" in response.headers["strict-transport-security"]

    def test_no_sniff_header(self, client):
        # When
        response = client.get("/ping")

        # Then
        assert response.headers["x-content-type-options"] == "nosniff"

    def test_frame_options_deny(self, client):
        # When
        response = client.get("/ping")

        # Then
        assert response.headers["x-frame-options"] == "DENY"

    def test_referrer_policy(self, client):
        # When
        response = client.get("/ping")

        # Then
        assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client):
        # When
        response = client.get("/ping")

        # Then
        assert "camera=()" in response.headers["permissions-policy"]

    def test_csp_header(self, client):
        # When
        response = client.get("/ping")

        # Then
        assert "default-src 'none'" in response.headers["content-security-policy"]

    async def test_passes_through_non_http_scope(self):
        # Given
        called = {"count": 0}

        async def fake_app(scope, receive, send):
            called["count"] += 1

        receive = AsyncMock()
        send = AsyncMock()
        middleware = SecurityHeadersMiddleware(fake_app)

        # When
        await middleware({"type": "lifespan"}, receive, send)

        # Then
        assert called["count"] == 1

    async def test_existing_header_is_not_overridden(self):
        # Given a downstream app that already sets x-frame-options
        async def fake_app(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"x-frame-options", b"SAMEORIGIN")],
                }
            )
            await send({"type": "http.response.body", "body": b""})

        captured: list[dict] = []

        async def capture_send(message):
            captured.append(message)

        receive = AsyncMock()
        middleware = SecurityHeadersMiddleware(fake_app)

        # When
        await middleware({"type": "http", "headers": []}, receive, capture_send)

        # Then. The existing SAMEORIGIN wins over the middleware DENY.
        start = captured[0]
        names_seen = [name for name, _ in start["headers"]]
        assert names_seen.count(b"x-frame-options") == 1
        for name, value in start["headers"]:
            if name == b"x-frame-options":
                assert value == b"SAMEORIGIN"
