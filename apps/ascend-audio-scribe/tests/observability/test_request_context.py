from typing import cast
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request
from starlette.types import Scope

from src.observability.request_context import (
    _REQUEST_ID_PATTERN,
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    request_id_ctx,
)


def test_pattern_accepts_safe_ids() -> None:
    assert _REQUEST_ID_PATTERN.fullmatch("abc-123_45")
    assert _REQUEST_ID_PATTERN.fullmatch("x" * 128)


def test_pattern_rejects_unsafe_ids() -> None:
    assert _REQUEST_ID_PATTERN.fullmatch("") is None
    assert _REQUEST_ID_PATTERN.fullmatch("x" * 129) is None
    assert _REQUEST_ID_PATTERN.fullmatch("bad\r\nthing") is None


def _build_request(headers: dict[str, str] | None = None) -> Request:
    raw_headers: list[tuple[bytes, bytes]] = [
        (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
    ]
    scope = cast(
        "Scope",
        {"type": "http", "method": "GET", "path": "/", "headers": raw_headers},
    )
    return Request(scope)


class _FakeResponse:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}


@pytest.mark.asyncio
async def test_dispatch_echoes_valid_id() -> None:
    middleware = RequestIdMiddleware(app=AsyncMock())
    request = _build_request({REQUEST_ID_HEADER: "incoming-123"})
    call_next = AsyncMock(return_value=_FakeResponse())
    result = await middleware.dispatch(request, call_next)
    assert result.headers[REQUEST_ID_HEADER] == "incoming-123"


@pytest.mark.asyncio
async def test_dispatch_generates_uuid_when_missing() -> None:
    middleware = RequestIdMiddleware(app=AsyncMock())
    request = _build_request()
    call_next = AsyncMock(return_value=_FakeResponse())
    result = await middleware.dispatch(request, call_next)
    assert len(result.headers[REQUEST_ID_HEADER]) >= 16


@pytest.mark.asyncio
async def test_dispatch_generates_uuid_when_malformed() -> None:
    middleware = RequestIdMiddleware(app=AsyncMock())
    request = _build_request({REQUEST_ID_HEADER: "bad\nvalue"})
    call_next = AsyncMock(return_value=_FakeResponse())
    result = await middleware.dispatch(request, call_next)
    rid = result.headers[REQUEST_ID_HEADER]
    assert "\n" not in rid
    assert rid != "bad\nvalue"


@pytest.mark.asyncio
async def test_dispatch_resets_contextvar() -> None:
    middleware = RequestIdMiddleware(app=AsyncMock())
    request = _build_request({REQUEST_ID_HEADER: "scoped"})
    call_next = AsyncMock(return_value=_FakeResponse())
    await middleware.dispatch(request, call_next)
    assert request_id_ctx.get() == "-"
