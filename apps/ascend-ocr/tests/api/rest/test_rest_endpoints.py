import asyncio
import io
import time
from importlib.metadata import version as get_package_version
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from src.api.exception_handlers import OcrProcessingError
from src.api.middleware.rate_limit import limiter
from src.config.config import settings
from src.main import create_app
from src.model.ocr_models import JobResultLocation, JobState
from src.observability.metrics import OCR_REQUESTS_TOTAL
from src.service.job_runner import JobRunner
from src.service.job_service import JobService
from src.service.job_store import JobStore, new_job_id
from src.service.ocr_service import wait_for_worker_replacements
from tests.conftest import (
    VALID_MULTI_PAGE_PDF_BYTES,
    VALID_PDF_BYTES,
    VALID_PNG_BYTES,
    FakeResultStore,
    OcrResponseFactory,
    make_record,
    write_finished_record,
)

JOBS_PATH = "/v1/ocr/jobs"


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Every test starts with a full budget, so one module's traffic cannot throttle another's."""
    limiter.reset()


@pytest.fixture
def store(jobs_dir: Path, results: FakeResultStore) -> JobStore:
    _ = jobs_dir

    return JobStore(results)


@pytest.fixture
def runner(store: JobStore, results: FakeResultStore) -> JobRunner:
    return JobRunner(store, results)


@pytest.fixture
def service(store: JobStore, results: FakeResultStore, runner: JobRunner) -> JobService:
    return JobService(store, results, runner)


@pytest.fixture
def app(service: JobService, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    # create_app() never touches the OCR worker pool at call time: it is only started by
    # the ASGI lifespan, which none of these tests drive. The job service is swapped for
    # one over this test's own directory and a fake bucket, so the real behaviour runs
    # without a real store behind it.
    monkeypatch.setattr("src.api.rest.rest_endpoints.job_service", service)

    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def submit_png(client: AsyncClient, filename: str = "test.png", lang: str | None = "en") -> Response:
    return await client.post(
        JOBS_PATH,
        files={"file": (filename, io.BytesIO(VALID_PNG_BYTES), "image/png")},
        data={} if lang is None else {"lang": lang},
    )


class TestHealthEndpoint:
    async def test_health_returns_ok(self, client):
        # When
        response = await client.get("/health")

        # Then
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == get_package_version("ascend-ocr")


class TestOpenApiDocument:
    async def test_openapi_reports_the_same_version_as_health(self, client):
        # When
        health = await client.get("/health")
        openapi = await client.get("/openapi.json")

        # Then
        assert openapi.status_code == 200
        assert openapi.json()["info"]["version"] == health.json()["version"]


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
        # Given - engine warm but the worker is being replaced, the pool is broken, or
        # the in-flight job is past its budget: still not-ready, per ADR-004.
        # When
        response = await client.get("/ready")

        # Then
        assert response.json()["status"] == "not-ready"
        assert response.json()["accepting_work"] is False

    async def test_ready_reports_the_queue_only_through_the_job_counters(self, client):
        # When
        response = await client.get("/ready")

        # Then
        assert set(response.json()) == {
            "status",
            "version",
            "engine_warm",
            "accepting_work",
            "jobs_queued",
            "jobs_running",
        }

    @patch("src.main.is_accepting_work", return_value=True)
    @patch("src.main.is_engine_warm", return_value=True)
    async def test_ready_reports_work_waiting_and_running_and_stays_ready(
        self, _mock_is_warm: MagicMock, _mock_accepting: MagicMock, client: AsyncClient, runner: JobRunner
    ) -> None:
        # Given - one document being read and two waiting
        for _ in range(3):
            runner.admit(make_record(page_count=1))

        runner._running = runner._queue.popleft()
        with patch("src.main.job_runner", runner):
            # When
            response = await client.get("/ready")

        # Then - busy is still ready, because the waiting work will be served
        payload = response.json()
        assert payload["jobs_running"] == 1
        assert payload["jobs_queued"] == 2
        assert payload["status"] == "ready"

    async def test_ready_reports_nothing_in_flight_on_an_idle_service(
        self, client: AsyncClient, runner: JobRunner
    ) -> None:
        # Given
        with patch("src.main.job_runner", runner):
            # When
            response = await client.get("/ready")

        # Then
        assert response.json()["jobs_queued"] == 0
        assert response.json()["jobs_running"] == 0


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


class TestRemovedSynchronousPath:
    async def test_the_old_synchronous_path_answers_not_found_like_any_unknown_path(self, client):
        # When
        response = await client.post(
            "/v1/ocr",
            files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
        )

        # Then
        assert response.status_code == 404


class TestSubmitJob:
    async def test_submission_is_accepted_with_an_identifier_and_a_relative_location(self, client):
        # When
        response = await submit_png(client)

        # Then
        assert response.status_code == 202
        payload = response.json()
        assert payload["state"] == "waiting"
        assert payload["page_count"] == 1
        assert response.headers["location"] == f"{JOBS_PATH}/{payload['job_id']}"
        assert payload["status_url"] == f"{JOBS_PATH}/{payload['job_id']}"
        assert payload["poll_after_seconds"] >= 1.0

    async def test_the_submission_answer_carries_no_page_content(self, client):
        # When
        response = await submit_png(client)

        # Then
        assert "pages" not in response.json()
        assert "lines" not in response.text

    async def test_the_requested_language_is_recorded(self, client: AsyncClient, store: JobStore) -> None:
        # When
        response = await client.post(
            JOBS_PATH,
            files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
            data={"lang": "pl"},
        )

        # Then
        assert store.read(response.json()["job_id"]).language == "pl"

    async def test_a_lang_query_parameter_is_ignored_in_favour_of_the_default(
        self, client: AsyncClient, store: JobStore
    ) -> None:
        # When - `lang` sent as a query parameter rather than a multipart form field.
        # FastAPI only binds a `Form()`-marked parameter from the request body, so this
        # must be silently dropped and DEFAULT_LANGUAGE used instead.
        response = await client.post(
            f"{JOBS_PATH}?lang=pl",
            files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
        )

        # Then
        assert store.read(response.json()["job_id"]).language == settings.DEFAULT_LANGUAGE

    async def test_the_requested_quality_mode_is_recorded(self, client: AsyncClient, store: JobStore) -> None:
        # When
        response = await client.post(
            JOBS_PATH,
            files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
            data={"quality": "normal"},
        )

        # Then
        assert response.status_code == 202
        assert store.read(response.json()["job_id"]).quality == "normal"

    async def test_an_omitted_quality_mode_is_high(self, client: AsyncClient, store: JobStore) -> None:
        # When
        response = await client.post(
            JOBS_PATH,
            files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
        )

        # Then
        assert store.read(response.json()["job_id"]).quality == "high"

    async def test_an_unknown_quality_mode_is_refused_and_nothing_is_queued(
        self, client: AsyncClient, runner: JobRunner
    ) -> None:
        # When
        response = await client.post(
            JOBS_PATH,
            files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
            data={"quality": "ultra"},
        )

        # Then
        assert response.status_code == 422
        assert runner.documents_waiting() == 0

    async def test_a_straighten_request_is_recorded(self, client: AsyncClient, store: JobStore) -> None:
        # When
        response = await client.post(
            JOBS_PATH,
            files={"file": ("photo.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
            data={"straighten": "true"},
        )

        # Then
        assert response.status_code == 202
        assert store.read(response.json()["job_id"]).straighten is True

    async def test_an_omitted_straighten_field_leaves_the_page_unwarped(
        self, client: AsyncClient, store: JobStore
    ) -> None:
        # When
        response = await client.post(
            JOBS_PATH,
            files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
        )

        # Then
        assert store.read(response.json()["job_id"]).straighten is False

    async def test_a_straighten_value_that_is_not_a_boolean_is_refused_and_nothing_is_queued(
        self, client: AsyncClient, runner: JobRunner
    ) -> None:
        # When
        response = await client.post(
            JOBS_PATH,
            files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
            data={"straighten": "sometimes"},
        )

        # Then
        assert response.status_code == 422
        assert runner.documents_waiting() == 0

    async def test_a_pdf_is_accepted(self, client):
        # When
        response = await client.post(
            JOBS_PATH,
            files={"file": ("doc.pdf", io.BytesIO(VALID_PDF_BYTES), "application/pdf")},
        )

        # Then
        assert response.status_code == 202

    async def test_a_submission_with_no_file_is_rejected(self, client):
        # When
        response = await client.post(JOBS_PATH)

        # Then
        assert response.status_code == 422

    @pytest.mark.parametrize("language", ["korean", "ru"])
    async def test_a_language_the_service_does_not_read_is_refused_with_no_identifier(
        self, client: AsyncClient, runner: JobRunner, language: str
    ) -> None:
        # When
        response = await submit_png(client, lang=language)

        # Then
        assert response.status_code == 400
        assert response.json() == {
            "code": "UNSUPPORTED_LANGUAGE",
            "detail": "Language is not supported. Supported languages: en, pl, de, fr, es, it, pt, nl, ch, japan",
        }
        assert "location" not in response.headers
        assert runner.documents_waiting() == 0

    async def test_a_refused_language_is_counted_under_one_fixed_label(self, client):
        # Given
        before = OCR_REQUESTS_TOTAL.labels(surface="rest", language="unsupported")._value.get()

        # When
        await submit_png(client, lang="zzqrst")

        # Then
        assert OCR_REQUESTS_TOTAL.labels(surface="rest", language="unsupported")._value.get() == before + 1
        labels = {sample.labels["language"] for metric in OCR_REQUESTS_TOTAL.collect() for sample in metric.samples}
        assert "zzqrst" not in labels

    async def test_a_file_the_service_cannot_read_is_refused(self, client):
        # When
        response = await client.post(
            JOBS_PATH,
            files={"file": ("test.txt", io.BytesIO(b"plain text"), "text/plain")},
        )

        # Then
        assert response.status_code == 400
        assert response.json()["code"] == "UNSUPPORTED_FILE_TYPE"

    async def test_an_oversized_file_is_refused(self, client, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 0)

        # When
        response = await client.post(
            JOBS_PATH,
            files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES * 200), "image/png")},
        )

        # Then
        assert response.status_code == 400
        assert response.json()["code"] == "FILE_TOO_LARGE"

    async def test_a_document_over_the_page_ceiling_is_refused(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch, runner: JobRunner
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "OCR_JOB_MAX_PAGES", 1)

        # When
        response = await client.post(
            JOBS_PATH,
            files={"file": ("doc.pdf", io.BytesIO(VALID_MULTI_PAGE_PDF_BYTES), "application/pdf")},
        )

        # Then
        assert response.status_code == 400
        assert response.json()["code"] == "FILE_TOO_LARGE"
        assert runner.documents_waiting() == 0

    async def test_a_full_queue_answers_service_unavailable_with_a_retry_hint(self, client, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_JOB_QUEUE_MAX_DOCUMENTS", 1)
        await submit_png(client, filename="first.png")

        # When
        response = await submit_png(client, filename="second.png")

        # Then
        assert response.status_code == 503
        assert response.json()["code"] == "QUEUE_FULL"
        assert int(response.headers["retry-after"]) >= 1

    async def test_an_unexpected_failure_surfaces_as_a_handled_internal_error(self, app):
        # Given - every expected failure is mapped by the service layer; anything else
        # must still reach the global handler rather than taking the app down.
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as unhandled_client:
            with patch(
                "src.api.rest.rest_endpoints.job_service.submit",
                AsyncMock(side_effect=RuntimeError("unexpected bug")),
            ):
                # When
                response = await submit_png(unhandled_client)

        # Then
        assert response.status_code == 500
        assert response.json()["code"] == "INTERNAL_ERROR"


class TestReadJob:
    async def test_reading_waiting_work_reports_its_place_and_its_hint(self, client):
        # Given
        job_id = (await submit_png(client)).json()["job_id"]

        # When
        response = await client.get(f"{JOBS_PATH}/{job_id}")

        # Then
        assert response.status_code == 200
        payload = response.json()
        assert payload["state"] == "waiting"
        assert payload["queue_position"] == 0
        assert payload["pages_done"] == 0
        assert payload["poll_after_seconds"] >= 1.0
        assert payload["result"] is None

    async def test_reading_successful_work_carries_the_address_and_no_hint(
        self, client: AsyncClient, store: JobStore, results: FakeResultStore
    ) -> None:
        # Given
        record = make_record(state="running", page_count=2, started_at=time.time())
        store.write(record)
        store.succeed(record, JobResultLocation(bucket="ocr-results", key=f"{record.job_id}.md"), 3.0)

        # When
        response = await client.get(f"{JOBS_PATH}/{record.job_id}")

        # Then
        payload = response.json()
        assert payload["state"] == "succeeded"
        assert "poll_after_seconds" not in payload
        assert payload["result"]["bucket"] == "ocr-results"
        assert payload["result"]["key"] == f"{record.job_id}.md"
        assert payload["result"]["url"].startswith("http")
        assert payload["result"]["page_count"] == 2
        assert results.signed[-1][0] == f"{record.job_id}.md"

    async def test_reading_a_failed_record_carries_its_code_and_reason(
        self, client: AsyncClient, store: JobStore
    ) -> None:
        # Given
        record = make_record(state="running", started_at=time.time())
        store.write(record)
        store.fail(record, "OCR_FAILED", "engine gave up")

        # When
        response = await client.get(f"{JOBS_PATH}/{record.job_id}")

        # Then
        payload = response.json()
        assert payload["state"] == "failed"
        assert payload["error_code"] == "OCR_FAILED"
        assert payload["error_reason"] == "engine gave up"
        assert payload["result"] is None

    @pytest.mark.parametrize("state", ["succeeded", "failed", "cancelled"])
    async def test_a_terminal_record_carries_no_hint_key_at_all(
        self, client: AsyncClient, store: JobStore, state: JobState
    ) -> None:
        # Given
        record = write_finished_record(store, state)

        # When
        response = await client.get(f"{JOBS_PATH}/{record.job_id}")

        # Then
        payload = response.json()
        assert payload["state"] == state
        assert "poll_after_seconds" not in payload
        assert payload["queue_position"] is None
        assert payload["pages_ahead"] is None

    async def test_a_running_record_carries_a_hint(self, client: AsyncClient, store: JobStore) -> None:
        # Given
        record = make_record(state="running", started_at=time.time())
        store.write(record)

        # When
        response = await client.get(f"{JOBS_PATH}/{record.job_id}")

        # Then
        payload = response.json()
        assert payload["state"] == "running"
        assert payload["poll_after_seconds"] >= 1.0
        assert payload["queue_position"] is None
        assert payload["pages_ahead"] is None

    async def test_reading_an_unknown_identifier_is_not_found(self, client):
        # When
        response = await client.get(f"{JOBS_PATH}/{new_job_id()}")

        # Then
        assert response.status_code == 404
        payload = response.json()
        assert payload["code"] == "JOB_NOT_FOUND"
        assert "unknown or expired" in payload["detail"]

    # "%2e%2e" is a traversal attempt that survives URL normalisation as one path
    # segment, so it reaches the identifier validator rather than being rewritten by the
    # client into a different URL.
    @pytest.mark.parametrize("candidate", ["not-an-identifier", "%2e%2e", "x" * 200, "job..id"])
    async def test_an_identifier_that_is_not_shaped_like_one_is_not_found(self, client, candidate):
        # When
        response = await client.get(f"{JOBS_PATH}/{candidate}")

        # Then
        assert response.status_code == 404
        assert response.json()["code"] == "JOB_NOT_FOUND"


class TestListJobs:
    async def test_an_idle_service_lists_nothing(self, client):
        # When
        response = await client.get(JOBS_PATH)

        # Then
        assert response.status_code == 200
        assert response.json() == {"jobs": []}

    async def test_everything_in_flight_is_listed_with_its_position(
        self, client: AsyncClient, runner: JobRunner
    ) -> None:
        # Given
        first = (await submit_png(client, filename="first.png")).json()["job_id"]
        second = (await submit_png(client, filename="second.png")).json()["job_id"]
        runner._running = runner._queue.popleft()

        # When
        response = await client.get(JOBS_PATH)

        # Then
        jobs = response.json()["jobs"]
        assert [job["job_id"] for job in jobs] == [first, second]
        assert [job["state"] for job in jobs] == ["running", "waiting"]
        assert [job["queue_position"] for job in jobs] == [None, 1]
        assert jobs[0]["elapsed_seconds"] >= 0.0

    async def test_finished_work_is_not_listed(self, client: AsyncClient, store: JobStore) -> None:
        # Given
        record = make_record(state="succeeded", finished_at=time.time())
        store.write(record)

        # When
        response = await client.get(JOBS_PATH)

        # Then
        assert response.json()["jobs"] == []


class TestDeleteJob:
    async def test_deleting_waiting_work_answers_no_content_and_cancels_it(
        self, client: AsyncClient, store: JobStore
    ) -> None:
        # Given
        job_id = (await submit_png(client)).json()["job_id"]

        # When
        response = await client.delete(f"{JOBS_PATH}/{job_id}")

        # Then
        assert response.status_code == 204
        assert response.content == b""
        assert store.read(job_id).state == "cancelled"

    async def test_deleting_finished_work_forgets_it(
        self, client: AsyncClient, store: JobStore, results: FakeResultStore
    ) -> None:
        # Given
        record = make_record(state="succeeded", finished_at=time.time())
        record.result = JobResultLocation(bucket="ocr-results", key=f"{record.job_id}.md")
        store.write(record)

        # When
        response = await client.delete(f"{JOBS_PATH}/{record.job_id}")

        # Then
        assert response.status_code == 204
        assert results.deleted == [f"{record.job_id}.md"]
        assert (await client.get(f"{JOBS_PATH}/{record.job_id}")).status_code == 404

    async def test_deleting_an_unknown_identifier_is_not_found(self, client):
        # When
        response = await client.delete(f"{JOBS_PATH}/{new_job_id()}")

        # Then
        assert response.status_code == 404
        assert response.json()["code"] == "JOB_NOT_FOUND"

    async def test_a_cancel_that_reaches_the_worker_replaces_it(
        self, client: AsyncClient, store: JobStore, runner: JobRunner
    ) -> None:
        # Given - a document already being read
        job_id = (await submit_png(client)).json()["job_id"]
        runner._running = runner._queue.popleft()
        runner._dispatched_job_id = job_id
        record = store.read(job_id)
        record.state = "running"
        record.started_at = time.time()
        store.write(record)
        replace = AsyncMock()

        # When
        with patch("src.service.ocr_service.replace_worker_for_cancel", replace):
            response = await client.delete(f"{JOBS_PATH}/{job_id}")
            await wait_for_worker_replacements()

        # Then
        assert response.status_code == 204
        replace.assert_awaited_once()
        assert store.read(job_id).state == "cancelled"

    async def test_a_cancel_answers_without_waiting_for_the_worker_to_be_replaced(
        self, client: AsyncClient, store: JobStore, runner: JobRunner
    ) -> None:
        # Given: a document already being read, and a replacement that takes as long as a warm-up
        job_id = (await submit_png(client)).json()["job_id"]
        runner._running = runner._queue.popleft()
        runner._dispatched_job_id = job_id
        record = store.read(job_id)
        record.state = "running"
        record.started_at = time.time()
        store.write(record)
        replacement_may_finish = asyncio.Event()

        async def slow_replacement() -> None:
            await replacement_may_finish.wait()

        with patch("src.service.ocr_service.replace_worker_for_cancel", slow_replacement):
            # When
            response = await asyncio.wait_for(client.delete(f"{JOBS_PATH}/{job_id}"), timeout=2.0)
            during = (await client.get("/ready")).json()
            status_during = (await client.get(f"{JOBS_PATH}/{job_id}")).json()["state"]
            replacement_may_finish.set()
            await wait_for_worker_replacements()
            after = (await client.get("/ready")).json()

        # Then: cancelled at once, not-ready while the worker is replaced, accepting again after
        assert response.status_code == 204
        assert status_during == "cancelled"
        assert during["accepting_work"] is False
        assert after["accepting_work"] is True


class TestRateLimits:
    async def test_submission_is_throttled_at_the_ocr_limit(self, client, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_JOB_QUEUE_MAX_DOCUMENTS", 1000)
        allowed = int(settings.RATE_LIMIT_OCR.split("/")[0])

        # When
        statuses = [(await submit_png(client, filename=f"scan-{index}.png")).status_code for index in range(allowed)]
        over_the_limit = await submit_png(client, filename="one-too-many.png")

        # Then
        assert set(statuses) == {202}
        assert over_the_limit.status_code == 429

    async def test_reading_and_listing_are_throttled_at_the_default_limit(self, client):
        # Given - more reads than the OCR limit allows, which must not throttle them
        job_id = (await submit_png(client)).json()["job_id"]
        ocr_limit = int(settings.RATE_LIMIT_OCR.split("/")[0])

        # When
        reads = [(await client.get(f"{JOBS_PATH}/{job_id}")).status_code for _ in range(ocr_limit + 1)]
        lists = [(await client.get(JOBS_PATH)).status_code for _ in range(ocr_limit + 1)]

        # Then
        assert set(reads) == {200}
        assert set(lists) == {200}


class TestFailurePropagation:
    async def test_a_reading_failure_recorded_against_a_job_is_read_back_as_a_successful_status(
        self, client: AsyncClient, store: JobStore
    ) -> None:
        # Given - a failure of the reading is a successful read of a record that failed
        record = make_record(state="running", started_at=time.time())
        store.write(record)
        store.fail(record, "OCR_FAILED", str(OcrProcessingError("engine internal trace")))

        # When
        response = await client.get(f"{JOBS_PATH}/{record.job_id}")

        # Then
        assert response.status_code == 200
        assert response.json()["state"] == "failed"


class TestTheWholePathThroughTheRunningService:
    async def test_submit_poll_collect_delete_over_http_with_the_runner_running(
        self, client: AsyncClient, store: JobStore, runner: JobRunner, results: FakeResultStore
    ) -> None:
        # Given - the real runner, driven by the real service, behind the real endpoints
        with patch(
            "src.service.job_runner.dispatch_ocr_request",
            AsyncMock(return_value=OcrResponseFactory.with_single_line(text="canary text")),
        ):
            await runner.start()
            try:
                # When - submit
                submitted = await submit_png(client)
                job_id = submitted.json()["job_id"]

                # When - poll until terminal, the way a caller does
                final = None
                for _ in range(500):
                    body = (await client.get(f"{JOBS_PATH}/{job_id}")).json()
                    if body["state"] in {"succeeded", "failed", "cancelled"}:
                        final = body

                        break

                    assert body["poll_after_seconds"] >= 1.0
                    await asyncio.sleep(0.01)
            finally:
                await runner.stop()

        # Then - the work succeeded and the address points at the object the store holds
        assert submitted.status_code == 202
        assert final is not None
        assert final["state"] == "succeeded"
        assert "poll_after_seconds" not in final
        assert final["pages_done"] == 1
        assert results.objects[final["result"]["key"]] == "## Page 1\ncanary text\n"
        assert final["result"]["bucket"] == results.bucket

        # And the listing no longer mentions it, while the record is still readable
        assert (await client.get(JOBS_PATH)).json() == {"jobs": []}
        assert (await client.get(f"{JOBS_PATH}/{job_id}")).json()["state"] == "succeeded"

        # And deleting it removes the object and the record together
        assert (await client.delete(f"{JOBS_PATH}/{job_id}")).status_code == 204
        assert results.objects == {}
        assert (await client.get(f"{JOBS_PATH}/{job_id}")).status_code == 404
