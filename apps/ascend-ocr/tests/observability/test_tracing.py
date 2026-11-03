from collections.abc import Iterator
from unittest.mock import patch

import pytest
from ascend_python_common.tracing import build_tracer_provider
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from src.config.config import settings
from src.observability.tracing import (
    configure_worker_tracing,
    extract_trace_context,
    get_tracer,
    inject_trace_context,
)


@pytest.fixture
def _isolated_global_provider() -> Iterator[None]:
    from opentelemetry.util._once import Once

    saved_provider = trace._TRACER_PROVIDER
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE = Once()
    yield
    trace._TRACER_PROVIDER = saved_provider
    trace._TRACER_PROVIDER_SET_ONCE = Once()


class TestConfigureWorkerTracing:
    def test_worker_tracing_builds_through_the_library_builder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # given
        monkeypatch.setattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "http://probe-collector:4317")
        # when
        with patch("src.observability.tracing.build_tracer_provider") as mock_build:
            with patch("src.observability.tracing.trace.set_tracer_provider") as mock_set:
                configure_worker_tracing()
        # then
        mock_build.assert_called_once_with("ascend-ocr", otel_endpoint="http://probe-collector:4317")
        mock_set.assert_called_once_with(mock_build.return_value)

    @pytest.mark.usefixtures("_isolated_global_provider")
    def test_endpoint_set_installs_a_sampled_provider_for_ascend_ocr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # given
        monkeypatch.setattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "http://probe-collector:4317")
        # when
        configure_worker_tracing()
        provider = trace.get_tracer_provider()
        # then
        assert isinstance(provider, TracerProvider)
        assert provider.resource.attributes["service.name"] == "ascend-ocr"

    @pytest.mark.usefixtures("_isolated_global_provider")
    def test_endpoint_unset_installs_an_unsampled_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # given
        monkeypatch.setattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", None)
        # when
        configure_worker_tracing()
        # then
        assert isinstance(trace.get_tracer_provider(), TracerProvider)
        with get_tracer().start_as_current_span("probe") as span:
            sampled = span.get_span_context().trace_flags.sampled
        assert sampled is False


class TestGetTracer:
    def test_returns_a_tracer_that_starts_a_span(self) -> None:
        # given
        tracer = get_tracer()
        # when
        with tracer.start_as_current_span("probe") as span:
            span_context = span.get_span_context()
        # then
        assert span_context.trace_id != 0


class TestTraceContextPropagation:
    def test_inject_returns_empty_carrier_without_active_span(self) -> None:
        # when - no span is current at module scope, so nothing is injected
        carrier = inject_trace_context()
        # then
        assert carrier == {}

    def test_inject_delegates_to_the_propagator(self) -> None:
        # given
        def fake_inject(carrier: dict[str, str]) -> None:
            carrier["traceparent"] = "00-fake-01"

        # when
        with patch("src.observability.tracing.propagate.inject", side_effect=fake_inject):
            carrier = inject_trace_context()
        # then
        assert carrier == {"traceparent": "00-fake-01"}

    def test_extract_delegates_to_the_propagator(self) -> None:
        # given
        sentinel_context = object()
        carrier = {"traceparent": "00-fake-01"}
        # when
        with patch(
            "src.observability.tracing.propagate.extract", return_value=sentinel_context
        ) as mock_extract:
            result = extract_trace_context(carrier)
        # then
        assert result is sentinel_context
        mock_extract.assert_called_once_with(carrier)

    def test_injected_context_carried_into_the_worker_stays_on_one_trace(self) -> None:
        # given - a provider of our own, so the global one is left alone
        provider = build_tracer_provider("probe", otel_endpoint=None)
        tracer = provider.get_tracer("probe")
        # when
        with tracer.start_as_current_span("parent"):
            carrier = inject_trace_context()
        child_context = extract_trace_context(carrier)
        with tracer.start_as_current_span("child", context=child_context) as child:
            child_trace_id = format(child.get_span_context().trace_id, "032x")
        # then
        assert carrier["traceparent"].split("-")[1] == child_trace_id
