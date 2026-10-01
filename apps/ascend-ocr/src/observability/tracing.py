from collections.abc import Sequence
from typing import Final

from fastapi import FastAPI
from opentelemetry import propagate, trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.util.types import AttributeValue

from src.api.middleware.correlation_id import digest_of_mcp_session_id
from src.config.config import settings

_SERVICE_NAME: str = "ascend-ocr"
MCP_SESSION_ID_SPAN_ATTRIBUTE: Final[str] = "mcp.session.id"
MCP_SESSION_ID_REQUEST_HEADER_ATTRIBUTE: Final[str] = "http.request.header.mcp_session_id"
MCP_SESSION_ID_RESPONSE_HEADER_ATTRIBUTE: Final[str] = "http.response.header.mcp_session_id"
MCP_SESSION_ID_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {MCP_SESSION_ID_SPAN_ATTRIBUTE, MCP_SESSION_ID_REQUEST_HEADER_ATTRIBUTE, MCP_SESSION_ID_RESPONSE_HEADER_ATTRIBUTE}
)


class McpSessionDigestSpanExporter(SpanExporter):
    def __init__(self, delegate: SpanExporter) -> None:
        self._delegate = delegate

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self._delegate.export([_with_session_digest(span) for span in spans])

    def shutdown(self) -> None:
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._delegate.force_flush(timeout_millis)


class _SessionDigestSpan(ReadableSpan):
    def __init__(self, original: ReadableSpan, attributes: dict[str, AttributeValue]) -> None:
        super().__init__(
            name=original.name,
            context=original.context,
            parent=original.parent,
            resource=original.resource,
            attributes=attributes,
            events=original.events,
            links=original.links,
            kind=original.kind,
            status=original.status,
            start_time=original.start_time,
            end_time=original.end_time,
            instrumentation_scope=original.instrumentation_scope,
        )
        self._original = original

    @property
    def dropped_attributes(self) -> int:
        return self._original.dropped_attributes

    @property
    def dropped_events(self) -> int:
        return self._original.dropped_events

    @property
    def dropped_links(self) -> int:
        return self._original.dropped_links


def _with_session_digest(span: ReadableSpan) -> ReadableSpan:
    original_attributes = span.attributes or {}
    if MCP_SESSION_ID_ATTRIBUTES.isdisjoint(original_attributes):
        return span

    attributes = {
        key: _digest_of_attribute_value(value) if key in MCP_SESSION_ID_ATTRIBUTES else value
        for key, value in original_attributes.items()
    }

    return _SessionDigestSpan(span, attributes)


def _digest_of_attribute_value(value: AttributeValue) -> AttributeValue:
    if isinstance(value, Sequence) and not isinstance(value, str):
        return tuple(digest_of_mcp_session_id(str(item)) for item in value)

    return digest_of_mcp_session_id(str(value))


def _configure_provider() -> None:
    """Build the TracerProvider and OTLP exporter shared by the main process and each OCR worker."""
    resource = Resource.create({"service.name": _SERVICE_NAME})
    provider = TracerProvider(resource=resource)

    exporter = McpSessionDigestSpanExporter(OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT))
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)


def configure_tracing(app: FastAPI) -> None:
    if not settings.OTEL_ENABLED:
        return

    _configure_provider()

    FastAPIInstrumentor.instrument_app(app)
    AioHttpClientInstrumentor().instrument()


def configure_worker_tracing() -> None:
    """Wire up the OTLP exporter inside an OCR worker process.

    OCR inference runs in a ProcessPoolExecutor worker (spawn context) so that it cannot
    starve this process's event loop. Each worker starts from a fresh interpreter, so
    configure_tracing's setup in the main process never reaches it and spans created
    during process_file would otherwise be silent no-ops. Call this once, from the pool
    initializer, before the worker accepts its first task.
    """
    if not settings.OTEL_ENABLED:
        return

    _configure_provider()


def get_tracer() -> trace.Tracer:
    return trace.get_tracer(_SERVICE_NAME)


def inject_trace_context() -> dict[str, str]:
    """Serialise the current span context into a carrier that survives a process boundary."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)

    return carrier


def extract_trace_context(carrier: dict[str, str]) -> Context:
    """Rebuild the span context captured by inject_trace_context in another process."""
    return propagate.extract(carrier)
