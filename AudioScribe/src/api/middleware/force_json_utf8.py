"""ASGI middleware that normalises Content-Type so JSON and SSE responses
always carry `charset=utf-8`. FastMCP's underlying Starlette app can drop
the charset on certain streamed responses, causing browser clients to
mis-decode UTF-8 transcript bodies."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_HEADER_NAME = b"content-type"
_JSON_UTF8 = b"application/json; charset=utf-8"
_SSE_PREFIX = b"text/event-stream"
_CHARSET_FRAGMENT = b"charset="


def _find_content_type(raw_headers: list[tuple[bytes, bytes]]) -> tuple[int | None, bytes | None]:
    """Locate the content-type header in an ASGI header list."""

    for i, (k, v) in enumerate(raw_headers):
        if k.lower() == _HEADER_NAME:
            return i, v
    return None, None


def _split_main_and_params(val: bytes) -> tuple[bytes, bytes]:
    """Split `content-type: main; params` into main type and raw params."""

    if not val:
        return b"", b""
    parts = val.split(b";", 1)
    if len(parts) == 1:
        return parts[0].strip().lower(), b""
    return parts[0].strip().lower(), parts[1].strip()


def _normalise_headers(raw_headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    """Return a new header list with the content-type normalised so JSON and
    SSE responses always carry `charset=utf-8`."""

    ct_index, current_value = _find_content_type(raw_headers)
    if ct_index is None:
        # Missing content-type entirely: assume JSON (FastMCP's common default).
        return [*raw_headers, (_HEADER_NAME, _JSON_UTF8)]

    main, params = _split_main_and_params(current_value or b"")
    if main == b"application/json":
        raw_headers[ct_index] = (_HEADER_NAME, _JSON_UTF8)
    elif main == _SSE_PREFIX and _CHARSET_FRAGMENT not in params.lower():
        existing = params + b"; " if params else b""
        raw_headers[ct_index] = (_HEADER_NAME, _SSE_PREFIX + b"; " + existing + b"charset=utf-8")
    return raw_headers


class ForceJSONUTF8Middleware:
    """ASGI middleware. The dispatch flow is intentionally minimal: when the
    response start message arrives, rewrite headers via `_normalise_headers`
    and pass everything else through unchanged."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw_headers = list(message.get("headers", []))
                message["headers"] = _normalise_headers(raw_headers)
            await send(message)

        await self.app(scope, receive, send_wrapper)
