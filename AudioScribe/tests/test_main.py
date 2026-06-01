from fastapi.testclient import TestClient

from src.main import app


def test_health_returns_200() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_metrics_returns_prometheus_payload() -> None:
    with TestClient(app) as client:
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "audioscribe_" in response.text or "process_" in response.text


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
