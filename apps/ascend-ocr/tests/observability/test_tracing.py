import hashlib
import uuid
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Link, SpanContext, Status, StatusCode
from opentelemetry.util.types import AttributeValue

from src.config.config import settings
from src.observability.tracing import (
    MCP_SESSION_ID_REQUEST_HEADER_ATTRIBUTE,
    MCP_SESSION_ID_RESPONSE_HEADER_ATTRIBUTE,
    MCP_SESSION_ID_SPAN_ATTRIBUTE,
    McpSessionDigestSpanExporter,
    configure_tracing,
    configure_worker_tracing,
    extract_trace_context,
    get_tracer,
    inject_trace_context,
)

SESSION_DIGEST_LENGTH = 16
FLUSH_TIMEOUT_MILLIS = 1234
SPAN_NAME = "tools/call ocr_job_status"
SCOPE_NAME = "probe-scope"
SCOPE_VERSION = "1.2.3"
KEPT_EVENT_NAME = "second event"
STATUS_DESCRIPTION = "tool failed"
LINKED_TRACE_ID = 0x0123456789ABCDEF0123456789ABCDEF
LINKED_SPAN_IDS = (0x1111111111111111, 0x2222222222222222)


def _digest_of(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()[:SESSION_DIGEST_LENGTH]


def _exported_through_the_digest_exporter(attributes: dict[str, AttributeValue]) -> InMemorySpanExporter:
    exported = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(McpSessionDigestSpanExporter(exported)))
    with provider.get_tracer("test").start_as_current_span("tools/call ocr_job_status", attributes=attributes):
        pass

    return exported


class TestConfigureTracing:
    def test_disabled_when_otel_off(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OTEL_ENABLED", False)
        app = MagicMock()

        # When
        configure_tracing(app)

        # Then - no FastAPI instrumentation calls
        app.add_middleware.assert_not_called()

    @patch("src.observability.tracing.AioHttpClientInstrumentor")
    @patch("src.observability.tracing.FastAPIInstrumentor")
    @patch("src.observability.tracing.BatchSpanProcessor")
    @patch("src.observability.tracing.OTLPSpanExporter")
    @patch("src.observability.tracing.TracerProvider")
    def test_enabled_wires_otel_stack(
        self,
        mock_provider,
        mock_exporter,
        mock_processor,
        mock_fastapi_inst,
        mock_aiohttp_inst,
        monkeypatch,
    ):
        # Given
        monkeypatch.setattr(settings, "OTEL_ENABLED", True)
        app = MagicMock()

        # When
        configure_tracing(app)

        # Then
        mock_provider.assert_called_once()
        mock_exporter.assert_called_once()
        mock_fastapi_inst.instrument_app.assert_called_once_with(app)
        mock_aiohttp_inst.return_value.instrument.assert_called_once()
        [wrapped_exporter] = mock_processor.call_args.args
        assert isinstance(wrapped_exporter, McpSessionDigestSpanExporter)


class TestConfigureWorkerTracing:
    def test_disabled_when_otel_off(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OTEL_ENABLED", False)

        # When
        with patch("src.observability.tracing.TracerProvider") as mock_provider:
            configure_worker_tracing()

        # Then - no provider is built when tracing is off
        mock_provider.assert_not_called()

    @patch("src.observability.tracing.AioHttpClientInstrumentor")
    @patch("src.observability.tracing.FastAPIInstrumentor")
    @patch("src.observability.tracing.BatchSpanProcessor")
    @patch("src.observability.tracing.OTLPSpanExporter")
    @patch("src.observability.tracing.TracerProvider")
    def test_enabled_configures_provider_without_app_instrumentation(
        self,
        mock_provider,
        mock_exporter,
        mock_processor,
        mock_fastapi_inst,
        mock_aiohttp_inst,
        monkeypatch,
    ):
        # Given - a worker process has no FastAPI app and no aiohttp client of its own
        monkeypatch.setattr(settings, "OTEL_ENABLED", True)

        # When
        configure_worker_tracing()

        # Then
        mock_provider.assert_called_once()
        mock_exporter.assert_called_once()
        mock_fastapi_inst.instrument_app.assert_not_called()
        mock_aiohttp_inst.return_value.instrument.assert_not_called()


class TestMcpSessionDigestSpanExporter:
    def test_a_span_leaves_with_the_session_digest_in_place_of_the_session_id(self):
        # Given
        session_id = uuid.uuid4().hex

        # When
        exported = _exported_through_the_digest_exporter({MCP_SESSION_ID_SPAN_ATTRIBUTE: session_id, "other": "kept"})

        # Then
        [span] = exported.get_finished_spans()
        assert span.attributes is not None
        expected_digest = hashlib.sha256(session_id.encode()).hexdigest()[:SESSION_DIGEST_LENGTH]
        assert span.attributes[MCP_SESSION_ID_SPAN_ATTRIBUTE] == expected_digest
        assert session_id not in span.attributes.values()
        assert span.attributes["other"] == "kept"
        assert span.name == "tools/call ocr_job_status"

    def test_a_rewritten_span_keeps_everything_but_the_session_id(self):
        # Given
        session_id = uuid.uuid4().hex
        exported = InMemorySpanExporter()
        provider = TracerProvider(
            resource=Resource.create({"service.name": "probe-service"}),
            span_limits=SpanLimits(max_attributes=2, max_events=1, max_links=1),
        )
        provider.add_span_processor(SimpleSpanProcessor(McpSessionDigestSpanExporter(exported)))
        tracer = provider.get_tracer(SCOPE_NAME, SCOPE_VERSION)
        linked = [Link(SpanContext(LINKED_TRACE_ID, span_id, is_remote=True)) for span_id in LINKED_SPAN_IDS]
        attributes = {"evicted": "first", "kept": "second", MCP_SESSION_ID_SPAN_ATTRIBUTE: session_id}

        # When
        with tracer.start_as_current_span(SPAN_NAME, attributes=attributes, links=linked) as span:
            span.add_event("first event")
            span.add_event(KEPT_EVENT_NAME)
            span.set_status(Status(StatusCode.ERROR, STATUS_DESCRIPTION))

        # Then
        [exported_span] = exported.get_finished_spans()
        assert (exported_span.dropped_attributes, exported_span.dropped_events, exported_span.dropped_links) == (
            1,
            1,
            1,
        )
        assert [event.name for event in exported_span.events] == [KEPT_EVENT_NAME]
        assert [link.context.span_id for link in exported_span.links] == [LINKED_SPAN_IDS[-1]]
        assert (exported_span.status.status_code, exported_span.status.description) == (
            StatusCode.ERROR,
            STATUS_DESCRIPTION,
        )
        assert exported_span.resource.attributes["service.name"] == "probe-service"
        assert exported_span.instrumentation_scope is not None
        assert (exported_span.instrumentation_scope.name, exported_span.instrumentation_scope.version) == (
            SCOPE_NAME,
            SCOPE_VERSION,
        )
        assert dict(exported_span.attributes or {}) == {
            "kept": "second",
            MCP_SESSION_ID_SPAN_ATTRIBUTE: _digest_of(session_id),
        }

    @pytest.mark.parametrize(
        "header_attribute", [MCP_SESSION_ID_REQUEST_HEADER_ATTRIBUTE, MCP_SESSION_ID_RESPONSE_HEADER_ATTRIBUTE]
    )
    def test_a_captured_session_header_leaves_as_the_digest(self, header_attribute):
        # Given
        session_id = uuid.uuid4().hex

        # When
        exported = _exported_through_the_digest_exporter({header_attribute: [session_id]})

        # Then
        [span] = exported.get_finished_spans()
        assert dict(span.attributes or {}) == {header_attribute: (_digest_of(session_id),)}

    def test_a_span_without_a_session_id_leaves_unchanged(self):
        # When
        exported = _exported_through_the_digest_exporter({"other": "kept"})

        # Then
        [span] = exported.get_finished_spans()
        assert dict(span.attributes or {}) == {"other": "kept"}

    def test_shutdown_and_flush_reach_the_wrapped_exporter(self):
        # Given
        delegate = MagicMock()
        exporter = McpSessionDigestSpanExporter(delegate)

        # When
        flushed = exporter.force_flush(FLUSH_TIMEOUT_MILLIS)
        exporter.shutdown()

        # Then
        assert flushed is delegate.force_flush.return_value
        delegate.force_flush.assert_called_once_with(FLUSH_TIMEOUT_MILLIS)
        delegate.shutdown.assert_called_once_with()


class TestGetTracer:
    def test_returns_tracer_instance(self):
        # When
        tracer = get_tracer()

        # Then
        assert tracer is not None
        with tracer.start_as_current_span("test") as span:
            assert span is not None


class TestTraceContextPropagation:
    def test_inject_returns_empty_carrier_without_active_span(self):
        # When - no span is current at module scope, so nothing is injected
        carrier = inject_trace_context()

        # Then
        assert carrier == {}

    def test_inject_delegates_to_propagator(self):
        # Given
        def fake_inject(carrier: dict[str, str]) -> None:
            carrier["traceparent"] = "00-fake-01"

        # When
        with patch("src.observability.tracing.propagate") as mock_propagate:
            mock_propagate.inject.side_effect = fake_inject
            carrier = inject_trace_context()

        # Then
        assert carrier == {"traceparent": "00-fake-01"}

    def test_extract_delegates_to_propagator(self):
        # Given
        sentinel_context = object()
        carrier = {"traceparent": "00-fake-01"}

        # When
        with patch("src.observability.tracing.propagate") as mock_propagate:
            mock_propagate.extract.return_value = sentinel_context
            result = extract_trace_context(carrier)

        # Then
        assert result is sentinel_context
        mock_propagate.extract.assert_called_once_with(carrier)
