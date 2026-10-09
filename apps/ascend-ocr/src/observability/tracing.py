from ascend_python_common.tracing import build_tracer_provider
from ascend_python_common.tracing import get_tracer as _library_get_tracer
from opentelemetry import propagate, trace
from opentelemetry.context import Context

from src.config.config import settings

_SERVICE_NAME: str = "ascend-ocr"


def configure_worker_tracing() -> None:
    """Wire up the exporter inside an OCR worker process.

    OCR inference runs in a ProcessPoolExecutor worker (spawn context) so that it cannot
    starve this process's event loop. Each worker starts from a fresh interpreter, so
    the main process setup never reaches it and spans created during process_file would
    otherwise be silent no-ops. Call this once, from the pool initializer, before the
    worker accepts its first task. The provider comes from the library's public builder,
    so the export rule exists once.
    """
    provider = build_tracer_provider(
        _SERVICE_NAME,
        otel_endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
    )
    trace.set_tracer_provider(provider)


def get_tracer() -> trace.Tracer:
    return _library_get_tracer(_SERVICE_NAME)


def inject_trace_context() -> dict[str, str]:
    """Serialise the current span context into a carrier that survives a process boundary."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)

    return carrier


def extract_trace_context(carrier: dict[str, str]) -> Context:
    """Rebuild the span context captured by inject_trace_context in another process."""
    return propagate.extract(carrier)
