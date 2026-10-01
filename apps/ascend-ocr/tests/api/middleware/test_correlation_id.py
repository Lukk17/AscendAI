import asyncio
import hashlib
import logging
import re
import sys
import uuid
from collections.abc import MutableMapping
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware.correlation_id import (
    CORRELATION_ID_HEADER,
    CorrelationIdLogFilter,
    CorrelationIdMiddleware,
    LogFilterFailureWarning,
    McpSessionIdRedactionFilter,
    digest_of_mcp_session_id,
    get_correlation_id,
    mcp_request_log_context,
)

MAX_ACCEPTED_LENGTH = 128
UNBOUND_CORRELATION_ID = "-"
UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
SESSION_DIGEST_LENGTH = 16
MCP_TRANSPORT_LOGGER = "mcp.server.streamable_http_manager"
MCP_SESSION_ID_HEADER = "mcp-session-id"
MCP_ENDPOINT = "/mcp"
REST_PATH = "/v1/ocr/jobs"
CALLER_CHOSEN_ID = "caller-chosen-1"


class _RaisedInsideTheBlock(Exception):
    pass


def _fresh_filtered_record() -> logging.LogRecord:
    record = logging.LogRecord("t", logging.INFO, "", 0, "msg", (), None)
    CorrelationIdLogFilter().filter(record)

    return record


def _session_field_of_a_fresh_record() -> str | None:
    return getattr(_fresh_filtered_record(), "mcp_session_id", None)


@pytest.fixture
def app_with_correlation():
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware, mcp_endpoint_path=MCP_ENDPOINT)

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

    def test_keeps_an_inbound_header_of_the_longest_accepted_length(self, client):
        # Given
        inbound = "a" * MAX_ACCEPTED_LENGTH

        # When
        response = client.get("/echo", headers={CORRELATION_ID_HEADER: inbound})

        # Then
        assert response.headers[CORRELATION_ID_HEADER] == inbound

    @pytest.mark.parametrize(
        "inbound",
        [
            pytest.param(b"a" * (MAX_ACCEPTED_LENGTH + 1), id="overlong"),
            pytest.param(b"caller-\xff-id", id="non-utf-8-byte"),
            pytest.param(b"caller-\x01-id", id="control-character"),
            pytest.param(b"", id="empty"),
        ],
    )
    async def test_replaces_an_unacceptable_inbound_header_with_a_fresh_id(self, inbound: bytes) -> None:
        # Given
        records: list[logging.LogRecord] = []
        sent: list[MutableMapping[str, Any]] = []

        async def logging_app(scope, receive, send):
            record = logging.LogRecord("t", logging.INFO, "", 0, "msg", (), None)
            CorrelationIdLogFilter().filter(record)
            records.append(record)
            await send({"type": "http.response.start", "status": 200, "headers": []})

        async def capture(message: MutableMapping[str, Any]) -> None:
            sent.append(message)

        scope = {"type": "http", "headers": [(CORRELATION_ID_HEADER.encode(), inbound)]}

        # When
        await CorrelationIdMiddleware(logging_app, mcp_endpoint_path=MCP_ENDPOINT)(scope, AsyncMock(), capture)

        # Then
        [response_start] = sent
        echoed = dict(response_start["headers"])[CORRELATION_ID_HEADER.encode()].decode()
        assert re.fullmatch(UUID_PATTERN, echoed)
        assert [getattr(record, "correlation_id", None) for record in records] == [echoed]

    async def test_passes_through_non_http_scope(self):
        # Given
        called = {"count": 0}

        async def fake_app(scope, receive, send):
            called["count"] += 1

        receive = AsyncMock()
        send = AsyncMock()
        middleware = CorrelationIdMiddleware(fake_app, mcp_endpoint_path=MCP_ENDPOINT)

        # When
        await middleware({"type": "lifespan"}, receive, send)

        # Then
        assert called["count"] == 1


async def _serve_once(
    request_headers: list[tuple[bytes, bytes]], response_headers: list[tuple[bytes, bytes]], path: str = MCP_ENDPOINT
) -> tuple[logging.LogRecord, logging.LogRecord]:
    written: dict[str, logging.LogRecord] = {}

    async def app(scope, receive, send):
        written["in_app"] = _fresh_filtered_record()
        await send({"type": "http.response.start", "status": 200, "headers": response_headers})
        await send({"type": "http.response.body", "body": b""})

    async def server_send(message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.start":
            written["access_line"] = _fresh_filtered_record()

    await CorrelationIdMiddleware(app, mcp_endpoint_path=MCP_ENDPOINT)(
        {"type": "http", "path": path, "headers": request_headers}, AsyncMock(), server_send
    )

    return written["in_app"], written["access_line"]


class TestMcpSessionDigestOfTheHttpRequest:
    async def test_a_request_carrying_a_session_header_logs_its_digest_in_the_app_and_on_the_access_line(self):
        # Given
        session_id = uuid.uuid4().hex

        # When
        in_app, access_line = await _serve_once([(MCP_SESSION_ID_HEADER.encode(), session_id.encode())], [])

        # Then
        logged = [getattr(record, "mcp_session_id", None) for record in (in_app, access_line)]
        assert logged == [digest_of_mcp_session_id(session_id)] * 2

    async def test_a_session_announced_in_the_response_is_logged_on_the_access_line_only(self):
        # Given
        session_id = uuid.uuid4().hex

        # When
        in_app, access_line = await _serve_once([], [(MCP_SESSION_ID_HEADER.encode(), session_id.encode())])

        # Then
        assert not hasattr(in_app, "mcp_session_id")
        assert getattr(access_line, "mcp_session_id", None) == digest_of_mcp_session_id(session_id)

    async def test_a_request_without_any_session_header_logs_no_session_field(self):
        # When
        in_app, access_line = await _serve_once([], [])

        # Then
        assert not hasattr(in_app, "mcp_session_id")
        assert not hasattr(access_line, "mcp_session_id")

    @pytest.mark.parametrize(
        "malformed",
        [
            pytest.param(b"", id="empty"),
            pytest.param(b"session with spaces", id="space"),
            pytest.param(b"session-\xff", id="non-ascii-byte"),
            pytest.param(b"session-\x01", id="control-character"),
        ],
    )
    async def test_a_session_header_the_sdk_would_refuse_logs_no_session_field(self, malformed: bytes) -> None:
        # When
        in_app, access_line = await _serve_once(
            [(MCP_SESSION_ID_HEADER.encode(), malformed)], [(MCP_SESSION_ID_HEADER.encode(), malformed)]
        )

        # Then
        assert not hasattr(in_app, "mcp_session_id")
        assert not hasattr(access_line, "mcp_session_id")

    async def test_the_raw_session_id_reaches_no_record(self):
        # Given
        session_id = uuid.uuid4().hex

        # When
        records = await _serve_once(
            [(MCP_SESSION_ID_HEADER.encode(), session_id.encode())],
            [(MCP_SESSION_ID_HEADER.encode(), session_id.encode())],
        )

        # Then
        assert [record for record in records if session_id in str(vars(record))] == []

    async def test_nothing_stays_bound_after_the_request(self):
        # Given
        session_id = uuid.uuid4().hex

        # When
        await _serve_once(
            [(MCP_SESSION_ID_HEADER.encode(), session_id.encode())],
            [(MCP_SESSION_ID_HEADER.encode(), session_id.encode())],
        )

        # Then
        assert not hasattr(_fresh_filtered_record(), "mcp_session_id")
        assert get_correlation_id() == UNBOUND_CORRELATION_ID

    @pytest.mark.parametrize("path", [REST_PATH, "/health", MCP_ENDPOINT + "/"])
    async def test_a_request_outside_the_mcp_endpoint_logs_no_session_field(self, path: str) -> None:
        # Given
        session_id = uuid.uuid4().hex

        # When
        in_app, access_line = await _serve_once(
            [(MCP_SESSION_ID_HEADER.encode(), session_id.encode())],
            [(MCP_SESSION_ID_HEADER.encode(), session_id.encode())],
            path=path,
        )

        # Then
        assert not hasattr(in_app, "mcp_session_id")
        assert not hasattr(access_line, "mcp_session_id")


def _record_of_an_escaped(exception: BaseException) -> logging.LogRecord:
    record = logging.LogRecord("uvicorn.error", logging.ERROR, "", 0, "escaped", (), (type(exception), exception, None))
    CorrelationIdLogFilter().filter(record)

    return record


def _records_carrying(raw_session_id: str, records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return [record for record in records if raw_session_id in str(vars(record))]


def _mcp_scope(session_id: str) -> dict[str, object]:
    return {
        "type": "http",
        "path": MCP_ENDPOINT,
        "headers": [
            (MCP_SESSION_ID_HEADER.encode(), session_id.encode()),
            (CORRELATION_ID_HEADER.encode(), CALLER_CHOSEN_ID.encode()),
        ],
    }


class TestBindingAcrossTheRequestLifetime:
    async def test_an_app_raising_after_the_response_start_leaves_nothing_bound_and_no_raw_id(self):
        # Given
        session_id = uuid.uuid4().hex
        records: list[logging.LogRecord] = []

        async def app(scope, receive, send):
            records.append(_fresh_filtered_record())
            await send({"type": "http.response.start", "status": 200, "headers": []})
            raise _RaisedInsideTheBlock

        async def server_send(message: MutableMapping[str, Any]) -> None:
            records.append(_fresh_filtered_record())

        # When
        with pytest.raises(_RaisedInsideTheBlock) as raised:
            await CorrelationIdMiddleware(app, mcp_endpoint_path=MCP_ENDPOINT)(
                _mcp_scope(session_id), AsyncMock(), server_send
            )
        records.append(_record_of_an_escaped(raised.value))

        # Then
        assert get_correlation_id() == UNBOUND_CORRELATION_ID
        assert _session_field_of_a_fresh_record() is None
        assert _records_carrying(session_id, records) == []

    async def test_a_request_cancelled_inside_send_leaves_nothing_bound_and_no_raw_id(self):
        # Given
        session_id = uuid.uuid4().hex
        records: list[logging.LogRecord] = []
        sending = asyncio.Event()
        observed_after_cancel: list[tuple[str, str | None]] = []

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})

        async def stalled_server_send(message: MutableMapping[str, Any]) -> None:
            records.append(_fresh_filtered_record())
            sending.set()
            await asyncio.Event().wait()

        async def served() -> None:
            try:
                await CorrelationIdMiddleware(app, mcp_endpoint_path=MCP_ENDPOINT)(
                    _mcp_scope(session_id), AsyncMock(), stalled_server_send
                )
            finally:
                observed_after_cancel.append((get_correlation_id(), _session_field_of_a_fresh_record()))

        task = asyncio.create_task(served())
        await sending.wait()

        # When
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Then
        assert observed_after_cancel == [(UNBOUND_CORRELATION_ID, None)]
        assert _records_carrying(session_id, records) == []

    async def test_a_response_start_sent_from_a_task_the_app_starts_leaves_nothing_bound_and_no_raw_id(self):
        # Given
        session_id = uuid.uuid4().hex
        records: list[logging.LogRecord] = []

        async def streaming_app(scope, receive, send):
            async def stream() -> None:
                records.append(_fresh_filtered_record())
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"data: 1\n\n"})

            await asyncio.create_task(stream())

        async def server_send(message: MutableMapping[str, Any]) -> None:
            records.append(_fresh_filtered_record())

        # When
        await CorrelationIdMiddleware(streaming_app, mcp_endpoint_path=MCP_ENDPOINT)(
            _mcp_scope(session_id), AsyncMock(), server_send
        )

        # Then
        assert get_correlation_id() == UNBOUND_CORRELATION_ID
        assert _session_field_of_a_fresh_record() is None
        assert _records_carrying(session_id, records) == []

    async def test_every_line_of_a_response_streamed_from_a_task_carries_the_requests_ids(self):
        # Given
        session_id = uuid.uuid4().hex
        records: list[logging.LogRecord] = []

        async def streaming_app(scope, receive, send):
            async def stream() -> None:
                records.append(_fresh_filtered_record())
                await send({"type": "http.response.start", "status": 200, "headers": []})

            await asyncio.create_task(stream())

        async def server_send(message: MutableMapping[str, Any]) -> None:
            records.append(_fresh_filtered_record())

        # When
        await CorrelationIdMiddleware(streaming_app, mcp_endpoint_path=MCP_ENDPOINT)(
            _mcp_scope(session_id), AsyncMock(), server_send
        )

        # Then
        logged = [
            (getattr(record, "correlation_id", None), getattr(record, "mcp_session_id", None)) for record in records
        ]
        assert logged == [(CALLER_CHOSEN_ID, digest_of_mcp_session_id(session_id))] * 2


class TestEscapedExceptionRecords:
    async def test_a_record_of_an_escaped_exception_written_outside_the_request_carries_its_ids(self):
        # Given
        session_id = uuid.uuid4().hex

        async def app(scope, receive, send):
            raise _RaisedInsideTheBlock

        with pytest.raises(_RaisedInsideTheBlock) as raised:
            await CorrelationIdMiddleware(app, mcp_endpoint_path=MCP_ENDPOINT)(
                _mcp_scope(session_id), AsyncMock(), AsyncMock()
            )

        # When
        record = _record_of_an_escaped(raised.value)

        # Then
        assert getattr(record, "correlation_id", None) == CALLER_CHOSEN_ID
        assert getattr(record, "mcp_session_id", None) == digest_of_mcp_session_id(session_id)

    async def test_a_record_of_an_escaped_exception_written_inside_another_request_keeps_that_requests_ids(self):
        # Given
        async def app(scope, receive, send):
            raise _RaisedInsideTheBlock

        with pytest.raises(_RaisedInsideTheBlock) as raised:
            await CorrelationIdMiddleware(app, mcp_endpoint_path=MCP_ENDPOINT)(
                _mcp_scope(uuid.uuid4().hex), AsyncMock(), AsyncMock()
            )

        # When
        with mcp_request_log_context("other-request", "other-session"):
            record = _record_of_an_escaped(raised.value)

        # Then
        assert getattr(record, "correlation_id", None) == "other-request"
        assert getattr(record, "mcp_session_id", None) == "other-session"

    def test_a_record_of_an_exception_that_never_crossed_the_middleware_has_no_request_ids(self):
        # When
        record = _record_of_an_escaped(_RaisedInsideTheBlock())

        # Then
        assert getattr(record, "correlation_id", None) == UNBOUND_CORRELATION_ID
        assert not hasattr(record, "mcp_session_id")


class TestMcpRequestLogContext:
    def test_an_exception_inside_the_block_restores_the_previous_values(self):
        # When
        with pytest.raises(_RaisedInsideTheBlock), mcp_request_log_context("inner-id", "inner-session"):
            raise _RaisedInsideTheBlock

        # Then
        assert get_correlation_id() == UNBOUND_CORRELATION_ID
        assert _session_field_of_a_fresh_record() is None

    async def test_a_cancellation_inside_the_block_restores_the_previous_values(self):
        # Given
        entered = asyncio.Event()
        observed_after_cancel: list[tuple[str, str | None]] = []

        async def cancelled_inside_the_block() -> None:
            try:
                with mcp_request_log_context("inner-id", "inner-session"):
                    entered.set()
                    await asyncio.Event().wait()
            finally:
                observed_after_cancel.append((get_correlation_id(), _session_field_of_a_fresh_record()))

        task = asyncio.create_task(cancelled_inside_the_block())
        await entered.wait()

        # When
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Then
        assert observed_after_cancel == [(UNBOUND_CORRELATION_ID, None)]

    def test_a_nested_block_restores_the_outer_values(self):
        # Given
        with mcp_request_log_context("outer-id", "outer-session"):
            # When
            with mcp_request_log_context("inner-id", "inner-session"):
                pass

            # Then
            assert get_correlation_id() == "outer-id"
            assert _session_field_of_a_fresh_record() == "outer-session"


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

    def test_a_rest_request_logs_its_own_id_and_no_session_field(self):
        # Given
        records: list[logging.LogRecord] = []

        class _ListHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _ListHandler()
        handler.addFilter(CorrelationIdLogFilter())
        rest_logger = logging.getLogger("correlation-rest-probe")
        rest_logger.addHandler(handler)
        app = FastAPI()
        app.add_middleware(CorrelationIdMiddleware, mcp_endpoint_path=MCP_ENDPOINT)

        @app.get("/logged")
        def logged() -> dict[str, str]:
            rest_logger.warning("handled")

            return {}

        # When
        try:
            response = TestClient(app).get("/logged")
        finally:
            rest_logger.removeHandler(handler)

        # Then
        [record] = records
        assert getattr(record, "correlation_id", None) == response.headers[CORRELATION_ID_HEADER]
        assert not hasattr(record, "mcp_session_id")


def _sha256_prefix(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:SESSION_DIGEST_LENGTH]


def _record(name: str, message: str, args: tuple[object, ...] = (), exc_info: Any = None) -> logging.LogRecord:
    return logging.LogRecord(name, logging.INFO, "", 0, message, args, exc_info)


class TestDigestOfMcpSessionId:
    def test_is_the_first_sixteen_hex_characters_of_the_sha256(self):
        # Given
        session_id = uuid.uuid4().hex

        # When
        digest = digest_of_mcp_session_id(session_id)

        # Then
        assert digest == _sha256_prefix(session_id)


class TestMcpSessionIdRedactionFilter:
    def test_replaces_every_session_token_in_a_transport_line_with_its_digest(self):
        # Given
        first, second = uuid.uuid4().hex, uuid.uuid4().hex
        record = _record(MCP_TRANSPORT_LOGGER, "Session %s replaced " + second, (first,))

        # When
        kept = McpSessionIdRedactionFilter().filter(record)

        # Then
        assert kept is True
        assert record.getMessage() == f"Session {_sha256_prefix(first)} replaced {_sha256_prefix(second)}"
        assert record.args is None

    def test_redacts_the_session_token_in_the_traceback_of_a_transport_line(self):
        # Given
        session_id = uuid.uuid4().hex
        try:
            raise RuntimeError(f"session {session_id} broke")
        except RuntimeError:
            record = _record("mcp.server.streamable_http", f"Session {session_id} crashed", exc_info=sys.exc_info())

        # When
        McpSessionIdRedactionFilter().filter(record)
        formatted = logging.Formatter().format(record)

        # Then
        assert session_id not in formatted
        assert f"session {_sha256_prefix(session_id)} broke" in formatted
        assert record.exc_info is None

    def test_leaves_a_line_from_any_other_logger_untouched(self):
        # Given
        job_like_token = uuid.uuid4().hex
        record = _record("src.service.job_runner", "job %s", (job_like_token,))

        # When
        kept = McpSessionIdRedactionFilter().filter(record)

        # Then
        assert kept is True
        assert record.args == (job_like_token,)
        assert record.getMessage() == f"job {job_like_token}"

    def test_leaves_a_longer_hex_run_untouched(self):
        # Given
        longer_hex_run = uuid.uuid4().hex + "ab"
        record = _record(MCP_TRANSPORT_LOGGER, f"not a session {longer_hex_run}")

        # When
        McpSessionIdRedactionFilter().filter(record)

        # Then
        assert record.getMessage() == f"not a session {longer_hex_run}"


_EXC_INFO_WITHOUT_AN_EXCEPTION: list[object] = [True, False, 0, "", None, (None, None, None), (), ("not", "an", "exc")]


class _CollectingHandler(logging.Handler):
    def __init__(self, log_filter: logging.Filter) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.addFilter(log_filter)

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _records_logged_through(log_filter: logging.Filter, logger_name: str, log: Any) -> list[logging.LogRecord]:
    handler = _CollectingHandler(log_filter)
    probe_logger = logging.getLogger(logger_name)
    probe_logger.addHandler(handler)

    try:
        log(probe_logger)
    finally:
        probe_logger.removeHandler(handler)

    return handler.records


async def _exception_escaped_through_the_middleware() -> _RaisedInsideTheBlock:
    async def app(scope, receive, send):
        raise _RaisedInsideTheBlock

    with pytest.raises(_RaisedInsideTheBlock) as raised:
        await CorrelationIdMiddleware(app, mcp_endpoint_path=MCP_ENDPOINT)(
            _mcp_scope(uuid.uuid4().hex), AsyncMock(), AsyncMock()
        )

    return raised.value


class TestCorrelationIdLogFilterOnEveryExcInfoShape:
    @pytest.mark.parametrize("exc_info", _EXC_INFO_WITHOUT_AN_EXCEPTION)
    def test_a_record_built_directly_without_an_exception_gets_the_unbound_id(self, exc_info: object) -> None:
        # Given
        record = _record("opentelemetry.exporter.otlp.proto.grpc.exporter", "Failed to export", exc_info=exc_info)

        # When
        kept = CorrelationIdLogFilter().filter(record)

        # Then
        assert kept is True
        assert getattr(record, "correlation_id", None) == UNBOUND_CORRELATION_ID
        assert not hasattr(record, "mcp_session_id")

    @pytest.mark.parametrize("exc_info", [False, True, None])
    def test_a_logger_call_without_an_active_exception_is_logged_with_the_unbound_id(self, exc_info: object) -> None:
        # When
        records = _records_logged_through(
            CorrelationIdLogFilter(),
            "exc-info-shape-probe",
            lambda probe: probe.error("Failed to export %s", "traces", exc_info=exc_info),
        )

        # Then
        assert [(record.getMessage(), getattr(record, "correlation_id", None)) for record in records] == [
            ("Failed to export traces", UNBOUND_CORRELATION_ID)
        ]

    async def test_a_logger_call_carrying_an_escaped_exception_is_logged_with_its_request_id(self) -> None:
        # Given
        escaped = await _exception_escaped_through_the_middleware()

        def log_the_escaped_exception(probe: logging.Logger) -> None:
            try:
                raise escaped
            except _RaisedInsideTheBlock:
                probe.error("escaped", exc_info=True)

        # When
        records = _records_logged_through(CorrelationIdLogFilter(), "exc-info-shape-probe", log_the_escaped_exception)

        # Then
        assert [getattr(record, "correlation_id", None) for record in records] == [CALLER_CHOSEN_ID]

    async def test_a_record_built_directly_from_an_escaped_exception_instance_is_logged_with_its_request_id(self):
        # Given
        escaped = await _exception_escaped_through_the_middleware()

        # When
        records = _records_logged_through(
            CorrelationIdLogFilter(), "exc-info-shape-probe", lambda probe: probe.error("escaped", exc_info=escaped)
        )

        # Then
        assert [getattr(record, "correlation_id", None) for record in records] == [CALLER_CHOSEN_ID]


class TestMcpSessionIdRedactionFilterOnEveryExcInfoShape:
    @pytest.mark.parametrize("exc_info", _EXC_INFO_WITHOUT_AN_EXCEPTION)
    def test_a_transport_record_without_an_exception_is_redacted_and_still_formats(self, exc_info: object) -> None:
        # Given
        session_id = uuid.uuid4().hex
        record = _record(MCP_TRANSPORT_LOGGER, f"Session {session_id} closed", exc_info=exc_info)

        # When
        kept = McpSessionIdRedactionFilter().filter(record)
        formatted = logging.Formatter().format(record)

        # Then
        assert kept is True
        assert session_id not in formatted
        assert f"Session {_sha256_prefix(session_id)} closed" in formatted

    @pytest.mark.parametrize("exc_info", [False, True, None])
    def test_a_transport_logger_call_without_an_active_exception_is_redacted(self, exc_info: object) -> None:
        # Given
        session_id = uuid.uuid4().hex

        # When
        records = _records_logged_through(
            McpSessionIdRedactionFilter(),
            MCP_TRANSPORT_LOGGER,
            lambda probe: probe.error("Session %s closed", session_id, exc_info=exc_info),
        )

        # Then
        [record] = records
        formatted = logging.Formatter().format(record)
        assert session_id not in formatted
        assert f"Session {_sha256_prefix(session_id)} closed" in formatted

    def test_a_traceback_already_formatted_into_exc_text_is_redacted(self) -> None:
        # Given
        session_id = uuid.uuid4().hex
        record = _record(MCP_TRANSPORT_LOGGER, "Session crashed")
        record.exc_text = f"Traceback\nRuntimeError: session {session_id} broke"

        # When
        McpSessionIdRedactionFilter().filter(record)
        formatted = logging.Formatter().format(record)

        # Then
        assert session_id not in formatted
        assert f"session {_sha256_prefix(session_id)} broke" in formatted


class TestLogFilterFailure:
    def test_a_filter_failing_on_a_record_keeps_the_line_and_reports_the_failure_as_a_warning(self) -> None:
        # Given
        record = _record(MCP_TRANSPORT_LOGGER, "Session %s %s", ("only-one-argument",))

        # When
        with pytest.warns(LogFilterFailureWarning, match="McpSessionIdRedactionFilter") as reported:
            kept = McpSessionIdRedactionFilter().filter(record)

        # Then
        assert kept is True
        assert "TypeError" in str(reported[0].message)
        assert MCP_TRANSPORT_LOGGER in str(reported[0].message)
