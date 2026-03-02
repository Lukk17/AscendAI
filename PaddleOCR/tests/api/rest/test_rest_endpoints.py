import io
import pytest
from httpx import AsyncClient, ASGITransport
from src.main import create_app
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture
def app():
    with patch("src.main.ocr_service") as mock_service:
        mock_service.warm_up_engine = MagicMock()
        test_app = create_app()
        yield test_app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealthEndpoint:
    async def test_health_returns_ok(self, client):
        # Arrange / Act
        response = await client.get("/health")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestOcrEndpoint:
    @patch("src.api.rest.rest_endpoints.ocr_service")
    async def test_successful_ocr_json(self, mock_service, client):
        # Arrange
        from src.model.ocr_models import OcrJsonResponse, OcrPageResult, OcrTextLine
        mock_line = OcrTextLine(
            text="Test text", confidence=0.95,
            bounding_box=[[0, 0], [100, 0], [100, 20], [0, 20]],
        )
        mock_response = OcrJsonResponse(
            filename="test.png", language="en",
            pages=[OcrPageResult(page_number=1, lines=[mock_line])],
            processing_time_seconds=0.5,
        )
        mock_service.process_file.return_value = mock_response
        file_content = b"fake image bytes"

        # Act
        response = await client.post(
            "/v1/ocr",
            files={"files": ("test.png", io.BytesIO(file_content), "image/png")},
            data={"lang": "en"},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "test.png"
        assert len(data["pages"]) == 1

    async def test_missing_file_returns_422(self, client):
        # Arrange / Act
        response = await client.post("/v1/ocr")

        # Assert
        assert response.status_code == 422

    async def test_unsupported_file_type_returns_400(self, client):
        # Arrange
        file_content = b"not an image"

        # Act
        response = await client.post(
            "/v1/ocr",
            files={"files": ("test.txt", io.BytesIO(file_content), "text/plain")},
        )

        # Assert
        assert response.status_code == 400

    @patch("src.api.rest.rest_endpoints.settings")
    async def test_oversized_file_returns_400(self, mock_settings, client):
        # Arrange
        mock_settings.MAX_FILE_SIZE_MB = 0
        mock_settings.DEFAULT_LANGUAGE = "en"
        mock_settings.DEFAULT_OUTPUT_FORMAT = "json"
        file_content = b"x" * 1024

        # Act
        response = await client.post(
            "/v1/ocr",
            files={"files": ("test.png", io.BytesIO(file_content), "image/png")},
        )

        # Assert
        assert response.status_code == 400
