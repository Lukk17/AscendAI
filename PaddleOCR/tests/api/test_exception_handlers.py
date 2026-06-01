import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.exception_handlers import (
    DownloadFailedError,
    FileSizeExceededError,
    OcrProcessingError,
    UnsafeUriError,
    UnsupportedFileTypeError,
    register_exception_handlers,
)


@pytest.fixture
def app_with_handlers():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/trigger-ocr-error")
    async def trigger_ocr_error():
        raise OcrProcessingError("internal stack trace with /etc/secret")

    @app.get("/trigger-file-size-error")
    async def trigger_file_size_error():
        raise FileSizeExceededError("File too large internal detail")

    @app.get("/trigger-file-type-error")
    async def trigger_file_type_error():
        raise UnsupportedFileTypeError("text/html")

    @app.get("/trigger-unsafe-uri")
    async def trigger_unsafe_uri():
        raise UnsafeUriError("internal-network leak attempt")

    @app.get("/trigger-download-failed")
    async def trigger_download_failed():
        raise DownloadFailedError("HTTP 404")

    @app.get("/trigger-generic-error")
    async def trigger_generic_error():
        raise RuntimeError("internal traceback should not leak")

    return app


@pytest.fixture
def test_client(app_with_handlers):
    return TestClient(app_with_handlers, raise_server_exceptions=False)


class TestOcrProcessingExceptionHandler:
    def test_returns_422_with_generic_message(self, test_client):
        # When
        response = test_client.get("/trigger-ocr-error")

        # Then
        assert response.status_code == 422
        payload = response.json()
        assert payload["code"] == "OCR_FAILED"
        assert payload["detail"] == "OCR processing failed"
        assert "/etc/secret" not in response.text


class TestFileSizeExceededHandler:
    def test_returns_400(self, test_client):
        # When
        response = test_client.get("/trigger-file-size-error")

        # Then
        assert response.status_code == 400
        payload = response.json()
        assert payload["code"] == "FILE_TOO_LARGE"
        assert payload["detail"] == "File too large"


class TestUnsupportedFileTypeHandler:
    def test_returns_400(self, test_client):
        # When
        response = test_client.get("/trigger-file-type-error")

        # Then
        assert response.status_code == 400
        payload = response.json()
        assert payload["code"] == "UNSUPPORTED_FILE_TYPE"
        assert payload["detail"] == "Unsupported file type"


class TestUnsafeUriHandler:
    def test_returns_400(self, test_client):
        # When
        response = test_client.get("/trigger-unsafe-uri")

        # Then
        assert response.status_code == 400
        payload = response.json()
        assert payload["code"] == "UNSAFE_URI"
        assert "internal-network" not in response.text


class TestDownloadFailedHandler:
    def test_returns_502(self, test_client):
        # When
        response = test_client.get("/trigger-download-failed")

        # Then
        assert response.status_code == 502
        payload = response.json()
        assert payload["code"] == "DOWNLOAD_FAILED"


class TestGlobalExceptionHandler:
    def test_returns_500_with_generic_message(self, test_client):
        # When
        response = test_client.get("/trigger-generic-error")

        # Then
        assert response.status_code == 500
        payload = response.json()
        assert payload["code"] == "INTERNAL_ERROR"
        assert payload["detail"] == "Internal server error"
        assert "traceback" not in response.text
