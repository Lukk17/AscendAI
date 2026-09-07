import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import _configure_otel, app


def _otel_sys_modules() -> dict[str, MagicMock]:
    """Return mocked OTel sub-modules for sys.modules injection.

    All parent packages must also be present so Python's import machinery
    resolves dotted names without touching the real (absent) SDK packages.
    """
    base = MagicMock()
    sdk = MagicMock()
    sdk_trace = MagicMock()
    sdk_trace_export = MagicMock()
    sdk_resources = MagicMock()
    exporter = MagicMock()
    exporter_otlp = MagicMock()
    exporter_otlp_proto = MagicMock()
    exporter_otlp_proto_grpc = MagicMock()
    exporter_otlp_proto_grpc_trace = MagicMock()
    instrumentation = MagicMock()
    instrumentation_fastapi = MagicMock()

    return {
        "opentelemetry": base,
        "opentelemetry.sdk": sdk,
        "opentelemetry.sdk.trace": sdk_trace,
        "opentelemetry.sdk.trace.export": sdk_trace_export,
        "opentelemetry.sdk.resources": sdk_resources,
        "opentelemetry.exporter": exporter,
        "opentelemetry.exporter.otlp": exporter_otlp,
        "opentelemetry.exporter.otlp.proto": exporter_otlp_proto,
        "opentelemetry.exporter.otlp.proto.grpc": exporter_otlp_proto_grpc,
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": exporter_otlp_proto_grpc_trace,
        "opentelemetry.instrumentation": instrumentation,
        "opentelemetry.instrumentation.fastapi": instrumentation_fastapi,
    }


def test_configure_otel_noop_when_env_var_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    _configure_otel()


def test_configure_otel_activates_when_endpoint_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel:4317")
    with patch.dict(sys.modules, _otel_sys_modules()):
        _configure_otel()


def test_health_returns_200() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_metrics_returns_prometheus_payload() -> None:
    with TestClient(app) as client:
        response = client.get("/metrics")
        assert response.status_code == 200
        body = response.text
        assert "process_" in body or "python_" in body
        assert "ascendaudioscribe_transcription_duration_seconds" in body


def test_request_id_echoed_back() -> None:
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "trace-abc"})
        assert response.headers["X-Request-ID"] == "trace-abc"


def test_request_id_generated_when_missing() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
        assert "X-Request-ID" in response.headers
        assert len(response.headers["X-Request-ID"]) >= 16


def test_request_id_malformed_replaced() -> None:
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "bad\nvalue"})
        assert "\n" not in response.headers["X-Request-ID"]
