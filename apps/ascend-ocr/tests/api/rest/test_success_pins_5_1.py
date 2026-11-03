import io
import time
from collections.abc import AsyncIterator
from importlib.metadata import version as get_package_version
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from src.api.rest.rest_endpoints import limiter
from src.config.config import settings
from src.main import create_app
from src.model.ocr_models import JobResultLocation
from src.service.job_runner import JobRunner
from src.service.job_service import JobService
from src.service.job_store import JobStore, new_job_id
from tests.conftest import VALID_PNG_BYTES, FakeResultStore, make_record

JOBS_PATH = "/v1/ocr/jobs"


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> None:
    # given
    limiter.reset()


@pytest.fixture
def pin_store(jobs_dir: Path, results: FakeResultStore) -> JobStore:
    _ = jobs_dir

    return JobStore(results)


@pytest.fixture
def pin_runner(pin_store: JobStore, results: FakeResultStore) -> JobRunner:
    return JobRunner(pin_store, results)


@pytest.fixture
def pin_service(pin_store: JobStore, results: FakeResultStore, pin_runner: JobRunner) -> JobService:
    return JobService(pin_store, results, pin_runner)


@pytest.fixture
def pin_app(pin_service: JobService, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    # given
    monkeypatch.setattr("src.api.rest.rest_endpoints.job_service", pin_service)
    # when
    return create_app()


@pytest.fixture
async def pin_client(pin_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=pin_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def submit_png(client: AsyncClient, filename: str = "test.png") -> Response:
    return await client.post(
        JOBS_PATH,
        files={"file": (filename, io.BytesIO(VALID_PNG_BYTES), "image/png")},
    )


async def test_submit_pins_today_accepted_body(pin_client: AsyncClient) -> None:
    # given
    filename = "scan.png"
    # when
    response = await pin_client.post(
        JOBS_PATH,
        files={"file": (filename, io.BytesIO(VALID_PNG_BYTES), "image/png")},
    )
    # then
    assert response.status_code == 202
    payload = response.json()
    assert payload["state"] == "waiting"
    assert payload["page_count"] == 1
    assert response.headers["location"] == f"{JOBS_PATH}/{payload['job_id']}"


async def test_status_pins_today_waiting_body(pin_client: AsyncClient) -> None:
    # given
    job_id = (await submit_png(pin_client)).json()["job_id"]
    # when
    response = await pin_client.get(f"{JOBS_PATH}/{job_id}")
    # then
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "waiting"
    assert payload["queue_position"] == 0
    assert payload["result"] is None


async def test_list_pins_today_envelope(pin_client: AsyncClient) -> None:
    # given
    first = (await submit_png(pin_client, filename="first.png")).json()["job_id"]
    second = (await submit_png(pin_client, filename="second.png")).json()["job_id"]
    # when
    response = await pin_client.get(JOBS_PATH)
    # then
    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert [job["job_id"] for job in jobs] == [first, second]


async def test_cancel_pins_today_no_content(pin_client: AsyncClient, pin_store: JobStore) -> None:
    # given
    job_id = (await submit_png(pin_client)).json()["job_id"]
    # when
    response = await pin_client.delete(f"{JOBS_PATH}/{job_id}")
    # then
    assert response.status_code == 204
    assert response.content == b""
    assert pin_store.read(job_id).state == "cancelled"


async def test_failed_record_pins_today_code_and_reason(pin_client: AsyncClient, pin_store: JobStore) -> None:
    # given
    record = make_record(state="running", started_at=time.time())
    pin_store.write(record)
    pin_store.fail(record, "OCR_FAILED", "engine gave up")
    # when
    response = await pin_client.get(f"{JOBS_PATH}/{record.job_id}")
    # then
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "failed"
    assert payload["error_code"] == "OCR_FAILED"
    assert payload["error_reason"] == "engine gave up"


async def test_restarted_record_pins_today_retryable_reason(
    pin_client: AsyncClient, pin_store: JobStore
) -> None:
    # given
    record = make_record(state="running", started_at=time.time())
    pin_store.write(record)
    pin_store.fail(record, "SERVICE_RESTARTED", "process went away")
    # when
    response = await pin_client.get(f"{JOBS_PATH}/{record.job_id}")
    # then
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "failed"
    assert payload["error_code"] == "SERVICE_RESTARTED"


async def test_succeeded_record_pins_today_address(pin_client: AsyncClient, pin_store: JobStore) -> None:
    # given
    record = make_record(state="running", page_count=2, started_at=time.time())
    pin_store.write(record)
    pin_store.succeed(record, JobResultLocation(bucket="ocr-results", key=f"{record.job_id}.md"), 3.0)
    # when
    response = await pin_client.get(f"{JOBS_PATH}/{record.job_id}")
    # then
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "succeeded"
    assert payload["result"]["bucket"] == "ocr-results"


async def test_korean_submission_pins_today_code_body(pin_client: AsyncClient, pin_runner: JobRunner) -> None:
    # given
    lang = "korean"
    # when
    response = await pin_client.post(
        JOBS_PATH,
        files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
        data={"lang": lang},
    )
    # then
    assert response.status_code == 400
    assert "application/problem+json" in response.headers["content-type"]
    payload = response.json()
    assert payload["type"] == "https://ascend.ai/errors/unsupported-language"
    assert payload["title"] == "Bad Request"
    assert payload["status"] == 400
    assert payload["code"] == "UNSUPPORTED_LANGUAGE"
    assert payload["detail"] == (
        "Language is not supported. Supported languages: en, pl, de, fr, es, it, pt, nl, ch, japan"
    )
    assert payload["instance"] == JOBS_PATH
    assert "job_id" not in payload
    assert "location" not in response.headers
    assert pin_runner.documents_waiting() == 0


async def test_unknown_job_pins_today_code_body(pin_client: AsyncClient) -> None:
    # given
    job_id = new_job_id()
    # when
    response = await pin_client.get(f"{JOBS_PATH}/{job_id}")
    # then
    assert response.status_code == 404
    assert response.json()["code"] == "JOB_NOT_FOUND"


async def test_health_pins_today_status_and_version(pin_client: AsyncClient) -> None:
    # given
    path = "/health"
    # when
    response = await pin_client.get(path)
    # then
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"] == get_package_version("ascend-ocr")


async def test_ready_pins_today_always_200(pin_client: AsyncClient) -> None:
    # given
    cold = False
    # when
    with (
        patch("src.api.readiness.is_engine_warm", return_value=cold),
        patch("src.api.readiness.is_accepting_work", return_value=True),
    ):
        response = await pin_client.get("/ready")
    # then
    assert response.status_code == 503
    assert response.json()["status"] == "not-ready"


async def test_queue_full_pins_today_code_and_retry_after(
    pin_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "OCR_JOB_QUEUE_MAX_DOCUMENTS", 1)
    await submit_png(pin_client, filename="first.png")
    # when
    response = await submit_png(pin_client, filename="second.png")
    # then
    assert response.status_code == 503
    assert response.json()["code"] == "QUEUE_FULL"
    assert int(response.headers["retry-after"]) >= 1


async def test_unexpected_failure_pins_today_internal_code(pin_app: FastAPI) -> None:
    # given
    transport = ASGITransport(app=pin_app, raise_app_exceptions=False)
    # when
    async with AsyncClient(transport=transport, base_url="http://test") as unhandled_client:
        with patch(
            "src.api.rest.rest_endpoints.job_service.submit",
            AsyncMock(side_effect=RuntimeError("unexpected bug")),
        ):
            response = await unhandled_client.post(
                JOBS_PATH,
                files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
            )
    # then
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
