import logging

import pytest
from ascend_python_common.errors import ERRORS_TOTAL, INTERNAL_FIXED_DETAIL
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.exception_handlers import (
    DownloadFailedError,
    FileSizeExceededError,
    JobNotFoundError,
    OcrProcessingError,
    QueueFullError,
    UnsafeUriError,
    UnsupportedFileTypeError,
    UnsupportedLanguageError,
    _queue_full_headers,
    register_exception_handlers,
)
from src.config.config import MCP_ENDPOINT_PATH

REFUSALS_LOGGER = "ascend_python_common.errors.refusals"


@pytest.fixture
def app_with_handlers() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/trigger-ocr-error")
    async def trigger_ocr_error() -> None:
        raise OcrProcessingError("internal stack trace with /etc/secret")

    @app.get("/trigger-file-size-error")
    async def trigger_file_size_error() -> None:
        raise FileSizeExceededError("File too large internal detail")

    @app.get("/trigger-file-type-error")
    async def trigger_file_type_error() -> None:
        raise UnsupportedFileTypeError("text/html")

    @app.get("/trigger-unsafe-uri")
    async def trigger_unsafe_uri() -> None:
        raise UnsafeUriError("internal-network leak attempt")

    @app.get("/trigger-download-failed")
    async def trigger_download_failed() -> None:
        raise DownloadFailedError("HTTP 404")

    @app.get("/trigger-generic-error")
    async def trigger_generic_error() -> None:
        raise RuntimeError("internal traceback should not leak")

    @app.get("/trigger-queue-full")
    async def trigger_queue_full() -> None:
        raise QueueFullError("8 documents are already waiting", retry_after_seconds=12.3)

    @app.get("/trigger-job-not-found")
    async def trigger_job_not_found() -> None:
        raise JobNotFoundError("no record for job /var/lib/ascend-ocr-jobs/secret")

    @app.get("/trigger-unsupported-language")
    async def trigger_unsupported_language() -> None:
        raise UnsupportedLanguageError("Language is not supported. Supported languages: en, pl")

    return app


@pytest.fixture
def test_client(app_with_handlers: FastAPI) -> TestClient:
    return TestClient(app_with_handlers, raise_server_exceptions=False)


class TestOcrProcessingExceptionHandler:
    def test_returns_422_problem_body_with_generic_message(self, test_client: TestClient) -> None:
        # When
        response = test_client.get("/trigger-ocr-error")

        # Then
        assert response.status_code == 422
        assert "application/problem+json" in response.headers["content-type"]
        payload = response.json()
        assert payload["code"] == "OCR_FAILED"
        assert payload["type"] == "https://ascend.ai/errors/ocr-failed"
        assert payload["title"] == "Unprocessable Entity"
        assert payload["status"] == 422
        assert payload["detail"] == "OCR processing failed"
        assert payload["instance"] == "/trigger-ocr-error"
        assert "/etc/secret" not in response.text


class TestFileSizeExceededHandler:
    def test_returns_400(self, test_client: TestClient) -> None:
        # When
        response = test_client.get("/trigger-file-size-error")

        # Then
        assert response.status_code == 400
        payload = response.json()
        assert payload["code"] == "FILE_TOO_LARGE"
        assert payload["type"] == "https://ascend.ai/errors/file-too-large"
        assert payload["detail"] == "File too large"


class TestUnsupportedFileTypeHandler:
    def test_returns_400(self, test_client: TestClient) -> None:
        # When
        response = test_client.get("/trigger-file-type-error")

        # Then
        assert response.status_code == 400
        payload = response.json()
        assert payload["code"] == "UNSUPPORTED_FILE_TYPE"
        assert payload["detail"] == "Unsupported file type"


class TestUnsafeUriHandler:
    def test_returns_400(self, test_client: TestClient) -> None:
        # When
        response = test_client.get("/trigger-unsafe-uri")

        # Then
        assert response.status_code == 400
        payload = response.json()
        assert payload["code"] == "UNSAFE_URI"
        assert payload["detail"] == "URI is not permitted"
        assert "internal-network" not in response.text


class TestDownloadFailedHandler:
    def test_returns_502_with_its_useful_detail(self, test_client: TestClient) -> None:
        # When
        response = test_client.get("/trigger-download-failed")

        # Then
        assert response.status_code == 502
        payload = response.json()
        assert payload["code"] == "DOWNLOAD_FAILED"
        assert payload["type"] == "https://ascend.ai/errors/download-failed"
        assert payload["detail"] == "Failed to fetch source"


class TestGlobalExceptionHandler:
    def test_returns_500_with_fixed_detail(self, test_client: TestClient) -> None:
        # When
        response = test_client.get("/trigger-generic-error")

        # Then
        assert response.status_code == 500
        payload = response.json()
        assert payload["code"] == "INTERNAL_ERROR"
        assert payload["type"] == "https://ascend.ai/errors/internal-error"
        assert payload["detail"] == INTERNAL_FIXED_DETAIL
        assert "traceback" not in response.text


class TestQueueFullHandler:
    def test_returns_503_with_a_retry_hint(self, test_client: TestClient) -> None:
        # When
        response = test_client.get("/trigger-queue-full")

        # Then
        assert response.status_code == 503
        payload = response.json()
        assert payload["code"] == "QUEUE_FULL"
        assert payload["detail"] == "Queue is full, retry later"
        # Rounded up, so a caller that honours it never comes back before the hint
        assert response.headers["retry-after"] == "13"


class TestQueueFullHeaders:
    def test_an_exception_of_another_type_carries_no_retry_hint(self) -> None:
        # given
        other = ValueError("not a queue refusal")
        # when
        headers = _queue_full_headers(other)
        # then
        assert headers is None


class TestJobNotFoundHandler:
    def test_returns_404_without_leaking_the_path_it_looked_in(self, test_client: TestClient) -> None:
        # When
        response = test_client.get("/trigger-job-not-found")

        # Then
        assert response.status_code == 404
        payload = response.json()
        assert payload["code"] == "JOB_NOT_FOUND"
        assert payload["detail"] == "Job identifier is unknown or expired"
        assert "/var/lib" not in response.text


class TestUnsupportedLanguageHandler:
    def test_returns_400_naming_the_supported_languages(self, test_client: TestClient) -> None:
        # When
        response = test_client.get("/trigger-unsupported-language")

        # Then
        assert response.status_code == 400
        payload = response.json()
        assert payload["code"] == "UNSUPPORTED_LANGUAGE"
        assert payload["type"] == "https://ascend.ai/errors/unsupported-language"
        assert payload["detail"] == "Language is not supported. Supported languages: en, pl"


class TestErrorCatalogue:
    def test_the_existing_codes_and_statuses_are_unchanged(self, test_client: TestClient) -> None:
        # Given - the catalogue as it stood before the job surface existed
        existing = {
            "/trigger-ocr-error": (422, "OCR_FAILED"),
            "/trigger-file-size-error": (400, "FILE_TOO_LARGE"),
            "/trigger-file-type-error": (400, "UNSUPPORTED_FILE_TYPE"),
            "/trigger-unsafe-uri": (400, "UNSAFE_URI"),
            "/trigger-download-failed": (502, "DOWNLOAD_FAILED"),
            "/trigger-generic-error": (500, "INTERNAL_ERROR"),
        }

        # When
        observed = {
            path: (test_client.get(path).status_code, test_client.get(path).json()["code"])
            for path in existing
        }

        # Then
        assert observed == existing


class TestRefusalLogging:
    @pytest.mark.parametrize(
        ("path", "code"),
        [
            ("/trigger-ocr-error", "OCR_FAILED"),
            ("/trigger-unsafe-uri", "UNSAFE_URI"),
            ("/trigger-file-type-error", "UNSUPPORTED_FILE_TYPE"),
            ("/trigger-file-size-error", "FILE_TOO_LARGE"),
            ("/trigger-unsupported-language", "UNSUPPORTED_LANGUAGE"),
            ("/trigger-job-not-found", "JOB_NOT_FOUND"),
            ("/trigger-download-failed", "DOWNLOAD_FAILED"),
        ],
    )
    def test_an_expected_refusal_is_one_warning_naming_its_code_with_no_traceback(
        self,
        test_client: TestClient,
        emitted_logs: list[logging.LogRecord],
        path: str,
        code: str,
    ) -> None:
        # When
        test_client.get(path)

        # Then
        logged = [record for record in emitted_logs if record.name == REFUSALS_LOGGER]
        assert [(record.levelno, code in record.getMessage(), record.exc_info) for record in logged] == [
            (logging.WARNING, True, None)
        ]

    @pytest.mark.parametrize("path", ["/trigger-queue-full", "/trigger-generic-error"])
    def test_an_unexpected_error_is_still_an_error_with_its_traceback(
        self, test_client: TestClient, emitted_logs: list[logging.LogRecord], path: str
    ) -> None:
        # When
        test_client.get(path)

        # Then
        logged = [record for record in emitted_logs if record.name == REFUSALS_LOGGER]
        assert [record.levelno for record in logged] == [logging.ERROR]
        assert logged[0].exc_info is not None


class TestErrorSurfaceLabel:
    @pytest.mark.parametrize(
        "path",
        [
            "/ready",
            "/health",
            "/metrics",
            "/v1/ocr/jobs/unknown-job",
            MCP_ENDPOINT_PATH,
        ],
    )
    def test_an_internal_error_is_counted_under_the_route_it_reached(self, path: str) -> None:
        # Given
        app = FastAPI()
        register_exception_handlers(app)

        @app.post(path)
        async def fail() -> None:
            raise RuntimeError("internal failure")

        client = TestClient(app, raise_server_exceptions=False)
        counted = ERRORS_TOTAL.labels(code="INTERNAL_ERROR", surface="rest", operation=path)
        before = counted._value.get()

        # When
        response = client.post(path)

        # Then
        assert (response.status_code, counted._value.get()) == (500, before + 1)
