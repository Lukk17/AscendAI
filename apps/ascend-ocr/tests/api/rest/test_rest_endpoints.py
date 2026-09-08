import io
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.exception_handlers import FileSizeExceededError, OcrProcessingError
from src.config.config import settings
from src.main import create_app
from tests.conftest import VALID_MULTI_PAGE_PDF_BYTES, VALID_PDF_BYTES, VALID_PNG_BYTES, OcrResponseFactory


@pytest.fixture
def app():
    # create_app() never touches the OCR worker pool at call time: it is only started
    # by the ASGI lifespan, which none of these tests drive. Every test below either
    # exercises a path that stops before the pool is touched (a refusal at the request
    # boundary) or patches dispatch_ocr_request directly.
    return create_app()


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
    @patch("src.main.is_accepting_work", return_value=True)
    @patch("src.main.is_engine_warm", return_value=False)
    async def test_ready_returns_not_ready_when_engine_cold(self, mock_is_warm, _mock_accepting, client):
        # When
        response = await client.get("/ready")

        # Then
        assert response.status_code == 200
        assert response.json()["status"] == "not-ready"
        assert response.json()["engine_warm"] is False
        mock_is_warm.assert_called_once_with(settings.DEFAULT_LANGUAGE)

    @patch("src.main.is_accepting_work", return_value=True)
    @patch("src.main.is_engine_warm", return_value=True)
    async def test_ready_returns_ready_when_engine_warm_and_accepting_work(self, mock_is_warm, mock_accepting, client):
        # When
        response = await client.get("/ready")

        # Then
        assert response.json()["status"] == "ready"
        assert response.json()["engine_warm"] is True
        assert response.json()["accepting_work"] is True
        mock_is_warm.assert_called_once_with(settings.DEFAULT_LANGUAGE)
        mock_accepting.assert_called_once()

    @patch("src.main.is_accepting_work", return_value=False)
    @patch("src.main.is_engine_warm", return_value=True)
    async def test_ready_returns_not_ready_when_engine_warm_but_not_accepting_work(
        self, _mock_is_warm, _mock_accepting, client
    ):
        # Given — engine warm but the worker is being replaced, the pool is broken, or
        # the in-flight job is past its budget: still not-ready, per Decision 6.
        # When
        response = await client.get("/ready")

        # Then
        assert response.json()["status"] == "not-ready"
        assert response.json()["accepting_work"] is False

    async def test_ready_reports_queue_depth(self, client):
        # Given
        with patch("src.main.get_queue_depth", return_value=3):
            # When
            response = await client.get("/ready")

        # Then
        assert response.json()["queue_depth"] == 3


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
        assert "ascendocr_ocr_requests_total" in body
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
    @patch("src.api.rest.rest_endpoints.dispatch_ocr_request")
    async def test_successful_ocr_json(self, mock_dispatch, client):
        # Given
        mock_dispatch.return_value = OcrResponseFactory.with_single_line()

        # When
        response = await client.post(
            "/v1/ocr",
            files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
            data={"lang": "en"},
        )

        # Then
        assert response.status_code == 200
        assert response.json()["filename"] == "test.png"
        assert response.json()["schema_version"] == "1"

    @patch("src.api.rest.rest_endpoints.dispatch_ocr_request")
    async def test_requested_language_form_field_reaches_dispatch(self, mock_dispatch, client):
        # Given — a language other than DEFAULT_LANGUAGE, sent as the documented
        # multipart form field, not as a query parameter
        mock_dispatch.return_value = OcrResponseFactory.with_single_line(language="pl")

        # When
        response = await client.post(
            "/v1/ocr",
            files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
            data={"lang": "pl"},
        )

        # Then
        assert response.status_code == 200
        assert mock_dispatch.call_args.args[2] == "pl"

    @patch("src.api.rest.rest_endpoints.dispatch_ocr_request")
    async def test_lang_query_parameter_is_ignored_in_favour_of_default(self, mock_dispatch, client):
        # Given — `lang` sent as a query parameter rather than a multipart form field.
        # FastAPI only binds a `Form()`-marked parameter from the request body, so this
        # must be silently dropped and DEFAULT_LANGUAGE used instead, proving the bug
        # (lang misclassified as a query parameter) cannot come back unnoticed.
        mock_dispatch.return_value = OcrResponseFactory.with_single_line()

        # When
        response = await client.post(
            "/v1/ocr?lang=pl",
            files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
        )

        # Then
        assert response.status_code == 200
        assert mock_dispatch.call_args.args[2] == settings.DEFAULT_LANGUAGE

    @patch("src.api.rest.rest_endpoints.inject_trace_context")
    @patch("src.api.rest.rest_endpoints.dispatch_ocr_request")
    async def test_trace_context_is_forwarded_to_worker(self, mock_dispatch, mock_inject, client):
        # Given — the carrier is captured from the auto-instrumented request span, so
        # the worker process can reattach its own span as that span's child
        mock_dispatch.return_value = OcrResponseFactory.with_single_line()
        mock_inject.return_value = {"traceparent": "00-fake-01"}

        # When
        response = await client.post(
            "/v1/ocr",
            files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
        )

        # Then
        assert response.status_code == 200
        mock_inject.assert_called_once()
        assert mock_dispatch.call_args.args[5] == {"traceparent": "00-fake-01"}

    @patch("src.api.rest.rest_endpoints.dispatch_ocr_request")
    async def test_pdf_accepted(self, mock_dispatch, client):
        # Given
        mock_dispatch.return_value = OcrResponseFactory.with_single_line(filename="doc.pdf")

        # When
        response = await client.post(
            "/v1/ocr",
            files={"file": ("doc.pdf", io.BytesIO(VALID_PDF_BYTES), "application/pdf")},
        )

        # Then
        assert response.status_code == 200

    @patch("src.api.rest.rest_endpoints.dispatch_ocr_request")
    async def test_ocr_service_failure_returns_422_with_generic_message(self, mock_dispatch, client):
        # Given
        mock_dispatch.side_effect = OcrProcessingError("engine internal trace")

        # When
        response = await client.post(
            "/v1/ocr",
            files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
        )

        # Then
        assert response.status_code == 422
        payload = response.json()
        assert payload["code"] == "OCR_FAILED"

    @patch("src.api.rest.rest_endpoints.dispatch_ocr_request")
    async def test_service_size_error_propagates_as_400(self, mock_dispatch, client):
        # Given. dispatch_ocr_request re-raises a size error surfaced by the worker
        # untouched, so the REST layer must too: 400 FILE_TOO_LARGE, not 422 OCR_FAILED.
        mock_dispatch.side_effect = FileSizeExceededError("page exceeds cap")

        # When
        response = await client.post(
            "/v1/ocr",
            files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
        )

        # Then
        assert response.status_code == 400
        assert response.json()["code"] == "FILE_TOO_LARGE"

    async def test_unexpected_dispatch_exception_returns_500_not_a_crash(self, app):
        # Given — dispatch_ocr_request wraps every expected failure mode itself; an
        # exception escaping it unwrapped must still surface as a handled 500 through
        # the global exception handler, not propagate and take the app down.
        # raise_app_exceptions=False mirrors how a real ASGI server behaves: it hands
        # the already-generated response to the caller instead of re-raising for local
        # traceback visibility, which is httpx's own test-only default.
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as unhandled_client:
            with patch("src.api.rest.rest_endpoints.dispatch_ocr_request") as mock_dispatch:
                mock_dispatch.side_effect = RuntimeError("unexpected bug")

                # When
                response = await unhandled_client.post(
                    "/v1/ocr",
                    files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
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

    async def test_oversized_file_returns_400(self, client, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 0)

        # When
        response = await client.post(
            "/v1/ocr",
            files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES * 200), "image/png")},
        )

        # Then
        assert response.status_code == 400
        assert response.json()["code"] == "FILE_TOO_LARGE"

    async def test_image_over_pixel_ceiling_refused_without_dispatch(self, client, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_MAX_INFERENCE_PIXELS", 50)

        # When
        with patch("src.api.rest.rest_endpoints.dispatch_ocr_request") as mock_dispatch:
            response = await client.post(
                "/v1/ocr",
                files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
            )

        # Then
        assert response.status_code == 400
        assert response.json()["code"] == "FILE_TOO_LARGE"
        mock_dispatch.assert_not_called()

    async def test_document_over_page_limit_refused_without_dispatch(self, client, monkeypatch):
        # Given — floor(1.0 / 1.0) == 1 page allowed, the fixture PDF has two
        monkeypatch.setattr(settings, "OCR_REQUEST_TIMEOUT", 1.0)
        monkeypatch.setattr(settings, "OCR_PAGE_TIMEOUT_SECONDS", 1.0)

        # When
        with patch("src.api.rest.rest_endpoints.dispatch_ocr_request") as mock_dispatch:
            response = await client.post(
                "/v1/ocr",
                files={"file": ("doc.pdf", io.BytesIO(VALID_MULTI_PAGE_PDF_BYTES), "application/pdf")},
            )

        # Then
        assert response.status_code == 400
        assert response.json()["code"] == "FILE_TOO_LARGE"
        mock_dispatch.assert_not_called()
