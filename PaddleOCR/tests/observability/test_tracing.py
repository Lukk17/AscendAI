from unittest.mock import MagicMock, patch

from src.config.config import settings
from src.observability.tracing import (
    configure_tracing,
    configure_worker_tracing,
    extract_trace_context,
    get_tracer,
    inject_trace_context,
)


class TestConfigureTracing:
    def test_disabled_when_otel_off(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OTEL_ENABLED", False)
        app = MagicMock()

        # When
        configure_tracing(app)

        # Then — no FastAPI instrumentation calls
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


class TestConfigureWorkerTracing:
    def test_disabled_when_otel_off(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OTEL_ENABLED", False)

        # When
        with patch("src.observability.tracing.TracerProvider") as mock_provider:
            configure_worker_tracing()

        # Then — no provider is built when tracing is off
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
        # Given — a worker process has no FastAPI app and no aiohttp client of its own
        monkeypatch.setattr(settings, "OTEL_ENABLED", True)

        # When
        configure_worker_tracing()

        # Then
        mock_provider.assert_called_once()
        mock_exporter.assert_called_once()
        mock_fastapi_inst.instrument_app.assert_not_called()
        mock_aiohttp_inst.return_value.instrument.assert_not_called()


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
        # When — no span is current at module scope, so nothing is injected
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
