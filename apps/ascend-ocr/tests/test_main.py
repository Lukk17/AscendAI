import asyncio
import logging
import socket
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import uvicorn
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from sse_starlette.sse import AppStatus
from starlette.types import Receive, Scope, Send

from src.api.middleware.correlation_id import CORRELATION_ID_HEADER, CorrelationIdLogFilter, digest_of_mcp_session_id
from src.config.config import MCP_ENDPOINT_PATH
from src.main import create_app
from src.model.ocr_models import FAILURE_SERVICE_RESTARTED
from src.observability.metrics import ENGINE_CACHE_EVICTIONS_TOTAL
from src.service import ocr_service as ocr_service_module
from src.service.job_runner import JobRunner
from src.service.job_store import JobStore
from src.service.ocr_service import request_worker_replacement_for_cancel
from tests.conftest import FakeResultStore, make_record


@pytest.fixture
def app_with_lifespan(
    jobs_dir: Path, results: FakeResultStore, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[FastAPI, MagicMock, MagicMock, MagicMock, JobStore, JobRunner]]:
    # start_worker_pool()/stop_worker_pool() are mocked so this test doesn't spawn a
    # real OS process and load a real PaddleOCR model just to exercise the lifespan,
    # and the result store is a fake so the lifespan's bucket check touches no network.
    _ = jobs_dir
    store = JobStore(results)
    runner = JobRunner(store, results)
    ensure_bucket = patch("src.main.result_store.ensure_bucket", return_value=True)
    monkeypatch.setattr("src.main.job_store", store)
    monkeypatch.setattr("src.main.job_runner", runner)

    with (
        patch("src.main.start_worker_pool") as mock_start_pool,
        patch("src.main.stop_worker_pool") as mock_stop_pool,
        ensure_bucket as mock_ensure_bucket,
    ):
        yield create_app(), mock_start_pool, mock_stop_pool, mock_ensure_bucket, store, runner


async def test_lifespan_starts_worker_pool_and_banner(app_with_lifespan):
    # Given. asgi-lifespan drives the ASGI lifespan protocol that httpx does not trigger by
    # default, so start_worker_pool, the MCP session manager startup, and the banner all run.
    app, mock_start_pool, mock_stop_pool, mock_ensure_bucket, _store, _runner = app_with_lifespan
    transport = ASGITransport(app=app)

    # When
    async with (
        LifespanManager(app),
        AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        response = await client.get("/health")
        mock_start_pool.assert_called_once()
        mock_ensure_bucket.assert_called_once()
        mock_stop_pool.assert_not_called()

    # Then
    assert response.status_code == 200
    mock_stop_pool.assert_called_once()


async def test_lifespan_recovers_work_in_flight_before_the_runner_starts(app_with_lifespan):
    # Given - a record left running by the previous process
    app, _start, _stop, _bucket, store, _runner = app_with_lifespan
    stranded = make_record(state="running", started_at=time.time())
    store.write(stranded)
    dispatch = AsyncMock()

    # When
    with patch("src.service.job_runner.dispatch_ocr_request", dispatch):
        async with LifespanManager(app):
            pass

    # Then - failed with a retryable reason, and never dispatched after the restart
    recovered = store.read(stranded.job_id)
    assert recovered.state == "failed"
    assert recovered.error_code == FAILURE_SERVICE_RESTARTED
    assert recovered.retryable is True
    dispatch.assert_not_awaited()


async def test_a_document_submitted_before_shutdown_is_terminal_after_the_next_startup(app_with_lifespan):
    # Given - a submission that never ran, exactly as a shutdown would leave it
    app, _start, _stop, _bucket, store, runner = app_with_lifespan
    record = make_record(state="waiting")
    await store.create(record, b"payload")

    # When - the next startup runs
    async with LifespanManager(app):
        pass

    # Then
    assert store.read(record.job_id).is_terminal is True
    assert runner.documents_waiting() == 0


def test_create_app_returns_fastapi_instance():
    # When
    app = create_app()

    # Then
    assert isinstance(app, FastAPI)


async def test_metrics_endpoint_reports_eviction_counter():
    # Given. Multiprocess mode (src/__init__.py) merges every process's own file in
    # PROMETHEUS_MULTIPROC_DIR at scrape time instead of reading in-process state, so
    # this also proves the merge path itself works, not just that the counter exists.
    ENGINE_CACHE_EVICTIONS_TOTAL.labels(engine="metrics-endpoint-probe").inc()
    app = create_app()
    transport = ASGITransport(app=app)

    # When
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/metrics")

    # Then
    assert response.status_code == 200
    assert "ascendocr_engine_cache_evictions_total" in response.text


async def test_shutdown_waits_for_a_worker_replacement_before_stopping_the_pool(app_with_lifespan, monkeypatch):
    # Given: a cancel's replacement still running when shutdown begins
    app, _start, mock_stop_pool, _bucket, _store, _runner = app_with_lifespan
    order: list[str] = []
    mock_stop_pool.side_effect = lambda: order.append("pool stopped")

    async def replacement() -> None:
        await asyncio.sleep(0.05)
        order.append("replacement finished")

    monkeypatch.setattr(ocr_service_module, "replace_worker_for_cancel", replacement)

    # When
    async with LifespanManager(app):
        request_worker_replacement_for_cancel()

    # Then
    assert order == ["replacement finished", "pool stopped"]


LOOPBACK = "127.0.0.1"
UVICORN_ACCESS_LOGGER = "uvicorn.access"
UVICORN_ERROR_LOGGER = "uvicorn.error"
GLOBAL_HANDLER_LOGGER = "src.api.exception_handlers"
MCP_SESSION_ID_HEADER = "mcp-session-id"
MCP_REQUEST_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
TOOLS_LIST_REQUEST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
CALLER_CHOSEN_ID = "caller-chosen-500"
INTERNAL_SERVER_ERROR = 500


class _UnhandledProbeError(Exception):
    pass


@dataclass(frozen=True)
class ServedService:
    client: AsyncClient
    records: list[logging.LogRecord]
    server: uvicorn.Server

    async def requests_in_flight_finished(self) -> None:
        await asyncio.gather(*self.server.server_state.tasks)

    def lines_of(self, correlation_id: str) -> list[logging.LogRecord]:
        return [record for record in self.records if getattr(record, "correlation_id", None) == correlation_id]

    def access_line_of(self, correlation_id: str) -> logging.LogRecord:
        [access_line] = [line for line in self.lines_of(correlation_id) if line.name == UVICORN_ACCESS_LOGGER]

        return access_line

    def error_lines(self) -> list[logging.LogRecord]:
        return [record for record in self.records if record.levelno >= logging.ERROR]


@pytest.fixture
async def served_service(
    app_with_lifespan: tuple[FastAPI, MagicMock, MagicMock, MagicMock, JobStore, JobRunner],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[ServedService]:
    app = app_with_lifespan[0]
    monkeypatch.setattr(AppStatus, "should_exit", False)
    records: list[logging.LogRecord] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _ListHandler(level=logging.NOTSET)
    handler.addFilter(CorrelationIdLogFilter())
    root = logging.getLogger()
    root.addHandler(handler)
    access_logger = logging.getLogger(UVICORN_ACCESS_LOGGER)
    previous_access_level = access_logger.level
    access_logger.setLevel(logging.INFO)
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, ws="none"))

    with socket.socket() as listening:
        listening.bind((LOOPBACK, 0))
        listening.listen()
        serving = asyncio.create_task(server.serve(sockets=[listening]))

        try:
            async with AsyncClient(base_url=f"http://{LOOPBACK}:{listening.getsockname()[1]}") as client:
                yield ServedService(client, records, server)
        finally:
            server.should_exit = True
            await serving
            access_logger.setLevel(previous_access_level)
            root.removeHandler(handler)


@pytest.fixture
def unhandled_mcp_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def raising_handle_request(
        _manager: StreamableHTTPSessionManager, _scope: Scope, _receive: Receive, _send: Send
    ) -> None:
        raise _UnhandledProbeError

    monkeypatch.setattr(StreamableHTTPSessionManager, "handle_request", raising_handle_request)


def _logged_status(access_line: logging.LogRecord) -> object:
    assert isinstance(access_line.args, tuple)

    return access_line.args[-1]


class TestSessionDigestOfTheServedApp:
    @pytest.mark.parametrize(("method", "path"), [("GET", "/health"), ("POST", "/v1/ocr/jobs")])
    async def test_a_rest_request_carrying_a_session_header_logs_no_session_field(
        self, served_service: ServedService, method: str, path: str
    ) -> None:
        # Given
        caller_chosen_session = uuid.uuid4().hex

        # When
        response = await served_service.client.request(
            method, path, headers={MCP_SESSION_ID_HEADER: caller_chosen_session}
        )

        # Then
        request_lines = served_service.lines_of(response.headers[CORRELATION_ID_HEADER])
        assert served_service.access_line_of(response.headers[CORRELATION_ID_HEADER]) in request_lines
        assert [line for line in request_lines if hasattr(line, "mcp_session_id")] == []

    async def test_the_404_access_line_of_an_unknown_session_logs_the_digest_of_the_value_sent(
        self, served_service: ServedService
    ) -> None:
        # Given
        unknown_session = uuid.uuid4().hex

        # When
        response = await served_service.client.post(
            MCP_ENDPOINT_PATH,
            headers={**MCP_REQUEST_HEADERS, MCP_SESSION_ID_HEADER: unknown_session},
            json=TOOLS_LIST_REQUEST,
        )

        # Then
        assert response.status_code == 404
        access_line = served_service.access_line_of(response.headers[CORRELATION_ID_HEADER])
        assert getattr(access_line, "mcp_session_id", None) == digest_of_mcp_session_id(unknown_session)


class TestUnhandledErrorOfTheServedApp:
    async def test_a_rest_500_answers_with_the_requests_id(self, served_service: ServedService) -> None:
        # When
        with patch("src.main.is_engine_warm", side_effect=_UnhandledProbeError):
            response = await served_service.client.get("/ready", headers={CORRELATION_ID_HEADER: CALLER_CHOSEN_ID})

        # Then
        assert response.status_code == INTERNAL_SERVER_ERROR
        assert response.headers[CORRELATION_ID_HEADER] == CALLER_CHOSEN_ID

    async def test_both_error_lines_and_the_access_line_of_a_rest_500_carry_the_requests_id(
        self, served_service: ServedService
    ) -> None:
        # When
        with patch("src.main.is_engine_warm", side_effect=_UnhandledProbeError):
            await served_service.client.get("/ready", headers={CORRELATION_ID_HEADER: CALLER_CHOSEN_ID})
        await served_service.requests_in_flight_finished()

        # Then
        error_lines = served_service.error_lines()
        assert sorted(line.name for line in error_lines) == [GLOBAL_HANDLER_LOGGER, UVICORN_ERROR_LOGGER]
        assert [getattr(line, "correlation_id", None) for line in error_lines] == [CALLER_CHOSEN_ID] * 2
        assert _logged_status(served_service.access_line_of(CALLER_CHOSEN_ID)) == INTERNAL_SERVER_ERROR

    async def test_both_error_lines_and_the_access_line_of_an_mcp_500_carry_the_requests_id_and_digest(
        self, unhandled_mcp_error: None, served_service: ServedService
    ) -> None:
        # Given
        session_id = uuid.uuid4().hex

        # When
        response = await served_service.client.post(
            MCP_ENDPOINT_PATH,
            headers={**MCP_REQUEST_HEADERS, MCP_SESSION_ID_HEADER: session_id, CORRELATION_ID_HEADER: CALLER_CHOSEN_ID},
            json=TOOLS_LIST_REQUEST,
        )
        await served_service.requests_in_flight_finished()

        # Then
        assert response.status_code == INTERNAL_SERVER_ERROR
        assert response.headers[CORRELATION_ID_HEADER] == CALLER_CHOSEN_ID
        logged = [served_service.access_line_of(CALLER_CHOSEN_ID), *served_service.error_lines()]
        assert [(getattr(line, "correlation_id", None), getattr(line, "mcp_session_id", None)) for line in logged] == [
            (CALLER_CHOSEN_ID, digest_of_mcp_session_id(session_id))
        ] * 3
