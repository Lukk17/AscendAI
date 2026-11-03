from importlib.metadata import version as get_package_version

from fastapi.testclient import TestClient

from src.main import app


def test_health_returns_200() -> None:
    # given
    with TestClient(app) as client:
        # when
        response = client.get("/health")

        # then
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["service"] == "ascend-audio-scribe"


def test_app_version_matches_installed_package_metadata() -> None:
    # when / then
    assert app.version == get_package_version("ascend-audio-scribe")


def test_metrics_returns_prometheus_payload() -> None:
    # given
    from src.observability import metrics as service_metrics

    service_metrics.TRANSCRIPTION_DURATION_SECONDS.labels(provider="local", outcome="ok").observe(1.0)
    service_metrics.TRANSCRIPTION_AUDIO_DURATION_SECONDS.labels(provider="local").observe(60.0)
    with TestClient(app) as client:
        # when
        response = client.get("/metrics")

        # then
        assert response.status_code == 200
        body = response.text
        assert "process_" in body or "python_" in body
        assert "transcription_duration_seconds" in body
        assert "transcription_audio_duration_seconds" in body


def test_request_id_echoed_back() -> None:
    # given
    with TestClient(app) as client:
        # when
        response = client.get("/health", headers={"X-Request-ID": "trace-abc"})

        # then
        assert response.headers["X-Request-ID"] == "trace-abc"


def test_request_id_generated_when_missing() -> None:
    # given
    with TestClient(app) as client:
        # when
        response = client.get("/health")

        # then
        assert "X-Request-ID" in response.headers
        assert len(response.headers["X-Request-ID"]) >= 16


def test_request_id_malformed_replaced() -> None:
    # given
    with TestClient(app) as client:
        # when
        response = client.get("/health", headers={"X-Request-ID": "bad\nvalue"})

        # then
        assert "\n" not in response.headers["X-Request-ID"]
