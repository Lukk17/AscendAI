import logging
import uuid
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

_correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")

CORRELATION_ID_HEADER: str = "x-request-id"


def get_correlation_id() -> str:
    return _correlation_id_var.get()


def set_correlation_id(value: str) -> None:
    _correlation_id_var.set(value)


class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)

            return

        incoming = _extract_header(scope, CORRELATION_ID_HEADER) or str(uuid.uuid4())
        token = _correlation_id_var.set(incoming)

        async def send_with_header(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.setdefault("headers", []))
                headers.append((CORRELATION_ID_HEADER.encode(), incoming.encode()))
                message["headers"] = headers

            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            _correlation_id_var.reset(token)


def _extract_header(scope: Scope, name: str) -> str | None:
    lowered = name.lower().encode()
    for key, value in scope.get("headers", []):
        if key.lower() == lowered:
            return str(value.decode())

    return None


class CorrelationIdLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = _correlation_id_var.get()

        return True
