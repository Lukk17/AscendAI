import asyncio
import importlib
import json
import logging
import re
import socket
import tomllib
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter, UploadFile
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from prometheus_client import REGISTRY
from pydantic import Field, ValidationError

from ascend_python_common import __version__
from ascend_python_common.app import ServiceDefinition, create_service_app
from ascend_python_common.errors import ErrorRegistry
from ascend_python_common.errors.codes import (
    INTERNAL_FIXED_DETAIL,
    RATE_LIMITED,
    VALIDATION,
    ProblemCode,
)
from ascend_python_common.readiness import ProbeResult
from ascend_python_common.request_context import digest_of_mcp_session_id
from ascend_python_common.settings import McpFetchSettings, RateLimit, ServiceSettings
from ascend_python_common.startup_banner import (
    CONFIGURED,
    CONNECTED,
    BannerCheck,
    BannerLine,
    BannerSection,
    build_banner,
    format_check,
    render_section,
    render_value,
    strip_user_info,
)
from ascend_python_common.tooling import assert_pyproject_conforms
from ascend_python_common.tracing import current_trace_id
from ascend_python_common.uri_guard import (
    FetchPolicy,
    FetchTarget,
    HopAnswer,
    UnsafeUriError,
    check_fetch_uri,
    follow_guarded_redirects,
)
from ascend_python_common.uri_guard_aiohttp import PinnedResolver, pinned_scope

SERVICE_NAME = "sample-service"
MCP_SERVER_NAME = "ascend-memory"
TRACE_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
KNOWN_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
KNOWN_PARENT_SPAN_ID = "00f067aa0ba902b7"

_SETTINGS_ENV_VARS: tuple[str, ...] = (
    "API_HOST",
    "API_PORT",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "RATE_LIMIT_DEFAULT",
    "READINESS_PROBE_TIMEOUT_SECONDS",
    "STARTUP_PROBE_TIMEOUT_SECONDS",
    "SECURITY_HSTS_MAX_AGE_SECONDS",
    "FETCH_MAX_REDIRECT_HOPS",
    "ALLOWED_PRIVATE_HOSTS",
    "MCP_FILE_URI_ROOT",
    "MCP_DOWNLOAD_TIMEOUT_SECONDS",
    "MCP_ALLOWED_HOSTS",
)


class _SampleSettings(ServiceSettings):
    API_PORT: int = 9917
    RATE_LIMIT_DEFAULT: RateLimit = "100/minute"


class _TightSettings(ServiceSettings):
    API_PORT: int = 9917
    RATE_LIMIT_DEFAULT: RateLimit = "2/minute"


class JobNotFoundError(Exception):
    pass


class DownloadFailedError(Exception):
    pass


class CaptchaNeededError(Exception):
    def __init__(self, vnc_url: str) -> None:
        super().__init__("Manual Captcha resolution required")
        self.vnc_url = vnc_url


class BrowserBusyError(Exception):
    def __init__(self, holder_url: str, holder_profile: str) -> None:
        super().__init__("Remote browser is busy")
        self.holder_url = holder_url
        self.holder_profile = holder_profile


class RateBudgetExceededError(Exception):
    pass


_captured_handler_trace_ids: list[str | None] = []


def _registry() -> ErrorRegistry:
    registry = ErrorRegistry()
    registry.register(JobNotFoundError, ProblemCode("JOB_NOT_FOUND", 404), "job not found")
    registry.register(
        DownloadFailedError,
        ProblemCode("DOWNLOAD_FAILED", 502),
        "download failed at upstream",
        expected=True,
    )
    registry.register(
        CaptchaNeededError,
        ProblemCode("human_intervention_required", 428),
        str,
        extensions=lambda exc: {
            "intervention_type": "captcha",
            "vnc_url": exc.vnc_url if isinstance(exc, CaptchaNeededError) else "",
        },
        expected=True,
    )
    registry.register(
        BrowserBusyError,
        ProblemCode("novnc_busy", 409),
        str,
        headers={"Retry-After": "30"},
        extensions=lambda exc: {
            "holder_url": exc.holder_url if isinstance(exc, BrowserBusyError) else "",
            "holder_profile": exc.holder_profile if isinstance(exc, BrowserBusyError) else "",
        },
        expected=True,
    )
    registry.register(ValueError, VALIDATION, str)
    registry.register(RateBudgetExceededError, RATE_LIMITED, "slow down")
    return registry


def _router() -> APIRouter:
    router = APIRouter()

    @router.get("/jobs/{job_id}")
    def read_job(job_id: str) -> dict[str, str]:
        raise JobNotFoundError(f"unknown job {job_id}")

    @router.get("/download")
    def download() -> dict[str, str]:
        raise DownloadFailedError("upstream said 502")

    @router.get("/web/read-captcha")
    def read_captcha() -> dict[str, str]:
        raise CaptchaNeededError("https://abc123.ngrok.io/vnc.html?autoconnect=true")

    @router.get("/web/read-busy")
    def read_busy() -> dict[str, str]:
        raise BrowserBusyError("https://holder.example/vnc", "profile-1")

    @router.get("/boom")
    def boom() -> dict[str, str]:
        _captured_handler_trace_ids.append(current_trace_id())
        raise RuntimeError("kaboom-secret-boom")

    @router.get("/limited")
    def limited() -> dict[str, str]:
        return {"status": "ok"}

    @router.post("/v1/ocr/jobs")
    def submit_job(file: UploadFile) -> dict[str, str]:
        return {"status": "ok", "filename": file.filename or ""}

    return router


def _mcp_server(name: str = MCP_SERVER_NAME) -> FastMCP:
    server = FastMCP(name)

    @server.tool
    def memory_insert(text: str) -> str:
        if not text.strip():
            raise ValueError("text must not be empty")
        return "inserted"

    @server.tool
    def boom_tool() -> str:
        raise RuntimeError("kaboom-secret-tool")

    @server.tool
    def ocr_submit() -> str:
        return "submitted"

    @server.tool
    def ocr_job_status() -> str:
        return "status-ok"

    @server.tool
    def rate_probe_one() -> str:
        raise RateBudgetExceededError("one")

    @server.tool
    def rate_probe_two() -> str:
        raise RateBudgetExceededError("two")

    return server


async def _ok_probe() -> ProbeResult:
    return ProbeResult(status="ok")


async def _failing_probe() -> ProbeResult:
    return ProbeResult(status="error")


def _definition(
    *,
    settings: ServiceSettings | None = None,
    probes: dict[str, Any] | None = None,
    service_name: str = SERVICE_NAME,
    mcp_name: str = MCP_SERVER_NAME,
) -> ServiceDefinition:
    return ServiceDefinition(
        name=service_name,
        distribution="ascend-python-common",
        settings=settings if settings is not None else _SampleSettings(),
        mcp=_mcp_server(mcp_name),
        routers=(_router(),),
        error_registry=_registry(),
        probes=probes if probes is not None else {"ok": _ok_probe},
    )


def _client(definition: ServiceDefinition) -> TestClient:
    app = create_service_app(definition)
    return TestClient(app, raise_server_exceptions=False)


def _counter(code: str, surface: str, operation: str) -> float:
    value = REGISTRY.get_sample_value(
        "ascend_service_errors_total",
        {"code": code, "surface": surface, "operation": operation},
    )
    return float(value) if value is not None else 0.0


@pytest.fixture(autouse=True)
def _clean_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _isolated_tracer() -> Any:
    from opentelemetry import trace
    from opentelemetry.util._once import Once

    saved_provider = trace._TRACER_PROVIDER
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE = Once()
    yield
    trace._TRACER_PROVIDER = saved_provider
    trace._TRACER_PROVIDER_SET_ONCE = Once()


def test_a_services_own_refusal() -> None:
    # given
    client = _client(_definition())
    # when
    response = client.get("/jobs/does-not-exist")
    # then
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "JOB_NOT_FOUND"
    assert body["type"] == "https://ascend.ai/errors/job-not-found"
    assert body["instance"] == "/jobs/does-not-exist"
    assert TRACE_ID_PATTERN.fullmatch(body["traceId"])


def test_an_unknown_path() -> None:
    # given
    client = _client(_definition())
    # when
    response = client.get("/does-not-exist")
    # then
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "not_found"


def test_a_method_the_path_does_not_support() -> None:
    # given
    client = _client(_definition())
    # when
    response = client.delete("/health")
    # then
    assert response.status_code == 405
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "method_not_allowed"
    assert "GET" in response.headers["allow"]


def test_an_unexpected_exception() -> None:
    # given
    _captured_handler_trace_ids.clear()
    client = _client(_definition())
    # when
    response = client.get("/boom")
    # then
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal"
    assert body["detail"] == INTERNAL_FIXED_DETAIL
    assert "RuntimeError" not in response.text
    assert "kaboom-secret-boom" not in response.text
    assert _captured_handler_trace_ids != []
    assert body["traceId"] == _captured_handler_trace_ids[-1]
    assert TRACE_ID_PATTERN.fullmatch(body["traceId"])


def test_an_upstream_failure_keeps_its_detail() -> None:
    # given
    client = _client(_definition())
    # when
    response = client.get("/download")
    # then
    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "DOWNLOAD_FAILED"
    assert body["detail"] == "download failed at upstream"
    assert body["detail"] != INTERNAL_FIXED_DETAIL


def test_human_help_needed_on_ascend_web_hunter() -> None:
    # given
    client = _client(_definition())
    # when
    response = client.get("/web/read-captcha")
    # then
    assert response.status_code == 428
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "human_intervention_required"
    assert body["type"] == "https://ascend.ai/errors/human-intervention-required"
    assert TRACE_ID_PATTERN.fullmatch(body["traceId"])
    assert body["intervention_type"] == "captcha"
    assert body["vnc_url"] != ""
    assert "message" not in body
    assert body["status"] == 428


def test_the_remote_browser_is_busy_on_ascend_web_hunter() -> None:
    # given
    client = _client(_definition())
    # when
    response = client.get("/web/read-busy")
    # then
    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "novnc_busy"
    assert body["holder_url"] != ""
    assert body["holder_profile"] != ""
    assert "Retry-After" in response.headers


def test_a_request_that_started_a_trace_elsewhere() -> None:
    # given
    client = _client(_definition())
    traceparent = f"00-{KNOWN_TRACE_ID}-{KNOWN_PARENT_SPAN_ID}-01"
    # when
    response = client.get("/does-not-exist", headers={"traceparent": traceparent})
    # then
    assert response.status_code == 404
    assert response.json()["traceId"] == KNOWN_TRACE_ID


def test_a_missing_upload_part() -> None:
    # given
    client = _client(_definition())
    # when
    response = client.post("/v1/ocr/jobs", files={})
    # then
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation"
    assert "errors" in body
    fields = [entry["field"] for entry in body["errors"]]
    assert "file" in fields
    assert fields == sorted(fields)
    assert all("message" in entry for entry in body["errors"])


def test_a_refusal_over_rest(caplog: pytest.LogCaptureFixture) -> None:
    # given
    client = _client(_definition())
    logging.getLogger().addHandler(caplog.handler)
    before = _counter("JOB_NOT_FOUND", "rest", "/jobs/{job_id}")
    # when
    with caplog.at_level(logging.WARNING):
        response = client.get("/jobs/abc")
    # then
    assert response.status_code == 404
    assert any("JOB_NOT_FOUND" in record.getMessage() for record in caplog.records)
    assert not any(record.exc_text for record in caplog.records)
    assert _counter("JOB_NOT_FOUND", "rest", "/jobs/{job_id}") == before + 1


def test_the_same_refusal_over_mcp(caplog: pytest.LogCaptureFixture) -> None:
    # given
    definition = _definition()
    create_service_app(definition)
    logging.getLogger().addHandler(caplog.handler)
    before = _counter("validation", "mcp", "memory_insert")

    async def _calls() -> str:
        # when
        async with Client(definition.mcp) as mcp_client:
            with pytest.raises(ToolError) as exc_info:
                await mcp_client.call_tool("memory_insert", {"text": ""})
            return str(exc_info.value)

    import asyncio

    # when
    with caplog.at_level(logging.WARNING):
        message = asyncio.run(_calls())
    # then
    assert message.startswith("validation: ")
    assert any("validation" in record.getMessage() for record in caplog.records)
    assert _counter("validation", "mcp", "memory_insert") == before + 1


def test_two_tools_refused_with_the_same_code() -> None:
    # given
    definition = _definition()

    async def _calls() -> tuple[str, str]:
        # when
        async with Client(definition.mcp) as mcp_client:
            first_error = ""
            second_error = ""
            with pytest.raises(ToolError) as first_info:
                await mcp_client.call_tool("rate_probe_one", {})
            first_error = str(first_info.value)
            with pytest.raises(ToolError) as second_info:
                await mcp_client.call_tool("rate_probe_two", {})
            second_error = str(second_info.value)
            return first_error, second_error

    import asyncio

    create_service_app(definition)
    before_first = _counter("rate_limited", "mcp", "rate_probe_one")
    before_second = _counter("rate_limited", "mcp", "rate_probe_two")
    # when
    first_error, second_error = asyncio.run(_calls())
    # then
    assert first_error.startswith("rate_limited: ")
    assert second_error.startswith("rate_limited: ")
    assert _counter("rate_limited", "mcp", "rate_probe_one") == before_first + 1
    assert _counter("rate_limited", "mcp", "rate_probe_two") == before_second + 1


def test_an_empty_memory_text_over_mcp() -> None:
    # given
    definition = _definition()
    create_service_app(definition)

    async def _calls() -> str:
        # when
        async with Client(definition.mcp) as mcp_client:
            with pytest.raises(ToolError) as exc_info:
                await mcp_client.call_tool("memory_insert", {"text": "   "})
            return str(exc_info.value)

    import asyncio

    # when
    message = asyncio.run(_calls())
    # then
    assert message.startswith("validation: ")


def test_an_unexpected_failure_over_mcp() -> None:
    # given
    definition = _definition()
    create_service_app(definition)

    async def _calls() -> str:
        # when
        async with Client(definition.mcp) as mcp_client:
            with pytest.raises(ToolError) as exc_info:
                await mcp_client.call_tool("boom_tool", {})
            return str(exc_info.value)

    import asyncio

    # when
    message = asyncio.run(_calls())
    # then
    assert message.startswith("internal: ")
    assert INTERNAL_FIXED_DETAIL in message
    assert "RuntimeError" not in message


def test_a_leftover_old_allow_list_name_stops_start_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "internal.example")
    # when
    with pytest.raises(ValidationError, match="MCP_ALLOWED_HOSTS") as exc_info:
        _SampleSettings()
    # then
    assert "MCP_ALLOWED_HOSTS" in str(exc_info.value)
    assert "ALLOWED_PRIVATE_HOSTS" in str(exc_info.value)


def test_an_invalid_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
    # when
    with pytest.raises(ValidationError, match="LOG_LEVEL") as exc_info:
        _SampleSettings()
    # then
    assert "LOG_LEVEL" in str(exc_info.value)


def test_a_lower_case_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setenv("LOG_LEVEL", "debug")
    # when
    settings = _SampleSettings()
    # then
    assert settings.LOG_LEVEL == "DEBUG"


def test_ascend_audio_scribe_reads_api_port(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setenv("API_PORT", "7117")
    # when
    settings = _SampleSettings()
    # then
    assert settings.API_PORT == 7117


def test_debug_lines_appear_only_at_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    settings = _SampleSettings()
    from ascend_python_common.log_config import configure_logging

    configure_logging(SERVICE_NAME, settings)
    probe = logging.getLogger("sample-probe-debug")
    # when
    probe.info("hello-info-hidden")
    probe.debug("hello-debug-hidden")
    # then
    assert settings.LOG_LEVEL == "WARNING"
    assert logging.getLogger().level == logging.WARNING


def test_json_lines_name_the_service() -> None:
    # given
    from ascend_python_common.log_config import configure_logging

    configure_logging(SERVICE_NAME, _SampleSettings())
    handler = logging.getLogger().handlers[-1]
    record = logging.LogRecord("t", logging.INFO, "", 0, "hello", (), None)
    # when
    formatted = handler.format(record)
    # then
    assert json.loads(formatted)["service"] == SERVICE_NAME


def test_an_unsafe_request_id(caplog: pytest.LogCaptureFixture) -> None:
    # given
    client = _client(_definition())
    logging.getLogger().addHandler(caplog.handler)
    # when
    with caplog.at_level(logging.INFO):
        response = client.get("/health", headers={"x-request-id": "bad\nid"})
    # then
    assert response.status_code == 200
    echoed = response.headers["x-request-id"]
    assert echoed != "bad\nid"
    assert "\n" not in echoed


def test_a_safe_request_id_is_echoed() -> None:
    # given
    client = _client(_definition())
    # when
    response = client.get("/health", headers={"x-request-id": "e2e-canary-req-0001"})
    # then
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "e2e-canary-req-0001"


def test_an_over_long_request_id() -> None:
    # given
    client = _client(_definition())
    too_long = "a" * 129
    # when
    response = client.get("/health", headers={"x-request-id": too_long})
    # then
    assert response.status_code == 200
    echoed = response.headers["x-request-id"]
    assert echoed != too_long
    assert 1 <= len(echoed) <= 128


def test_the_mcp_transport_logs_a_session_id() -> None:
    # given
    session_id = "a" * 32
    digest = digest_of_mcp_session_id(session_id)
    record = logging.LogRecord(
        "mcp.server.streamable_http", logging.INFO, "", 0, f"session {session_id}", (), None
    )
    from ascend_python_common.request_context import McpSessionIdRedactionFilter

    # when
    McpSessionIdRedactionFilter().filter(record)
    # then
    assert session_id not in record.getMessage()
    assert digest in record.getMessage()


def test_export_follows_an_unset_endpoint() -> None:
    # given
    settings = _SampleSettings()
    client = _client(_definition(settings=settings))
    # when
    response = client.get("/does-not-exist")
    # then
    assert settings.OTEL_EXPORTER_OTLP_ENDPOINT is None
    assert response.status_code == 404
    body = response.json()
    assert TRACE_ID_PATTERN.fullmatch(body["traceId"])


def test_sdk_disabled_leaves_no_span_and_no_trace_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    client = _client(_definition())
    # when
    response = client.get("/does-not-exist")
    # then
    assert response.status_code == 404
    body = response.json()
    assert "traceId" not in body


def test_a_dependency_is_down() -> None:
    # given
    client = _client(_definition(probes={"qdrant": _failing_probe}))
    # when
    ready = client.get("/ready")
    healthy = client.get("/health")
    # then
    assert ready.status_code == 503
    body = ready.json()
    assert body["status"] == "not-ready"
    assert body["checks"]["qdrant"]["status"] == "error"
    assert healthy.status_code == 200


def test_a_healthy_service() -> None:
    # given
    client = _client(_definition(probes={"ok": _ok_probe}))
    # when
    ready = client.get("/ready")
    healthy = client.get("/health")
    # then
    assert ready.status_code == 200
    body = ready.json()
    assert body["status"] == "ready"
    assert body["service"] == SERVICE_NAME
    assert body["version"] == package_version("ascend-python-common")
    assert "checks" in body
    assert healthy.status_code == 200
    assert healthy.json() == {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": package_version("ascend-python-common"),
    }


def test_too_many_submissions() -> None:
    # given
    client = _client(_definition(settings=_TightSettings()))
    # when
    first = client.get("/limited")
    second = client.get("/limited")
    refused = client.get("/limited")
    # then
    assert first.status_code == 200
    assert second.status_code == 200
    assert refused.status_code == 429
    assert refused.json()["code"] == "rate_limited"
    assert "Retry-After" in refused.headers


def test_too_many_tool_calls() -> None:
    # given
    definition = _definition(settings=_TightSettings())
    create_service_app(definition)

    async def _calls() -> str:
        # when
        async with Client(definition.mcp) as mcp_client:
            await mcp_client.call_tool("ocr_submit", {})
            await mcp_client.call_tool("ocr_submit", {})
            with pytest.raises(ToolError) as exc_info:
                await mcp_client.call_tool("ocr_submit", {})
            return str(exc_info.value)

    import asyncio

    # when
    message = asyncio.run(_calls())
    # then
    assert message.startswith("rate_limited: ")


def test_health_is_never_limited() -> None:
    # given
    client = _client(_definition(settings=_TightSettings()))
    client.get("/limited")
    client.get("/limited")
    client.get("/limited")
    # when
    answers = [client.get("/health").status_code for _ in range(10)]
    # then
    assert all(status == 200 for status in answers)


def test_ascend_memory_names_itself() -> None:
    # given
    app = create_service_app(_definition())
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "probe", "version": "0.0.1"},
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    # when
    with TestClient(app) as live_client:
        response = live_client.post("/mcp", json=payload, headers=headers)
    # then
    assert response.status_code == 200
    assert MCP_SERVER_NAME in response.text


def test_a_tool_call_reaches_a_container_that_did_not_answer_the_handshake() -> None:
    # given
    first_app = create_service_app(_definition())
    second_app = create_service_app(_definition())
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    initialize_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "probe", "version": "0.0.1"},
        },
    }
    list_payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    call_payload = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "ocr_job_status", "arguments": {}},
    }
    # when
    with TestClient(first_app) as first_client:
        initialize_response = first_client.post("/mcp", json=initialize_payload, headers=headers)
    with TestClient(second_app) as second_client:
        list_response = second_client.post("/mcp", json=list_payload, headers=headers)
        call_response = second_client.post("/mcp", json=call_payload, headers=headers)
    # then
    assert initialize_response.status_code == 200
    assert "mcp-session-id" not in initialize_response.headers
    assert list_response.status_code == 200
    assert "ocr_job_status" in list_response.text
    assert call_response.status_code == 200
    assert "status-ok" in call_response.text


class _FetchSampleSettings(ServiceSettings, McpFetchSettings):
    API_PORT: int = Field(default=7022, ge=1, le=65535)
    RATE_LIMIT_DEFAULT: RateLimit = Field(default="600/minute")
    MCP_DOWNLOAD_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)
    FETCH_MAX_REDIRECT_HOPS: int = Field(default=10, ge=0)


def test_a_service_builds_against_the_pinned_library_version() -> None:
    # given
    raw = Path("pyproject.toml").read_bytes()
    data: dict[str, Any] = tomllib.loads(raw.decode("utf-8"))
    project = data.get("project")
    assert isinstance(project, dict)
    pinned = project.get("version")
    assert isinstance(pinned, str)
    client = _client(_definition())
    # when
    response = client.get("/health")
    # then
    assert package_version("ascend-python-common") == pinned
    assert __version__ == pinned
    assert response.json()["version"] == pinned


def test_no_service_keeps_a_copy_of_shared_code() -> None:
    # given
    shared = [
        "ascend_python_common.log_config",
        "ascend_python_common.request_context",
        "ascend_python_common.tracing",
        "ascend_python_common.errors.problem",
        "ascend_python_common.rate_limit",
        "ascend_python_common.startup_banner",
        "ascend_python_common.uri_guard",
    ]
    # when
    modules = [importlib.import_module(name) for name in shared]
    app = create_service_app(_definition())
    # then
    assert len(modules) == len(shared)
    assert app.title == SERVICE_NAME


async def test_a_host_that_resolves_to_a_private_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    loop = asyncio.get_running_loop()

    async def _fake(
        host: str, port: int, *args: object, **kwargs: object
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]

    monkeypatch.setattr(loop, "getaddrinfo", _fake)
    registry = ErrorRegistry()
    registry.register(UnsafeUriError, ProblemCode("UNSAFE_URI", 400), "unsafe uri", expected=True)
    server = FastMCP("guard-private-probe")

    @server.tool
    async def read_pdf() -> str:
        target = await check_fetch_uri("http://internal.example/file.pdf", FetchPolicy())
        return target.url

    definition = ServiceDefinition(
        name=SERVICE_NAME,
        distribution="ascend-python-common",
        settings=_SampleSettings(),
        mcp=server,
        error_registry=registry,
        probes={"ok": _ok_probe},
    )
    create_service_app(definition)
    # when
    async with Client(definition.mcp) as mcp_client:
        with pytest.raises(ToolError) as exc_info:
            await mcp_client.call_tool("read_pdf", {})
        message = str(exc_info.value)
    # then
    assert message.startswith("UNSAFE_URI: ")
    assert "10.0.0.5" not in message


async def test_a_link_that_leaves_the_file_root(tmp_path: Path) -> None:
    # given
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret-outside", encoding="utf-8")
    (root / "link.txt").symlink_to(outside)
    policy = FetchPolicy(file_root=root)
    uri = root.as_uri() + "/link.txt"
    registry = ErrorRegistry()
    registry.register(UnsafeUriError, VALIDATION, str, expected=True)
    server = FastMCP("guard-file-probe")

    @server.tool
    async def read_file() -> str:
        target = await check_fetch_uri(uri, policy)
        assert target.file_path is not None
        return target.file_path.read_text(encoding="utf-8")

    definition = ServiceDefinition(
        name=SERVICE_NAME,
        distribution="ascend-python-common",
        settings=_SampleSettings(),
        mcp=server,
        error_registry=registry,
        probes={"ok": _ok_probe},
    )
    create_service_app(definition)
    # when
    async with Client(definition.mcp) as mcp_client:
        with pytest.raises(ToolError) as exc_info:
            await mcp_client.call_tool("read_file", {})
        message = str(exc_info.value)
    # then
    assert message.startswith("validation: ")
    assert "secret-outside" not in message


async def test_user_info_in_an_http_uri(caplog: pytest.LogCaptureFixture) -> None:
    # given
    registry = ErrorRegistry()
    registry.register(UnsafeUriError, VALIDATION, str, expected=True)
    server = FastMCP("guard-userinfo-probe")

    @server.tool
    async def fetch_song() -> str:
        target = await check_fetch_uri("https://user:secret@files.example/a.mp3", FetchPolicy())
        return target.url

    definition = ServiceDefinition(
        name=SERVICE_NAME,
        distribution="ascend-python-common",
        settings=_SampleSettings(),
        mcp=server,
        error_registry=registry,
        probes={"ok": _ok_probe},
    )
    create_service_app(definition)
    logging.getLogger().addHandler(caplog.handler)
    # when
    with caplog.at_level(logging.WARNING):
        async with Client(definition.mcp) as mcp_client:
            with pytest.raises(ToolError) as exc_info:
                await mcp_client.call_tool("fetch_song", {})
            message = str(exc_info.value)
    # then
    assert message.startswith("validation: ")
    assert "secret" not in message
    assert all("secret" not in record.getMessage() for record in caplog.records)


async def test_a_public_url_that_redirects_to_a_private_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    loop = asyncio.get_running_loop()

    async def _fake(
        host: str, port: int, *args: object, **kwargs: object
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(loop, "getaddrinfo", _fake)
    registry = ErrorRegistry()
    registry.register(UnsafeUriError, VALIDATION, str, expected=True)
    calls: list[str] = []

    async def _send(target: FetchTarget) -> HopAnswer[str]:
        calls.append(target.url)
        if target.url == "https://files.example/a.mp3":
            return HopAnswer(status=302, location="http://10.0.0.5/a.mp3", answer="")
        raise AssertionError("private hop must never be sent")

    server = FastMCP("guard-redirect-probe")

    @server.tool
    async def transcribe() -> str:
        first = await check_fetch_uri("https://files.example/a.mp3", FetchPolicy())
        final = await follow_guarded_redirects(first, FetchPolicy(), _send)
        return final.answer

    definition = ServiceDefinition(
        name=SERVICE_NAME,
        distribution="ascend-python-common",
        settings=_SampleSettings(),
        mcp=server,
        error_registry=registry,
        probes={"ok": _ok_probe},
    )
    create_service_app(definition)
    # when
    async with Client(definition.mcp) as mcp_client:
        with pytest.raises(ToolError) as exc_info:
            await mcp_client.call_tool("transcribe", {})
        message = str(exc_info.value)
    # then
    assert message.startswith("validation: ")
    assert calls == ["https://files.example/a.mp3"]


async def test_a_name_that_answers_a_private_address_to_a_second_lookup() -> None:
    # given
    from aiohttp.abc import AbstractResolver, ResolveResult

    class _Inner(AbstractResolver):
        async def resolve(
            self,
            host: str,
            port: int = 0,
            family: socket.AddressFamily = socket.AF_INET,
        ) -> list[ResolveResult]:
            return [
                {
                    "hostname": host,
                    "host": "127.0.0.1",
                    "port": port,
                    "family": int(socket.AF_INET),
                    "proto": 0,
                    "flags": 0,
                }
            ]

        async def close(self) -> None:
            return None

    inner = _Inner()
    resolver = PinnedResolver(inner)
    target = FetchTarget(
        url="https://files.example/a.pdf",
        host="files.example",
        port=443,
        addresses=("93.184.216.34",),
    )
    # when
    with pinned_scope(target):
        found = await resolver.resolve("files.example", 443)
    # then
    assert [entry["host"] for entry in found] == ["93.184.216.34"]
    assert "127.0.0.1" not in [entry["host"] for entry in found]


async def test_ascend_web_hunter_allows_only_the_hosts_its_setting_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    loop = asyncio.get_running_loop()
    seen: list[tuple[str, int]] = []

    async def _fake(
        host: str, port: int, *args: object, **kwargs: object
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        seen.append((host, port))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]

    monkeypatch.setattr(loop, "getaddrinfo", _fake)
    policy = FetchPolicy(allowed_hosts=("e2e-fake-site",))
    # when
    allowed = await check_fetch_uri("http://e2e-fake-site/page", policy)
    with pytest.raises(UnsafeUriError):
        await check_fetch_uri("http://e2e-fake-site-blocked/page", policy)
    shipped = _FetchSampleSettings()
    # then
    assert allowed.host == "e2e-fake-site"
    assert allowed.addresses == ()
    assert seen == [("e2e-fake-site-blocked", 80)]
    assert shipped.ALLOWED_PRIVATE_HOSTS == ()
    assert policy.allowed_hosts == ("e2e-fake-site",)


async def test_ascend_web_hunter_refuses_a_private_url_with_the_same_guard() -> None:
    # given
    registry = ErrorRegistry()
    registry.register(UnsafeUriError, ProblemCode("unsafe_uri", 400), "unsafe uri", expected=True)
    router = APIRouter()

    @router.get("/read")
    async def read() -> dict[str, str]:
        await check_fetch_uri("http://169.254.169.254/latest/meta-data", FetchPolicy())
        return {"status": "ok"}

    definition = ServiceDefinition(
        name=SERVICE_NAME,
        distribution="ascend-python-common",
        settings=_SampleSettings(),
        mcp=_mcp_server(),
        routers=(router,),
        error_registry=registry,
        probes={"ok": _ok_probe},
    )
    client = _client(definition)
    # when
    response = client.get("/read")
    # then
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "unsafe_uri"
    assert "169.254.169.254" not in response.text


def test_a_connection_string_with_a_password() -> None:
    # given
    raw = "redis://user:secret@redis:6379/0"
    section = BannerSection("External services", (BannerCheck("Redis", raw, CONNECTED),))
    # when
    lines = render_section(section)
    checked = format_check(raw, CONNECTED)
    full = build_banner(
        service_name="ascend-web-hunter",
        api_port=7021,
        log_level="INFO",
        art="ART",
        sections=(section,),
        host="myhost",
    )
    text = "\n".join(lines + full)
    # then
    assert checked == "redis://redis:6379/0 [Connected]"
    assert "redis://redis:6379/0 [Connected]" in "\n".join(lines)
    assert strip_user_info(raw) == "redis://redis:6379/0"
    assert "secret" not in text


def test_a_key_that_is_set() -> None:
    # given
    section = BannerSection(
        "Keys",
        (
            BannerCheck("API key", "environment", CONFIGURED),
            BannerLine("Token", "s3cret-value", secret=True),
        ),
    )
    # when
    lines = render_section(section)
    rendered = render_value("s3cret-value", secret=True)
    # then
    assert "environment [Configured]" in "\n".join(lines)
    assert rendered == "****"
    assert "s3cret-value" not in "\n".join(lines)


def test_a_service_drops_the_coverage_gate(tmp_path: Path) -> None:
    # given
    base = (
        '[tool.mypy]\npython_version = "3.11"\nstrict = true\nwarn_unused_ignores = true\n'
        "warn_return_any = true\nwarn_unreachable = true\n\n"
        '[tool.pytest.ini_options]\nasyncio_mode = "auto"\nxfail_strict = true\n'
        'filterwarnings = ["error"]\naddopts = [\n    "--strict-markers",\n'
        '    "--strict-config",\n    "--cov-branch",\n    "--cov-fail-under=100",\n]\n\n'
        '[tool.ruff]\nextend = "tooling/ruff.toml"\n'
    )
    low = tmp_path / "low.toml"
    low.write_text(base.replace("--cov-fail-under=100", "--cov-fail-under=99"), encoding="utf-8")
    no_markers = tmp_path / "no-markers.toml"
    no_markers.write_text(base.replace('    "--strict-markers",\n', ""), encoding="utf-8")
    # when
    with pytest.raises(AssertionError, match="cov-fail-under"):
        assert_pyproject_conforms(low)
    with pytest.raises(AssertionError, match="strict-markers"):
        assert_pyproject_conforms(no_markers)
    # then
    assert "--cov-fail-under=99" in low.read_text(encoding="utf-8")
    assert "--strict-markers" not in no_markers.read_text(encoding="utf-8")
