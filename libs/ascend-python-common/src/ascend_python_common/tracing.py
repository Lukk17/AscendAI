from collections.abc import MutableMapping, Sequence
from typing import Final

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON, ParentBased
from starlette.types import ASGIApp

SERVICE_NAME_RESOURCE_KEY: Final[str] = "service.name"
SERVICE_VERSION_RESOURCE_KEY: Final[str] = "service.version"
MCP_SESSION_ID_SPAN_ATTRIBUTE: Final[str] = "mcp.session.id"


class DropMcpSessionIdSpanProcessor(SpanProcessor):
    def on_start(
        self,
        span: Span,
        parent_context: Context | None = None,  # noqa: ARG002
    ) -> None:
        attributes = span._attributes  # noqa: SLF001
        if isinstance(attributes, MutableMapping) and MCP_SESSION_ID_SPAN_ATTRIBUTE in attributes:
            del attributes[MCP_SESSION_ID_SPAN_ATTRIBUTE]


def build_tracer_provider(
    service_name: str,
    *,
    otel_endpoint: str | None,
    service_version: str | None = None,
    exporter: SpanExporter | None = None,
) -> TracerProvider:
    endpoint = otel_endpoint or None
    resource_attributes = {SERVICE_NAME_RESOURCE_KEY: service_name}
    if service_version is not None:
        resource_attributes[SERVICE_VERSION_RESOURCE_KEY] = service_version
    provider = TracerProvider(
        resource=Resource.create(resource_attributes),
        sampler=ParentBased(ALWAYS_ON) if endpoint is not None else ParentBased(ALWAYS_OFF),
    )
    provider.add_span_processor(DropMcpSessionIdSpanProcessor())
    if endpoint is not None:
        delegate = exporter if exporter is not None else OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(_SessionIdScrubbingExporter(delegate)))

    return provider


class _SessionIdScrubbingExporter(SpanExporter):
    """Forwards exported spans after dropping the MCP session id attribute.

    FastMCP enriches its server spans after span start, so the span processor
    above cannot remove the attribute it adds later. The exporter is the last
    point where the attribute can still be removed before it reaches Tempo.
    """

    def __init__(self, delegate: SpanExporter) -> None:
        self._delegate = delegate

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self._delegate.export([_without_session_id(span) for span in spans])

    def shutdown(self) -> None:
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._delegate.force_flush(timeout_millis)


def _without_session_id(span: ReadableSpan) -> ReadableSpan:
    attributes = span.attributes
    if attributes is None or MCP_SESSION_ID_SPAN_ATTRIBUTE not in attributes:
        return span
    pruned = {key: value for key, value in attributes.items() if key != MCP_SESSION_ID_SPAN_ATTRIBUTE}
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=pruned,
        events=span.events,
        links=span.links,
        kind=span.kind,
        status=span.status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


def configure_tracing(
    service_name: str,
    *,
    otel_endpoint: str | None,
    service_version: str | None = None,
    exporter: SpanExporter | None = None,
) -> TracerProvider:
    provider = build_tracer_provider(
        service_name,
        otel_endpoint=otel_endpoint,
        service_version=service_version,
        exporter=exporter,
    )
    trace.set_tracer_provider(provider)

    return provider


def wrap_with_tracing(app: ASGIApp, tracer_provider: TracerProvider | None = None) -> ASGIApp:
    """Start the server span just inside the correlation id middleware, around the whole stack."""
    return OpenTelemetryMiddleware(app, tracer_provider=tracer_provider)


def get_tracer(service_name: str) -> trace.Tracer:
    return trace.get_tracer(service_name)


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None

    return format(context.trace_id, "032x")
