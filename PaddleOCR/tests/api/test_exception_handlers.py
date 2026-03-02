import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.api.exception_handlers import (
    OcrProcessingError,
    FileSizeExceededError,
    UnsupportedFileTypeError,
    register_exception_handlers,
)
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def app_with_handlers():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/trigger-ocr-error")
    async def trigger_ocr_error():
        raise OcrProcessingError("OCR failed")

    @app.get("/trigger-file-size-error")
    async def trigger_file_size_error():
        raise FileSizeExceededError("File too large")

    @app.get("/trigger-file-type-error")
    async def trigger_file_type_error():
        raise UnsupportedFileTypeError("Invalid type")

    @app.get("/trigger-generic-error")
    async def trigger_generic_error():
        raise RuntimeError("Unexpected error")

    return app


@pytest.fixture
def test_client(app_with_handlers):
    return TestClient(app_with_handlers, raise_server_exceptions=False)


class TestOcrProcessingExceptionHandler:
    def test_returns_422(self, test_client):
        # Arrange / Act
        response = test_client.get("/trigger-ocr-error")

        # Assert
        assert response.status_code == 422
        assert response.json()["detail"] == "OCR failed"


class TestFileSizeExceededHandler:
    def test_returns_400(self, test_client):
        # Arrange / Act
        response = test_client.get("/trigger-file-size-error")

        # Assert
        assert response.status_code == 400
        assert response.json()["detail"] == "File too large"


class TestUnsupportedFileTypeHandler:
    def test_returns_400(self, test_client):
        # Arrange / Act
        response = test_client.get("/trigger-file-type-error")

        # Assert
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid type"


class TestGlobalExceptionHandler:
    def test_returns_500(self, test_client):
        # Arrange / Act
        response = test_client.get("/trigger-generic-error")

        # Assert
        assert response.status_code == 500
        assert response.json()["detail"] == "Internal server error"
