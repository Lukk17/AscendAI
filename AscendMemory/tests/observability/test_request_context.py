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


def test_pattern_accepts_safe_ids():
    assert _REQUEST_ID_PATTERN.fullmatch("abc-123_45")
    assert _REQUEST_ID_PATTERN.fullmatch("x" * 128)


def test_pattern_rejects_unsafe_ids():
    assert _REQUEST_ID_PATTERN.fullmatch("") is None
    assert _REQUEST_ID_PATTERN.fullmatch("x" * 129) is None
    assert _REQUEST_ID_PATTERN.fullmatch("bad\r\nthing") is None
    assert _REQUEST_ID_PATTERN.fullmatch("bad space") is None


def _build_request(headers: dict[str, str] | None = None) -> Request:
    raw_headers: list[tuple[bytes, bytes]] = [
        (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
    ]
    # Cast: Starlette's Scope TypedDict carries more keys than our minimal
    # test scope; the cast tells static analysers we know what we're doing.
    scope = cast(
        "Scope",
        {
            "type": "http",
            "method": "GET",
            "path": "/health",
            "headers": raw_headers,
        },
    )
    return Request(scope)


class _FakeResponse:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}


@pytest.mark.asyncio
async def test_dispatch_echoes_valid_incoming_id():
    middleware = RequestIdMiddleware(app=AsyncMock())
    request = _build_request({REQUEST_ID_HEADER: "incoming-123"})
    response = _FakeResponse()

    call_next = AsyncMock(return_value=response)
    result = await middleware.dispatch(request, call_next)

    assert result.headers[REQUEST_ID_HEADER] == "incoming-123"


@pytest.mark.asyncio
async def test_dispatch_generates_uuid_when_no_header():
    middleware = RequestIdMiddleware(app=AsyncMock())
    request = _build_request()
    response = _FakeResponse()

    call_next = AsyncMock(return_value=response)
    result = await middleware.dispatch(request, call_next)

    rid = result.headers[REQUEST_ID_HEADER]
    assert len(rid) >= 16


@pytest.mark.asyncio
async def test_dispatch_generates_uuid_when_header_malformed():
    middleware = RequestIdMiddleware(app=AsyncMock())
    request = _build_request({REQUEST_ID_HEADER: "bad\nvalue"})
    response = _FakeResponse()

    call_next = AsyncMock(return_value=response)
    result = await middleware.dispatch(request, call_next)

    rid = result.headers[REQUEST_ID_HEADER]
    assert rid != "bad\nvalue"
    assert "\n" not in rid


@pytest.mark.asyncio
async def test_dispatch_resets_context_var_after_response():
    middleware = RequestIdMiddleware(app=AsyncMock())
    request = _build_request({REQUEST_ID_HEADER: "scoped"})
    response = _FakeResponse()

    call_next = AsyncMock(return_value=response)
    await middleware.dispatch(request, call_next)

    # The context var should reset to the default outside the request scope.
    assert request_id_ctx.get() == "-"
