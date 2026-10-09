from collections.abc import MutableMapping
from typing import Final

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON, ParentBased
from starlette.types import ASGIApp

SERVICE_NAME_RESOURCE_KEY: Final[str] = "service.name"
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
    exporter: SpanExporter | None = None,
) -> TracerProvider:
    endpoint = otel_endpoint or None
    provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME_RESOURCE_KEY: service_name}),
        sampler=ParentBased(ALWAYS_ON) if endpoint is not None else ParentBased(ALWAYS_OFF),
    )
    provider.add_span_processor(DropMcpSessionIdSpanProcessor())
    if endpoint is not None:
        delegate = exporter if exporter is not None else OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(delegate))

    return provider


def configure_tracing(
    service_name: str,
    *,
    otel_endpoint: str | None,
    exporter: SpanExporter | None = None,
) -> TracerProvider:
    provider = build_tracer_provider(service_name, otel_endpoint=otel_endpoint, exporter=exporter)
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
