from unittest.mock import MagicMock

import pytest

from src.observability.request_context import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    request_id_ctx,
)


@pytest.mark.asyncio
async def test_middleware_uses_inbound_request_id_header():
    # given
    middleware = RequestIdMiddleware(MagicMock())
    request = MagicMock()
    request.headers = {REQUEST_ID_HEADER: "client-id"}
    captured: dict[str, str] = {}

    async def call_next(req):
        captured["id"] = request_id_ctx.get()
        response = MagicMock()
        response.headers = {}

        return response

    # when
    response = await middleware.dispatch(request, call_next)

    # then
    assert captured["id"] == "client-id"
    assert response.headers[REQUEST_ID_HEADER] == "client-id"


@pytest.mark.asyncio
async def test_middleware_generates_uuid_when_header_absent():
    # given
    middleware = RequestIdMiddleware(MagicMock())
    request = MagicMock()
    request.headers = {}

    async def call_next(req):
        response = MagicMock()
        response.headers = {}

        return response

    # when
    response = await middleware.dispatch(request, call_next)

    # then
    request_id = response.headers[REQUEST_ID_HEADER]
    assert isinstance(request_id, str)
    assert len(request_id) >= 16


@pytest.mark.asyncio
async def test_middleware_rejects_crlf_in_inbound_header():
    """Security: CR/LF in X-Request-ID would enable response splitting / log forging.
    The middleware must drop the inbound value and synthesise a fresh UUID instead."""
    # given
    middleware = RequestIdMiddleware(MagicMock())
    request = MagicMock()
    request.headers = {REQUEST_ID_HEADER: "a\r\nX-Injected: 1"}

    async def call_next(req):
        response = MagicMock()
        response.headers = {}

        return response

    # when
    response = await middleware.dispatch(request, call_next)

    # then
    emitted = response.headers[REQUEST_ID_HEADER]
    assert "\r" not in emitted
    assert "\n" not in emitted
    assert emitted != "a\r\nX-Injected: 1"


@pytest.mark.asyncio
async def test_middleware_rejects_overlong_header():
    # given
    middleware = RequestIdMiddleware(MagicMock())
    request = MagicMock()
    request.headers = {REQUEST_ID_HEADER: "a" * 200}

    async def call_next(req):
        response = MagicMock()
        response.headers = {}

        return response

    # when
    response = await middleware.dispatch(request, call_next)

    # then
    assert len(response.headers[REQUEST_ID_HEADER]) <= 36  # uuid4 length


@pytest.mark.asyncio
async def test_middleware_rejects_unicode_tricks():
    # given
    middleware = RequestIdMiddleware(MagicMock())
    request = MagicMock()
    request.headers = {REQUEST_ID_HEADER: "abc‮def"}  # bidi override

    async def call_next(req):
        response = MagicMock()
        response.headers = {}

        return response

    # when
    response = await middleware.dispatch(request, call_next)

    # then
    assert "‮" not in response.headers[REQUEST_ID_HEADER]
