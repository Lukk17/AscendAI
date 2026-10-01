import hashlib
import logging
import re
import traceback
import uuid
import warnings
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Final

from mcp.server.streamable_http import MCP_SESSION_ID_HEADER, SESSION_ID_PATTERN
from starlette.types import ASGIApp, Receive, Scope, Send

_UNBOUND_CORRELATION_ID: Final[str] = "-"
_HEADER_ENCODING: Final[str] = "latin-1"
_SESSION_DIGEST_HEX_LENGTH: Final[int] = 16
_MCP_TRANSPORT_LOGGER_PREFIX: Final[str] = "mcp.server.streamable_http"
_MCP_SESSION_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32}(?![0-9A-Fa-f])")
_EXCEPTION_FORMATTER: Final[logging.Formatter] = logging.Formatter()
_REQUEST_LOG_IDS_ATTRIBUTE: Final[str] = "_ascend_ocr_request_log_ids"
_EXC_INFO_LENGTH: Final[int] = 3

_correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default=_UNBOUND_CORRELATION_ID)
_mcp_session_id_var: ContextVar[str | None] = ContextVar("mcp_session_id", default=None)

CORRELATION_ID_HEADER: str = "x-request-id"
CORRELATION_ID_SCOPE_KEY: str = "ascend_ocr.correlation_id"
ACCEPTED_CORRELATION_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9._:-]{1,128}")


class LogFilterFailureWarning(RuntimeWarning):
    pass


def get_correlation_id() -> str:
    return _correlation_id_var.get()


def bound_correlation_id() -> str | None:
    bound = _correlation_id_var.get()

    return None if bound == _UNBOUND_CORRELATION_ID else bound


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def digest_of_mcp_session_id(mcp_session_id: str) -> str:
    return hashlib.sha256(mcp_session_id.encode()).hexdigest()[:_SESSION_DIGEST_HEX_LENGTH]


def correlation_id_of(scope: Scope) -> str | None:
    carried = scope.get(CORRELATION_ID_SCOPE_KEY)

    return carried if isinstance(carried, str) else None


@contextmanager
def mcp_request_log_context(correlation_id: str, mcp_session_id: str | None) -> Iterator[None]:
    correlation_token = _correlation_id_var.set(correlation_id)
    session_token = _mcp_session_id_var.set(mcp_session_id)

    try:
        yield
    finally:
        _mcp_session_id_var.reset(session_token)
        _correlation_id_var.reset(correlation_token)


@contextmanager
def _mcp_session_digest_bound(mcp_session_digest: str | None) -> Iterator[None]:
    if mcp_session_digest is None:
        yield

        return

    token = _mcp_session_id_var.set(mcp_session_digest)

    try:
        yield
    finally:
        _mcp_session_id_var.reset(token)


@dataclass(frozen=True, slots=True)
class _RequestLogIds:
    correlation_id: str
    mcp_session_digest: str | None


class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp, mcp_endpoint_path: str) -> None:
        self.app = app
        self.mcp_endpoint_path = mcp_endpoint_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)

            return

        incoming = _accepted_correlation_id(scope)
        is_mcp_request = scope.get("path") == self.mcp_endpoint_path
        request_session_digest = _mcp_session_digest_in(scope.get("headers", [])) if is_mcp_request else None
        scope[CORRELATION_ID_SCOPE_KEY] = incoming
        token = _correlation_id_var.set(incoming)

        async def send_with_header(message: MutableMapping[str, Any]) -> None:
            if message["type"] != "http.response.start":
                await send(message)

                return

            headers = list(message.setdefault("headers", []))
            headers.append((CORRELATION_ID_HEADER.encode(), incoming.encode()))
            message["headers"] = headers
            announced_session_digest = _mcp_session_digest_in(headers) if is_mcp_request else None

            with _mcp_session_digest_bound(request_session_digest or announced_session_digest):
                await send(message)

        try:
            with _mcp_session_digest_bound(request_session_digest):
                await self.app(scope, receive, send_with_header)
        except BaseException as exc:
            setattr(exc, _REQUEST_LOG_IDS_ATTRIBUTE, _RequestLogIds(incoming, request_session_digest))

            raise
        finally:
            _correlation_id_var.reset(token)


def _accepted_correlation_id(scope: Scope) -> str:
    incoming = _extract_header(scope.get("headers", []), CORRELATION_ID_HEADER)
    if incoming is not None and ACCEPTED_CORRELATION_ID_PATTERN.fullmatch(incoming):
        return incoming

    return new_correlation_id()


def _mcp_session_digest_in(headers: Iterable[tuple[bytes, bytes]]) -> str | None:
    mcp_session_id = _extract_header(headers, MCP_SESSION_ID_HEADER)
    if mcp_session_id is None or not SESSION_ID_PATTERN.fullmatch(mcp_session_id):
        return None

    return digest_of_mcp_session_id(mcp_session_id)


def _extract_header(headers: Iterable[tuple[bytes, bytes]], name: str) -> str | None:
    lowered = name.lower().encode()
    for key, value in headers:
        if key.lower() == lowered:
            return str(value.decode(_HEADER_ENCODING))

    return None


class _NeverRaisingLogFilter(logging.Filter, ABC):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            self._apply(record)
        except Exception:
            warnings.warn(
                LogFilterFailureWarning(
                    f"{type(self).__name__} failed on a record of {record.name}, the line is kept as it stands:\n"
                    f"{traceback.format_exc()}"
                ),
                stacklevel=2,
            )

        return True

    @abstractmethod
    def _apply(self, record: logging.LogRecord) -> None:
        raise NotImplementedError


class CorrelationIdLogFilter(_NeverRaisingLogFilter):
    def _apply(self, record: logging.LogRecord) -> None:
        log_ids = _request_log_ids_carried_by(record) or _RequestLogIds(
            _correlation_id_var.get(), _mcp_session_id_var.get()
        )
        record.correlation_id = log_ids.correlation_id
        if log_ids.mcp_session_digest is not None:
            record.mcp_session_id = log_ids.mcp_session_digest


def _request_log_ids_carried_by(record: logging.LogRecord) -> _RequestLogIds | None:
    if _correlation_id_var.get() != _UNBOUND_CORRELATION_ID:
        return None

    carried = getattr(_exception_carried_by(record), _REQUEST_LOG_IDS_ATTRIBUTE, None)

    return carried if isinstance(carried, _RequestLogIds) else None


def _exception_carried_by(record: logging.LogRecord) -> BaseException | None:
    exc_info: object = record.exc_info
    if not isinstance(exc_info, tuple) or len(exc_info) != _EXC_INFO_LENGTH:
        return None

    exception = exc_info[1]

    return exception if isinstance(exception, BaseException) else None


class McpSessionIdRedactionFilter(_NeverRaisingLogFilter):
    def _apply(self, record: logging.LogRecord) -> None:
        if not record.name.startswith(_MCP_TRANSPORT_LOGGER_PREFIX):
            return

        record.msg = _redact_mcp_session_tokens(record.getMessage())
        record.args = None
        exception = _exception_carried_by(record)
        if exception is not None and not record.exc_text:
            record.exc_text = _EXCEPTION_FORMATTER.formatException(
                (type(exception), exception, exception.__traceback__)
            )
        if record.exc_text:
            record.exc_text = _redact_mcp_session_tokens(record.exc_text)
        record.exc_info = None


def _redact_mcp_session_tokens(text: str) -> str:
    return _MCP_SESSION_TOKEN_PATTERN.sub(lambda token: digest_of_mcp_session_id(token.group()), text)
