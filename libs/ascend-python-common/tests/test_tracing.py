import hashlib
import re
import time
import uuid
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from starlette.types import ASGIApp

from ascend_python_common.request_context import CorrelationIdMiddleware
from ascend_python_common.tracing import (
    MCP_SESSION_ID_SPAN_ATTRIBUTE,
    build_tracer_provider,
    configure_tracing,
    current_trace_id,
    get_tracer,
    wrap_with_tracing,
)

SERVICE_NAME = "probe-service"
TRACE_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
SESSION_DIGEST_LENGTH = 16
SAMPLE_PATH = "/sample"
MCP_ENDPOINT = "/mcp"
REQUEST_COUNT = 1000
KNOWN_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
KNOWN_PARENT_SPAN_ID = "00f067aa0ba902b7"
OTEL_ENDPOINT = "http://otel-collector:4317"


def _digest_of(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()[:SESSION_DIGEST_LENGTH]


@pytest.fixture
def shutdown_providers() -> Iterator[list[TracerProvider]]:
    created: list[TracerProvider] = []
    yield created
    for provider in created:
        provider.shutdown()


@pytest.fixture(autouse=True)
def _isolated_global_provider(shutdown_providers: list[TracerProvider]) -> Iterator[None]:
    from opentelemetry.util._once import Once

    saved_provider = trace._TRACER_PROVIDER
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE = Once()
    yield
    trace._TRACER_PROVIDER = saved_provider
    trace._TRACER_PROVIDER_SET_ONCE = Once()


def _build(
    created: list[TracerProvider],
    *,
    otel_endpoint: str | None,
    exporter: Any | None = None,
    service_name: str = SERVICE_NAME,
) -> tuple[TracerProvider, InMemorySpanExporter | None]:
    collected = exporter
    provider = build_tracer_provider(
        service_name,
        otel_endpoint=otel_endpoint,
        exporter=collected,
    )
    created.append(provider)
    if isinstance(collected, InMemorySpanExporter):
        return provider, collected
    return provider, None


def _server_spans(spans: Sequence[ReadableSpan]) -> list[ReadableSpan]:
    return [span for span in spans if not span.name.endswith(("http send", "http receive"))]


def _sample_app(provider: TracerProvider | None) -> ASGIApp:
    app = FastAPI()

    @app.get(SAMPLE_PATH)
    def sample() -> dict[str, object]:
        span = trace.get_current_span()
        context = span.get_span_context()
        sampled = bool(context.trace_flags.sampled) if context.is_valid else False
        return {"trace_id": current_trace_id(), "sampled": sampled}

    if provider is None:
        return app
    return wrap_with_tracing(app, tracer_provider=provider)


def test_trace_id_exists_with_export_off_and_nothing_is_exported(
    shutdown_providers: list[TracerProvider],
) -> None:
    # given
    exported = InMemorySpanExporter()
    provider, _ = _build(shutdown_providers, otel_endpoint=None, exporter=exported)
    client = TestClient(_sample_app(provider))
    # when
    response = client.get(SAMPLE_PATH)
    provider.force_flush()
    # then
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["trace_id"], str)
    assert TRACE_ID_PATTERN.fullmatch(body["trace_id"])
    assert body["sampled"] is False
    assert list(exported.get_finished_spans()) == []


def test_incoming_traceparent_is_continued_with_export_off(
    shutdown_providers: list[TracerProvider],
) -> None:
    # given
    provider, _ = _build(shutdown_providers, otel_endpoint=None)
    client = TestClient(_sample_app(provider))
    traceparent = f"00-{KNOWN_TRACE_ID}-{KNOWN_PARENT_SPAN_ID}-01"
    # when
    response = client.get(SAMPLE_PATH, headers={"traceparent": traceparent})
    # then
    assert response.status_code == 200
    assert response.json()["trace_id"] == KNOWN_TRACE_ID


def test_endpoint_set_exports_sampled_spans_for_the_service(
    shutdown_providers: list[TracerProvider],
) -> None:
    # given
    exported = InMemorySpanExporter()
    provider, _ = _build(shutdown_providers, otel_endpoint=OTEL_ENDPOINT, exporter=exported)
    client = TestClient(_sample_app(provider))
    # when
    response = client.get(SAMPLE_PATH)
    provider.force_flush()
    # then
    assert response.status_code == 200
    [span] = _server_spans(exported.get_finished_spans())
    assert response.json()["trace_id"] == format(span.context.trace_id, "032x")
    assert span.resource.attributes["service.name"] == SERVICE_NAME


def test_endpoint_set_builds_the_otlp_exporter_by_default(
    shutdown_providers: list[TracerProvider], monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    from unittest.mock import MagicMock

    delegate = MagicMock()
    exporter_mock = MagicMock(return_value=delegate)
    monkeypatch.setattr("ascend_python_common.tracing.OTLPSpanExporter", exporter_mock)
    # when
    provider = build_tracer_provider(SERVICE_NAME, otel_endpoint=OTEL_ENDPOINT)
    shutdown_providers.append(provider)
    # then
    assert exporter_mock.call_count == 1
    assert exporter_mock.call_args.kwargs["endpoint"] == OTEL_ENDPOINT


def test_endpoint_unset_builds_no_exporter(
    shutdown_providers: list[TracerProvider], monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    from unittest.mock import MagicMock

    exporter_mock = MagicMock()
    monkeypatch.setattr("ascend_python_common.tracing.OTLPSpanExporter", exporter_mock)
    # when
    provider = build_tracer_provider(SERVICE_NAME, otel_endpoint=None)
    shutdown_providers.append(provider)
    # then
    assert exporter_mock.call_count == 0
    assert provider.resource.attributes["service.name"] == SERVICE_NAME


def test_current_trace_id_is_none_outside_a_span() -> None:
    # given
    no_span_is_current = trace.get_current_span().get_span_context().is_valid is False
    # when
    trace_id = current_trace_id()
    # then
    assert no_span_is_current
    assert trace_id is None


def test_session_id_attribute_is_dropped_at_span_start(
    shutdown_providers: list[TracerProvider],
) -> None:
    # given
    session_id = uuid.uuid4().hex
    exported = InMemorySpanExporter()
    provider, _ = _build(shutdown_providers, otel_endpoint=OTEL_ENDPOINT, exporter=exported)
    # when
    with provider.get_tracer("test").start_as_current_span(
        "tools/call probe", attributes={MCP_SESSION_ID_SPAN_ATTRIBUTE: session_id, "other": "kept"}
    ):
        pass
    provider.force_flush()
    # then
    [span] = exported.get_finished_spans()
    assert span.attributes is not None
    assert MCP_SESSION_ID_SPAN_ATTRIBUTE not in span.attributes
    assert session_id not in span.attributes.values()
    assert _digest_of(session_id) not in span.attributes.values()
    assert span.attributes["other"] == "kept"


def test_span_without_a_session_id_keeps_its_attributes(
    shutdown_providers: list[TracerProvider],
) -> None:
    # given
    exported = InMemorySpanExporter()
    provider, _ = _build(shutdown_providers, otel_endpoint=OTEL_ENDPOINT, exporter=exported)
    # when
    with provider.get_tracer("test").start_as_current_span("GET /sample", attributes={"other": "kept"}):
        pass
    provider.force_flush()
    # then
    [span] = exported.get_finished_spans()
    assert dict(span.attributes or {}) == {"other": "kept"}


def test_sdk_disabled_hands_out_noop_tracers(
    shutdown_providers: list[TracerProvider], monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    provider = build_tracer_provider(SERVICE_NAME, otel_endpoint=OTEL_ENDPOINT)
    shutdown_providers.append(provider)
    # when
    with provider.get_tracer("test").start_as_current_span("probe") as span:
        trace_id = current_trace_id()
        recording = span.is_recording()
    # then
    assert recording is False
    assert trace_id is None


def test_configure_tracing_sets_the_global_provider(
    shutdown_providers: list[TracerProvider],
) -> None:
    # given
    no_exporter: Any | None = None
    # when
    provider = configure_tracing(SERVICE_NAME, otel_endpoint=None, exporter=no_exporter)
    shutdown_providers.append(provider)
    # then
    assert trace.get_tracer_provider() is provider
    assert provider.resource.attributes["service.name"] == SERVICE_NAME


def test_configure_tracing_without_exporter_returns_a_provider(
    shutdown_providers: list[TracerProvider],
) -> None:
    # given
    no_endpoint: str | None = None
    # when
    provider = configure_tracing(SERVICE_NAME, otel_endpoint=no_endpoint)
    shutdown_providers.append(provider)
    # then
    assert isinstance(provider, TracerProvider)


def test_get_tracer_starts_a_span() -> None:
    # given
    tracer = get_tracer(SERVICE_NAME)
    # when
    with tracer.start_as_current_span("probe") as span:
        span_is_recording = span.is_recording()
    # then
    assert span_is_recording or current_trace_id() is None


def test_middleware_sits_inside_the_correlation_middleware(
    shutdown_providers: list[TracerProvider],
) -> None:
    # given
    exported = InMemorySpanExporter()
    provider, _ = _build(shutdown_providers, otel_endpoint=OTEL_ENDPOINT, exporter=exported)
    inner = FastAPI()

    @inner.get(SAMPLE_PATH)
    def sample() -> dict[str, object]:
        return {"trace_id": current_trace_id()}

    traced = wrap_with_tracing(inner, tracer_provider=provider)
    app = CorrelationIdMiddleware(traced, mcp_endpoint_path=MCP_ENDPOINT)
    client = TestClient(app)
    # when
    response = client.get(SAMPLE_PATH, headers={"x-request-id": "caller-chosen-1"})
    provider.force_flush()
    # then
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "caller-chosen-1"
    [span] = _server_spans(exported.get_finished_spans())
    assert response.json()["trace_id"] == format(span.context.trace_id, "032x")


def test_thousand_requests_with_and_without_the_provider() -> None:
    # given
    exported = InMemorySpanExporter()
    provider = build_tracer_provider(SERVICE_NAME, otel_endpoint=None, exporter=exported)
    traced_client = TestClient(_sample_app(provider))
    plain_client = TestClient(_sample_app(None))
    # when
    started_without = time.perf_counter()
    for _ in range(REQUEST_COUNT):
        plain_response = plain_client.get(SAMPLE_PATH)
    without_provider_ms = (time.perf_counter() - started_without) * 1000
    started_with = time.perf_counter()
    for _ in range(REQUEST_COUNT):
        traced_response = traced_client.get(SAMPLE_PATH)
    with_provider_ms = (time.perf_counter() - started_with) * 1000
    provider.shutdown()
    # then
    assert plain_response.status_code == 200
    assert traced_response.status_code == 200
    assert plain_response.json()["trace_id"] is None
    assert TRACE_ID_PATTERN.fullmatch(traced_response.json()["trace_id"])
    assert without_provider_ms > 0
    assert with_provider_ms > 0
