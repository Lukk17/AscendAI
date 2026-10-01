import asyncio
import hashlib
import json
import logging
import re
import socket
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

import mcp.types as mt
import pytest
import uvicorn
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sse_starlette.sse import AppStatus

from src.api.mcp.mcp_server import mcp
from src.api.mcp.request_log_context import McpRequestLogContextMiddleware
from src.api.middleware.correlation_id import (
    CORRELATION_ID_HEADER,
    CorrelationIdLogFilter,
    CorrelationIdMiddleware,
    get_correlation_id,
    mcp_request_log_context,
)
from src.config.config import settings
from src.config.logging_config import setup_logging
from src.observability.tracing import MCP_SESSION_ID_SPAN_ATTRIBUTE, McpSessionDigestSpanExporter
from src.service.job_runner import JobRunner
from src.service.job_service import JobService
from src.service.job_store import JobStore, new_job_id
from tests.conftest import FakeResultStore

MCP_PATH = "/mcp"
MCP_SESSION_ID_HEADER = "mcp-session-id"
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_REQUEST_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
JOB_NOT_FOUND_MARKER = "JOB_NOT_FOUND"
PROBE_MARKER = "request-log-context-probe"
SESSION_DIGEST_LENGTH = 16
SESSION_DIGEST_PATTERN = rf"[0-9a-f]{{{SESSION_DIGEST_LENGTH}}}"
CALLER_CHOSEN_ID = "caller-chosen-1"
UNBOUND_CORRELATION_ID = "-"
FASTMCP_LOGGER = "fastmcp"
FASTMCP_TRACER_GETTER = "fastmcp.server.telemetry.get_tracer"
TOOL_NAME_SPAN_ATTRIBUTE = "gen_ai.tool.name"
JOB_STATUS_TOOL = "ocr_job_status"
UVICORN_ACCESS_LOGGER = "uvicorn.access"
LOOPBACK = "127.0.0.1"
REST_PROBE_PATH = "/rest-probe"


@dataclass(frozen=True)
class McpSession:
    client: AsyncClient
    session_id: str
    initialize_request_id: str


class _ProbeMiddleware(Middleware):
    async def on_request(
        self,
        context: MiddlewareContext[mt.Request[Any, Any]],
        call_next: CallNext[mt.Request[Any, Any], Any],
    ) -> Any:
        logging.getLogger(PROBE_MARKER).info("%s %s", PROBE_MARKER, context.method)

        return await call_next(context)


@pytest.fixture(autouse=True)
def service(store: JobStore, results: FakeResultStore, monkeypatch: pytest.MonkeyPatch) -> JobService:
    built = JobService(store, results, JobRunner(store, results))
    monkeypatch.setattr("src.api.mcp.mcp_server.job_service", built)

    return built


@pytest.fixture
def filtered_logs() -> Iterator[list[logging.LogRecord]]:
    records: list[logging.LogRecord] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _ListHandler(level=logging.NOTSET)
    handler.addFilter(CorrelationIdLogFilter())
    root = logging.getLogger()
    root.addHandler(handler)
    probe_logger = logging.getLogger(PROBE_MARKER)
    previous_probe_level = probe_logger.level
    probe_logger.setLevel(logging.INFO)

    try:
        yield records
    finally:
        probe_logger.setLevel(previous_probe_level)
        root.removeHandler(handler)


@pytest.fixture
def service_logs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Iterator[list[logging.LogRecord]]:
    records: list[logging.LogRecord] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    root = logging.getLogger()
    fastmcp_logger = logging.getLogger(FASTMCP_LOGGER)
    saved_root = (list(root.handlers), root.level)
    saved_fastmcp = (list(fastmcp_logger.handlers), fastmcp_logger.level, fastmcp_logger.propagate)
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
    setup_logging()
    root.addHandler(_ListHandler(level=logging.NOTSET))

    try:
        yield records
    finally:
        root.handlers[:] = saved_root[0]
        root.setLevel(saved_root[1])
        fastmcp_logger.handlers[:] = saved_fastmcp[0]
        fastmcp_logger.setLevel(saved_fastmcp[1])
        fastmcp_logger.propagate = saved_fastmcp[2]


@pytest.fixture
def exported_spans(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    exported = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(McpSessionDigestSpanExporter(exported)))
    monkeypatch.setattr(FASTMCP_TRACER_GETTER, lambda version=None: provider.get_tracer(FASTMCP_LOGGER, version))

    return exported


@pytest.fixture
def probe_every_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp, "middleware", [*mcp.middleware, _ProbeMiddleware()])


@pytest.fixture
async def mcp_session() -> AsyncIterator[McpSession]:
    mcp_app = mcp.http_app()
    app = FastAPI(lifespan=mcp_app.router.lifespan_context)
    app.add_middleware(CorrelationIdMiddleware, mcp_endpoint_path=MCP_PATH)
    app.mount("/", mcp_app)

    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        initialize = await client.post(
            MCP_PATH,
            headers=MCP_REQUEST_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "log-context-test", "version": "1"},
                },
            },
        )
        session_id = initialize.headers[MCP_SESSION_ID_HEADER]
        await client.post(
            MCP_PATH,
            headers=_session_headers(session_id),
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )

        yield McpSession(client, session_id, initialize.headers[CORRELATION_ID_HEADER])


@pytest.fixture
async def served_over_uvicorn(
    filtered_logs: list[logging.LogRecord], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(AppStatus, "should_exit", False)
    mcp_app = mcp.http_app()
    app = FastAPI(lifespan=mcp_app.router.lifespan_context)
    app.add_middleware(CorrelationIdMiddleware, mcp_endpoint_path=MCP_PATH)

    @app.get(REST_PROBE_PATH)
    def rest_probe() -> dict[str, str]:
        return {}

    app.mount("/", mcp_app)
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, ws="none"))
    access_logger = logging.getLogger(UVICORN_ACCESS_LOGGER)
    previous_access_level = access_logger.level
    access_logger.setLevel(logging.INFO)

    with socket.socket() as listening:
        listening.bind((LOOPBACK, 0))
        listening.listen()
        serving = asyncio.create_task(server.serve(sockets=[listening]))

        try:
            async with AsyncClient(base_url=f"http://{LOOPBACK}:{listening.getsockname()[1]}") as client:
                yield client
        finally:
            server.should_exit = True
            await serving
            access_logger.setLevel(previous_access_level)


async def _open_session(client: AsyncClient) -> tuple[str, str]:
    initialize = await client.post(
        MCP_PATH,
        headers=MCP_REQUEST_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "access-line-test", "version": "1"},
            },
        },
    )
    session_id = initialize.headers[MCP_SESSION_ID_HEADER]
    await client.post(
        MCP_PATH,
        headers=_session_headers(session_id),
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )

    return session_id, initialize.headers[CORRELATION_ID_HEADER]


def _access_lines(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return [record for record in records if record.name == UVICORN_ACCESS_LOGGER]


def _session_headers(session_id: str) -> dict[str, str]:
    return {**MCP_REQUEST_HEADERS, MCP_SESSION_ID_HEADER: session_id, "mcp-protocol-version": MCP_PROTOCOL_VERSION}


def _digest_of(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()[:SESSION_DIGEST_LENGTH]


async def _call_job_status_for_an_unknown_job(
    session: McpSession, call_id: int, extra_headers: dict[str, str] | None = None
) -> str:
    response = await session.client.post(
        MCP_PATH,
        headers={**_session_headers(session.session_id), **(extra_headers or {})},
        json={
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {"name": "ocr_job_status", "arguments": {"job_id": new_job_id()}},
        },
    )
    assert response.status_code == 200

    return response.headers[CORRELATION_ID_HEADER]


def _refusals(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return [record for record in records if JOB_NOT_FOUND_MARKER in record.getMessage()]


def _probes(records: list[logging.LogRecord], method: str) -> list[logging.LogRecord]:
    return [record for record in records if record.getMessage() == f"{PROBE_MARKER} {method}"]


def _fresh_record() -> logging.LogRecord:
    record = logging.LogRecord("t", logging.INFO, "", 0, "msg", (), None)
    CorrelationIdLogFilter().filter(record)

    return record


class TestToolCallsInOneSession:
    async def test_each_tool_call_logs_the_id_of_the_request_that_carried_it(
        self, mcp_session: McpSession, filtered_logs: list[logging.LogRecord]
    ) -> None:
        # When
        first_call_id = await _call_job_status_for_an_unknown_job(mcp_session, 2)
        second_call_id = await _call_job_status_for_an_unknown_job(mcp_session, 3)

        # Then
        logged_ids = [getattr(record, "correlation_id", None) for record in _refusals(filtered_logs)]
        assert logged_ids == [first_call_id, second_call_id]
        assert first_call_id != second_call_id
        assert mcp_session.initialize_request_id not in logged_ids

    async def test_every_tool_call_logs_the_digest_of_its_session_id_never_the_id_itself(
        self, mcp_session: McpSession, filtered_logs: list[logging.LogRecord]
    ) -> None:
        # When
        await _call_job_status_for_an_unknown_job(mcp_session, 2)
        await _call_job_status_for_an_unknown_job(mcp_session, 3)

        # Then
        logged_sessions = [getattr(record, "mcp_session_id", None) for record in _refusals(filtered_logs)]
        assert logged_sessions == [_digest_of(mcp_session.session_id)] * 2
        assert mcp_session.session_id not in logged_sessions

    async def test_a_caller_chosen_request_id_is_logged_and_echoed(
        self, mcp_session: McpSession, filtered_logs: list[logging.LogRecord]
    ) -> None:
        # When
        echoed = await _call_job_status_for_an_unknown_job(
            mcp_session, 2, extra_headers={CORRELATION_ID_HEADER: CALLER_CHOSEN_ID}
        )

        # Then
        [refusal] = _refusals(filtered_logs)
        assert getattr(refusal, "correlation_id", None) == CALLER_CHOSEN_ID
        assert echoed == CALLER_CHOSEN_ID


class TestRequestsOtherThanToolCalls:
    async def test_a_tools_list_request_logs_the_id_of_the_request_that_carried_it_and_the_session_digest(
        self, probe_every_request: None, mcp_session: McpSession, filtered_logs: list[logging.LogRecord]
    ) -> None:
        # When
        response = await mcp_session.client.post(
            MCP_PATH,
            headers=_session_headers(mcp_session.session_id),
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )

        # Then
        assert response.status_code == 200
        [probe] = _probes(filtered_logs, "tools/list")
        assert getattr(probe, "correlation_id", None) == response.headers[CORRELATION_ID_HEADER]
        assert getattr(probe, "mcp_session_id", None) == _digest_of(mcp_session.session_id)

    async def test_a_request_with_no_carrying_http_request_keeps_the_id_already_bound(self):
        # Given
        records: list[logging.LogRecord] = []
        context: MiddlewareContext[mt.Request[Any, Any]] = MiddlewareContext(
            message=mt.ListToolsRequest(method="tools/list"), type="request", method="tools/list", fastmcp_context=None
        )

        async def call_next(context: MiddlewareContext[mt.Request[Any, Any]]) -> None:
            records.append(_fresh_record())

        # When
        with mcp_request_log_context("initialize-request-id", None):
            await McpRequestLogContextMiddleware().on_request(context, call_next)

        # Then
        [record] = records
        assert getattr(record, "correlation_id", None) == "initialize-request-id"
        assert not hasattr(record, "mcp_session_id")


class TestToolCallOutsideAnHttpSession:
    async def test_a_call_over_an_in_memory_session_gets_an_id_of_its_own_and_a_session_digest(
        self, filtered_logs: list[logging.LogRecord]
    ) -> None:
        # When
        async with Client(mcp) as client:
            with pytest.raises(ToolError):
                await client.call_tool("ocr_job_status", {"job_id": new_job_id()})

        # Then
        [refusal] = _refusals(filtered_logs)
        assert getattr(refusal, "correlation_id", UNBOUND_CORRELATION_ID) != UNBOUND_CORRELATION_ID
        assert re.fullmatch(SESSION_DIGEST_PATTERN, getattr(refusal, "mcp_session_id", ""))

    async def test_a_middleware_context_with_no_fastmcp_context_still_gets_an_id(self):
        # Given
        records: list[logging.LogRecord] = []
        context: MiddlewareContext[mt.Request[Any, Any]] = MiddlewareContext(
            message=mt.ListToolsRequest(method="tools/list"), type="request", method="tools/list", fastmcp_context=None
        )

        async def call_next(context: MiddlewareContext[mt.Request[Any, Any]]) -> None:
            records.append(_fresh_record())

        # When
        await McpRequestLogContextMiddleware().on_request(context, call_next)

        # Then
        [record] = records
        assert getattr(record, "correlation_id", UNBOUND_CORRELATION_ID) != UNBOUND_CORRELATION_ID
        assert not hasattr(record, "mcp_session_id")

    async def test_a_call_with_no_carrying_request_gets_an_id_of_its_own_and_no_session(
        self, filtered_logs: list[logging.LogRecord]
    ) -> None:
        # When
        with pytest.raises(ToolError):
            await mcp.call_tool("ocr_job_status", {"job_id": new_job_id()})

        # Then
        [refusal] = _refusals(filtered_logs)
        assert getattr(refusal, "correlation_id", UNBOUND_CORRELATION_ID) != UNBOUND_CORRELATION_ID
        assert not hasattr(refusal, "mcp_session_id")

    async def test_a_direct_call_leaves_nothing_bound_in_the_callers_task(self):
        # When
        with pytest.raises(ToolError):
            await mcp.call_tool("ocr_job_status", {"job_id": new_job_id()})

        # Then
        assert get_correlation_id() == UNBOUND_CORRELATION_ID
        assert not hasattr(_fresh_record(), "mcp_session_id")


class TestAccessLines:
    async def test_the_access_line_of_a_request_carrying_a_session_header_logs_its_id_and_the_session_digest(
        self, served_over_uvicorn: AsyncClient, filtered_logs: list[logging.LogRecord]
    ) -> None:
        # Given
        session_id, _ = await _open_session(served_over_uvicorn)
        filtered_logs.clear()

        # When
        response = await served_over_uvicorn.post(
            MCP_PATH,
            headers=_session_headers(session_id),
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )

        # Then
        [access_line] = _access_lines(filtered_logs)
        assert getattr(access_line, "correlation_id", None) == response.headers[CORRELATION_ID_HEADER]
        assert getattr(access_line, "mcp_session_id", None) == _digest_of(session_id)

    async def test_the_access_line_of_initialize_logs_the_digest_of_the_session_it_opened(
        self, served_over_uvicorn: AsyncClient, filtered_logs: list[logging.LogRecord]
    ) -> None:
        # When
        session_id, initialize_request_id = await _open_session(served_over_uvicorn)

        # Then
        [access_line] = [
            line
            for line in _access_lines(filtered_logs)
            if getattr(line, "correlation_id", None) == initialize_request_id
        ]
        assert getattr(access_line, "mcp_session_id", None) == _digest_of(session_id)

    async def test_a_rest_access_line_after_an_mcp_request_logs_no_session_field(
        self, served_over_uvicorn: AsyncClient, filtered_logs: list[logging.LogRecord]
    ) -> None:
        # Given
        session_id, _ = await _open_session(served_over_uvicorn)
        await served_over_uvicorn.post(
            MCP_PATH,
            headers=_session_headers(session_id),
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
        filtered_logs.clear()

        # When
        response = await served_over_uvicorn.get(REST_PROBE_PATH)

        # Then
        [access_line] = _access_lines(filtered_logs)
        assert getattr(access_line, "correlation_id", None) == response.headers[CORRELATION_ID_HEADER]
        assert not hasattr(access_line, "mcp_session_id")

    async def test_no_record_from_initialize_to_delete_carries_the_raw_session_id(
        self, served_over_uvicorn: AsyncClient, filtered_logs: list[logging.LogRecord]
    ) -> None:
        # Given
        session_id, _ = await _open_session(served_over_uvicorn)
        await served_over_uvicorn.post(
            MCP_PATH,
            headers=_session_headers(session_id),
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )

        # When
        await served_over_uvicorn.delete(MCP_PATH, headers=_session_headers(session_id))

        # Then
        access_lines = _access_lines(filtered_logs)
        assert [getattr(line, "mcp_session_id", None) for line in access_lines] == [_digest_of(session_id)] * 4
        assert [line for line in access_lines if session_id in str(vars(line))] == []


class TestRawSessionIdNeverLeavesTheProcess:
    async def test_no_log_record_or_json_line_carries_the_raw_session_id_from_initialize_to_delete(
        self, service_logs: list[logging.LogRecord], mcp_session: McpSession, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # When
        await _call_job_status_for_an_unknown_job(mcp_session, 2)
        deleted = await mcp_session.client.delete(MCP_PATH, headers=_session_headers(mcp_session.session_id))
        written = capsys.readouterr()

        # Then
        assert deleted.status_code == 200
        digest = _digest_of(mcp_session.session_id)
        messages = [record.getMessage() + (record.exc_text or "") for record in service_logs]
        json_lines = [json.loads(line) for line in (written.err + written.out).splitlines() if line.startswith("{")]
        assert [message for message in messages if mcp_session.session_id in message] == []
        assert mcp_session.session_id not in written.err + written.out
        assert any(digest in message for message in messages)
        assert any(digest in json.dumps(line) for line in json_lines)

    async def test_the_tool_span_carries_the_session_digest_and_never_the_session_id(
        self, exported_spans: InMemorySpanExporter, mcp_session: McpSession
    ) -> None:
        # When
        await _call_job_status_for_an_unknown_job(mcp_session, 2)

        # Then
        spans = exported_spans.get_finished_spans()
        [tool_span] = [
            span for span in spans if (span.attributes or {}).get(TOOL_NAME_SPAN_ATTRIBUTE) == JOB_STATUS_TOOL
        ]
        assert (tool_span.attributes or {}).get(MCP_SESSION_ID_SPAN_ATTRIBUTE) == _digest_of(mcp_session.session_id)
        exported_values = [str(value) for span in spans for value in (span.attributes or {}).values()]
        assert mcp_session.session_id not in exported_values
