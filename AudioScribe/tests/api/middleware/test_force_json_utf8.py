from unittest.mock import AsyncMock, MagicMock
from typing import Any

import pytest

from src.api.middleware.force_json_utf8 import ForceJSONUTF8Middleware


@pytest.fixture
def mock_app() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def middleware(mock_app: AsyncMock) -> ForceJSONUTF8Middleware:
    return ForceJSONUTF8Middleware(mock_app)


@pytest.mark.asyncio
async def test_call_ignores_non_http_scope(middleware: ForceJSONUTF8Middleware, mock_app: AsyncMock) -> None:
    # // given
    scope = {"type": "websocket"}
    receive = AsyncMock()
    send = AsyncMock()

    # // when
    await middleware(scope, receive, send)

    # // then
    mock_app.assert_called_once_with(scope, receive, send)


@pytest.mark.asyncio
async def test_call_appends_charset_to_json(middleware: ForceJSONUTF8Middleware, mock_app: AsyncMock) -> None:
    # // given
    scope = {"type": "http"}
    receive = AsyncMock()
    send = AsyncMock()

    async def fake_app(scope: Any, receive: Any, send_wrapper: Any) -> None:
        await send_wrapper({
            "type": "http.response.start",
            "headers": [(b"content-type", b"application/json")]
        })

    mock_app.side_effect = fake_app

    # // when
    await middleware(scope, receive, send)

    # // then
    args = send.call_args[0]
    message = args[0]
    headers = dict(message["headers"])
    assert headers[b"content-type"] == b"application/json; charset=utf-8"


@pytest.mark.asyncio
async def test_call_appends_charset_to_sse(middleware: ForceJSONUTF8Middleware, mock_app: AsyncMock) -> None:
    # // given
    scope = {"type": "http"}
    receive = AsyncMock()
    send = AsyncMock()

    async def fake_app(scope: Any, receive: Any, send_wrapper: Any) -> None:
        await send_wrapper({
            "type": "http.response.start",
            "headers": [(b"content-type", b"text/event-stream")]
        })

    mock_app.side_effect = fake_app

    # // when
    await middleware(scope, receive, send)

    # // then
    args = send.call_args[0]
    message = args[0]
    headers = dict(message["headers"])
    assert headers[b"content-type"] == b"text/event-stream; charset=utf-8"


@pytest.mark.asyncio
async def test_call_adds_json_header_if_missing(middleware: ForceJSONUTF8Middleware, mock_app: AsyncMock) -> None:
    # // given
    scope = {"type": "http"}
    receive = AsyncMock()
    send = AsyncMock()

    async def fake_app(scope: Any, receive: Any, send_wrapper: Any) -> None:
        await send_wrapper({
            "type": "http.response.start",
            "headers": []
        })

    mock_app.side_effect = fake_app

    # // when
    await middleware(scope, receive, send)

    # // then
    args = send.call_args[0]
    message = args[0]
    headers = dict(message["headers"])
    assert headers[b"content-type"] == b"application/json; charset=utf-8"


@pytest.mark.asyncio
async def test_call_preserves_other_content_types(middleware: ForceJSONUTF8Middleware, mock_app: AsyncMock) -> None:
    # // given
    scope = {"type": "http"}
    receive = AsyncMock()
    send = AsyncMock()

    async def fake_app(scope: Any, receive: Any, send_wrapper: Any) -> None:
        await send_wrapper({
            "type": "http.response.start",
            "headers": [(b"content-type", b"image/png")]
        })

    mock_app.side_effect = fake_app

    # // when
    await middleware(scope, receive, send)

    # // then
    args = send.call_args[0]
    message = args[0]
    headers = dict(message["headers"])
    assert headers[b"content-type"] == b"image/png"
