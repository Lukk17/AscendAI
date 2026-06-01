import io
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.config.config import settings
from src.main import create_app
from tests.conftest import PDF_MAGIC_BYTES, PNG_MAGIC_BYTES, OcrResponseFactory


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
        # When
        response = await client.get("/health")

        # Then
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestReadyEndpoint:
    @patch("src.main.ocr_service")
    async def test_ready_returns_not_ready_when_engine_cold(self, mock_service, client):
        # Given
        mock_service._engines = {}

        # When
        response = await client.get("/ready")

        # Then
        assert response.status_code == 200
        assert response.json()["status"] == "not-ready"
        assert response.json()["engine_warm"] is False

    @patch("src.main.ocr_service")
    async def test_ready_returns_ready_when_engine_warm(self, mock_service, client):
        # Given
        mock_service._engines = {settings.DEFAULT_LANGUAGE: object()}

        # When
        response = await client.get("/ready")

        # Then
        assert response.json()["status"] == "ready"
        assert response.json()["engine_warm"] is True


class TestMetricsEndpoint:
    async def test_metrics_endpoint_serves_prometheus_text(self, client):
        # When
        response = await client.get("/metrics")

        # Then
        assert response.status_code == 200
        assert "paddleocr_ocr_requests_total" in response.text or "# HELP" in response.text


class TestSecurityHeaders:
    async def test_hsts_header_on_health(self, client):
        # When
        response = await client.get("/health")

        # Then
        assert "strict-transport-security" in response.headers


class TestCorrelationIdHeader:
    async def test_response_carries_correlation_id(self, client):
        # When
        response = await client.get("/health")

        # Then
        assert "x-request-id" in response.headers


class TestOcrEndpoint:
    @patch("src.api.rest.rest_endpoints.ocr_service")
    async def test_successful_ocr_json(self, mock_service, client):
        # Given
        mock_service.process_file.return_value = OcrResponseFactory.with_single_line()

        # When
        response = await client.post(
            "/v1/ocr",
            files={"file": ("test.png", io.BytesIO(PNG_MAGIC_BYTES), "image/png")},
            data={"lang": "en"},
        )

        # Then
        assert response.status_code == 200
        assert response.json()["filename"] == "test.png"
        assert response.json()["schema_version"] == "1"

    @patch("src.api.rest.rest_endpoints.ocr_service")
    async def test_pdf_accepted(self, mock_service, client):
        # Given
        mock_service.process_file.return_value = OcrResponseFactory.with_single_line(filename="doc.pdf")

        # When
        response = await client.post(
            "/v1/ocr",
            files={"file": ("doc.pdf", io.BytesIO(PDF_MAGIC_BYTES), "application/pdf")},
        )

        # Then
        assert response.status_code == 200

    @patch("src.api.rest.rest_endpoints.ocr_service")
    async def test_ocr_service_failure_returns_422_with_generic_message(self, mock_service, client):
        # Given
        mock_service.process_file.side_effect = RuntimeError("engine internal trace")

        # When
        response = await client.post(
            "/v1/ocr",
            files={"file": ("test.png", io.BytesIO(PNG_MAGIC_BYTES), "image/png")},
        )

        # Then
        assert response.status_code == 422
        payload = response.json()
        assert payload["code"] == "OCR_FAILED"
        assert "engine internal trace" not in response.text

    @patch("src.api.rest.rest_endpoints.ocr_service")
    async def test_service_size_error_propagates_as_400(self, mock_service, client):
        # Given. The service layer can raise FileSizeExceededError too (e.g. during PDF
        # multi-page processing). The REST endpoint must re-raise it untouched so the
        # global handler returns 400 with code=FILE_TOO_LARGE, not 422 OCR_FAILED.
        from src.api.exception_handlers import FileSizeExceededError
        mock_service.process_file.side_effect = FileSizeExceededError("page exceeds cap")

        # When
        response = await client.post(
            "/v1/ocr",
            files={"file": ("test.png", io.BytesIO(PNG_MAGIC_BYTES), "image/png")},
        )

        # Then
        assert response.status_code == 400
        assert response.json()["code"] == "FILE_TOO_LARGE"

    async def test_missing_file_returns_422(self, client):
        # When
        response = await client.post("/v1/ocr")

        # Then
        assert response.status_code == 422

    async def test_unsupported_magic_bytes_returns_400(self, client):
        # When
        response = await client.post(
            "/v1/ocr",
            files={"file": ("test.txt", io.BytesIO(b"plain text"), "text/plain")},
        )

        # Then
        assert response.status_code == 400
        assert response.json()["code"] == "UNSUPPORTED_FILE_TYPE"

    @patch("src.api.rest.rest_endpoints.settings")
    async def test_oversized_file_returns_400(self, mock_settings, client):
        # Given
        mock_settings.MAX_FILE_SIZE_MB = 0
        mock_settings.DEFAULT_LANGUAGE = "en"
        mock_settings.OCR_REQUEST_TIMEOUT = 30.0
        mock_settings.RATE_LIMIT_OCR = "1000/minute"

        # When
        response = await client.post(
            "/v1/ocr",
            files={"file": ("test.png", io.BytesIO(PNG_MAGIC_BYTES * 200), "image/png")},
        )

        # Then
        assert response.status_code == 400
        assert response.json()["code"] == "FILE_TOO_LARGE"
