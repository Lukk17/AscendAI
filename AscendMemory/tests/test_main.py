from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import src.main as main_module
from src.main import app


def test_liveness_health_always_returns_200(override_dependencies):
    with patch("src.main.warmup_client", new_callable=AsyncMock):
        main_module.is_ready = False
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json()["status"] == "ok"


def test_legacy_health_reports_503_until_warmup_done(override_dependencies):
    with patch("src.main.warmup_client", new_callable=AsyncMock):
        main_module.is_ready = False
        with TestClient(app) as client:
            response = client.get("/health/legacy")
            assert response.status_code == 503
            assert response.json()["status"] == "starting"


def test_legacy_health_returns_200_after_warmup(override_dependencies):
    main_module.is_ready = True
    with TestClient(app) as client:
        response = client.get("/health/legacy")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_metrics_endpoint_exposes_prometheus_payload(override_dependencies):
    with patch("src.main.warmup_client", new_callable=AsyncMock):
        with TestClient(app) as client:
            response = client.get("/metrics")
            assert response.status_code == 200
            assert "memory_insert_total" in response.text or "process_" in response.text


@pytest.mark.asyncio
async def test_warmup_client_succeeds_on_first_attempt():
    main_module.is_ready = False
    with patch("src.main.get_memory_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        await main_module.warmup_client()

        assert main_module.is_ready is True
        mock_client.search.assert_called_once()


@pytest.mark.asyncio
async def test_warmup_client_retries_until_max_attempts(monkeypatch):
    main_module.is_ready = False
    monkeypatch.setattr(main_module, "WARMUP_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(main_module, "WARMUP_RETRY_DELAY_SECONDS", 0)

    with patch("src.main.get_memory_client", side_effect=RuntimeError("not yet")):
        await main_module.warmup_client()

    assert main_module.is_ready is False


@pytest.mark.asyncio
async def test_warmup_client_logs_warning_on_transient_failure(monkeypatch):
    main_module.is_ready = False
    monkeypatch.setattr(main_module, "WARMUP_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(main_module, "WARMUP_RETRY_DELAY_SECONDS", 0)

    mock_client = MagicMock()
    call_count = {"n": 0}

    def get_client_then_succeed(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise RuntimeError("cold")
        return mock_client

    with patch("src.main.get_memory_client", side_effect=get_client_then_succeed):
        await main_module.warmup_client()

    assert main_module.is_ready is True
    assert call_count["n"] == 2
