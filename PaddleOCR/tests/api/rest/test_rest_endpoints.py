import io
from concurrent.futures.process import BrokenProcessPool
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.exception_handlers import FileSizeExceededError
from src.config.config import settings
from src.main import create_app
from tests.conftest import PDF_MAGIC_BYTES, PNG_MAGIC_BYTES, OcrResponseFactory


class _BrokenExecutor:
    """Stands in for a real ProcessPoolExecutor whose pool initializer failed.

    concurrent.futures marks the whole pool broken in that case, so every subsequent
    submission raises BrokenProcessPool synchronously, which is what loop.run_in_executor
    calls under the hood.
    """

    def submit(self, *_args: object, **_kwargs: object) -> None:
        raise BrokenProcessPool("worker pool is broken")


@pytest.fixture
def app():
    # create_app() never touches ocr_service at call time: the engine warm-up only
    # runs inside the OCR worker process, once the ASGI lifespan actually starts it,
    # which none of these tests drive (see _stub_process_pool below).
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _stub_process_pool():
    # process_ocr() dispatches through get_process_pool(), which is only populated by
    # main.py's lifespan (not driven in these tests). Returning None makes run_in_executor
    # fall back to the default in-process thread pool, matching the pre-worker-pool
    # dispatch these tests were written against, without spawning a real subprocess.
    with patch("src.api.rest.rest_endpoints.get_process_pool", return_value=None):
        yield


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
    @patch("src.main.is_engine_warm", return_value=False)
    async def test_ready_returns_not_ready_when_engine_cold(self, mock_is_warm, client):
        # When
        response = await client.get("/ready")

        # Then
        assert response.status_code == 200
        assert response.json()["status"] == "not-ready"
        assert response.json()["engine_warm"] is False
        mock_is_warm.assert_called_once_with(settings.DEFAULT_LANGUAGE)

    @patch("src.main.is_engine_warm", return_value=True)
    async def test_ready_returns_ready_when_engine_warm(self, mock_is_warm, client):
        # When
        response = await client.get("/ready")

        # Then
        assert response.json()["status"] == "ready"
        assert response.json()["engine_warm"] is True
        mock_is_warm.assert_called_once_with(settings.DEFAULT_LANGUAGE)


class TestMetricsEndpoint:
    async def test_metrics_endpoint_serves_prometheus_text(self, client):
        # When
        response = await client.get("/metrics")

        # Then
        assert response.status_code == 200
        body = response.text
        # PROMETHEUS_MULTIPROC_DIR (set in src/__init__.py) makes prometheus-fastapi-
        # instrumentator serve this endpoint through prometheus_client's
        # MultiProcessCollector, which merges every process's own file so that
        # counters incremented in the OCR worker process reach this response too.
        # That collector only reads the value files backing user-defined Counter /
        # Histogram / Summary metrics, so the built-in process_*/python_* collectors,
        # which compute their values live and were never written to a file, are
        # correctly absent here rather than a sign the endpoint is broken.
        assert "paddleocr_ocr_requests_total" in body
        assert "http_" in body


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

    @patch("src.api.rest.rest_endpoints.inject_trace_context")
    @patch("src.api.rest.rest_endpoints.ocr_service")
    async def test_trace_context_is_forwarded_to_worker(self, mock_service, mock_inject, client):
        # Given — the carrier is captured from the auto-instrumented request span, so
        # the worker process can reattach its own span as that span's child
        mock_service.process_file.return_value = OcrResponseFactory.with_single_line()
        mock_inject.return_value = {"traceparent": "00-fake-01"}

        # When
        response = await client.post(
            "/v1/ocr",
            files={"file": ("test.png", io.BytesIO(PNG_MAGIC_BYTES), "image/png")},
        )

        # Then
        assert response.status_code == 200
        mock_inject.assert_called_once()
        assert mock_service.process_file.call_args.args[3] == {"traceparent": "00-fake-01"}

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
        mock_service.process_file.side_effect = FileSizeExceededError("page exceeds cap")

        # When
        response = await client.post(
            "/v1/ocr",
            files={"file": ("test.png", io.BytesIO(PNG_MAGIC_BYTES), "image/png")},
        )

        # Then
        assert response.status_code == 400
        assert response.json()["code"] == "FILE_TOO_LARGE"

    async def test_broken_worker_pool_returns_500_not_a_crash(self, app):
        # Given. Simulates get_process_pool() returning a pool whose initializer failed
        # at startup (see start_worker_pool's BrokenProcessPool handling in
        # ocr_service.py): the whole pool is broken, so a real request against it must
        # surface as a handled 500 through the global exception handler, not propagate
        # unhandled. raise_app_exceptions=False mirrors how a real ASGI server behaves:
        # it hands the already-generated response to the caller instead of re-raising
        # for local traceback visibility, which is httpx's own test-only default.
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as broken_pool_client:
            with patch("src.api.rest.rest_endpoints.get_process_pool", return_value=_BrokenExecutor()):
                response = await broken_pool_client.post(
                    "/v1/ocr",
                    files={"file": ("test.png", io.BytesIO(PNG_MAGIC_BYTES), "image/png")},
                )

        # Then
        assert response.status_code == 500
        assert response.json()["code"] == "INTERNAL_ERROR"

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
