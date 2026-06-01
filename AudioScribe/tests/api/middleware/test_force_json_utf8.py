"""ForceJSONUTF8Middleware tests.

The middleware mutates `http.response.start` headers, so each test drives a
fake ASGI app via the middleware and asserts the header list shape on the
captured `send` calls. `send` and `app` are typed AsyncMocks so SonarLint's
async-without-await + Awaitable-callable type checks both pass.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.api.middleware.force_json_utf8 import ForceJSONUTF8Middleware


@pytest.mark.asyncio
async def test_middleware_passes_through_non_http() -> None:
    inner = AsyncMock()
    mw = ForceJSONUTF8Middleware(inner)
    scope = {"type": "lifespan"}
    await mw(scope, AsyncMock(), AsyncMock())
    inner.assert_awaited_once()


def _make_app(start_message: dict[str, Any]) -> AsyncMock:
    """Build a fake ASGI app whose only side-effect is emitting a single
    `http.response.start` message, then awaiting whatever the middleware
    wraps `send` with."""

    async def fake_app(_scope: Any, _receive: Any, send: AsyncMock) -> None:
        await send(start_message)

    return AsyncMock(side_effect=fake_app)


@pytest.mark.asyncio
async def test_default_content_type_is_json_utf8() -> None:
    send = AsyncMock()
    app = _make_app({"type": "http.response.start", "status": 200, "headers": []})
    await ForceJSONUTF8Middleware(app)({"type": "http"}, AsyncMock(), send)
    captured = send.await_args_list[0].args[0]
    assert (b"content-type", b"application/json; charset=utf-8") in captured["headers"]


@pytest.mark.asyncio
async def test_existing_json_gets_normalised() -> None:
    send = AsyncMock()
    app = _make_app({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"application/json")],
    })
    await ForceJSONUTF8Middleware(app)({"type": "http"}, AsyncMock(), send)
    captured = send.await_args_list[0].args[0]
    assert captured["headers"][0][1] == b"application/json; charset=utf-8"


@pytest.mark.asyncio
async def test_sse_without_charset_gets_charset_appended() -> None:
    send = AsyncMock()
    app = _make_app({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/event-stream")],
    })
    await ForceJSONUTF8Middleware(app)({"type": "http"}, AsyncMock(), send)
    captured = send.await_args_list[0].args[0]
    assert b"charset=utf-8" in captured["headers"][0][1]


@pytest.mark.asyncio
async def test_sse_with_params_preserves_them() -> None:
    send = AsyncMock()
    app = _make_app({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/event-stream; profile=foo")],
    })
    await ForceJSONUTF8Middleware(app)({"type": "http"}, AsyncMock(), send)
    captured = send.await_args_list[0].args[0]
    value = captured["headers"][0][1]
    assert b"profile=foo" in value
    assert b"charset=utf-8" in value


@pytest.mark.asyncio
async def test_existing_sse_with_charset_left_alone() -> None:
    send = AsyncMock()
    app = _make_app({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/event-stream; charset=utf-8")],
    })
    await ForceJSONUTF8Middleware(app)({"type": "http"}, AsyncMock(), send)
    captured = send.await_args_list[0].args[0]
    assert b"charset=utf-8" in captured["headers"][0][1]


@pytest.mark.asyncio
async def test_other_content_types_pass_through() -> None:
    send = AsyncMock()
    app = _make_app({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/markdown")],
    })
    await ForceJSONUTF8Middleware(app)({"type": "http"}, AsyncMock(), send)
    captured = send.await_args_list[0].args[0]
    assert captured["headers"][0][1] == b"text/markdown"


@pytest.mark.asyncio
async def test_empty_content_type_left_alone() -> None:
    send = AsyncMock()
    app = _make_app({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"")],
    })
    await ForceJSONUTF8Middleware(app)({"type": "http"}, AsyncMock(), send)
    captured = send.await_args_list[0].args[0]
    assert captured["headers"][0] == (b"content-type", b"")
