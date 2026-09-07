from fastapi import FastAPI
from opentelemetry import propagate, trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from src.config.config import settings

_SERVICE_NAME: str = "ascend-ocr"


def _configure_provider() -> None:
    """Build the TracerProvider and OTLP exporter shared by the main process and each OCR worker."""
    resource = Resource.create({"service.name": _SERVICE_NAME})
    provider = TracerProvider(resource=resource)

    exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
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
