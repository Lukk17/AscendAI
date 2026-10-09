import re
from importlib.metadata import version

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def test_opentelemetry_versions_are_the_library_set() -> None:
    # given
    expected = {
        "opentelemetry-api": "1.45.0",
        "opentelemetry-sdk": "1.45.0",
        "opentelemetry-exporter-otlp": "1.45.0",
        "opentelemetry-instrumentation-fastapi": "0.66b0",
    }
    # when
    installed = {name: version(name) for name in expected}
    # then
    assert installed == expected


def test_started_span_carries_a_valid_trace_id_and_exports() -> None:
    # given
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("ascend-web-hunter.otel-probe-4-4")
    # when
    with tracer.start_as_current_span("probe-span") as span:
        trace_id = span.get_span_context().trace_id
    # then
    assert re.fullmatch(r"[0-9a-f]{32}", format(trace_id, "032x")) is not None
    assert [finished.name for finished in exporter.get_finished_spans()] == ["probe-span"]
