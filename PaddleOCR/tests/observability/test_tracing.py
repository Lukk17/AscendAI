from unittest.mock import MagicMock, patch

from src.config.config import settings
from src.observability.tracing import configure_tracing, get_tracer


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


class TestGetTracer:
    def test_returns_tracer_instance(self):
        # When
        tracer = get_tracer()

        # Then
        assert tracer is not None
        with tracer.start_as_current_span("test") as span:
            assert span is not None
