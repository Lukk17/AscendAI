import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock

from src.main import app


def test_health_check_status(override_dependencies):
    # given
    import src.main as main_module

    # 1. Test Unready State
    # Patch warmup_client to verify 503
    with patch("src.main.warmup_client", new_callable=AsyncMock) as mock_warmup:
        # Reset ready state
        main_module.is_ready = False
        with TestClient(app) as client:
            # when
            response = client.get("/health")
            # then
            assert response.status_code == 503
            assert response.json()["status"] == "starting"

    # 2. Test Ready State
    main_module.is_ready = True
    with TestClient(app) as client:
        # when
        response = client.get("/health")
        # then
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_warmup_client_success():
    # given
    import src.main as main_module
    main_module.is_ready = False

    with patch("src.main.get_memory_client") as mock_get_client:
        mock_client_instance = MagicMock()  # Search is synchronous
        mock_get_client.return_value = mock_client_instance

        # when
        await main_module.warmup_client()

        # then
        assert main_module.is_ready is True
        mock_client_instance.search.assert_called_once()
