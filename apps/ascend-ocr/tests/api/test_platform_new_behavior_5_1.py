import io
import re
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.rest.rest_endpoints import limiter
from src.config.config import settings
from src.main import create_app
from src.service.job_runner import JobRunner
from src.service.job_service import JobService
from src.service.job_store import JobStore, new_job_id
from tests.conftest import VALID_PNG_BYTES, FakeResultStore

JOBS_PATH = "/v1/ocr/jobs"
TRACE_ID_PATTERN = r"[0-9a-f]{32}"


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> None:
    # given
    limiter.reset()


@pytest.fixture
def fresh_store(jobs_dir: Path, results: FakeResultStore) -> JobStore:
    _ = jobs_dir

    return JobStore(results)


@pytest.fixture
def fresh_runner(fresh_store: JobStore, results: FakeResultStore) -> JobRunner:
    return JobRunner(fresh_store, results)


@pytest.fixture
def fresh_service(fresh_store: JobStore, results: FakeResultStore, fresh_runner: JobRunner) -> JobService:
    return JobService(fresh_store, results, fresh_runner)


@pytest.fixture
def fresh_app(fresh_service: JobService, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    # given
    monkeypatch.setattr("src.api.rest.rest_endpoints.job_service", fresh_service)
    # when
    return create_app()


@pytest.fixture
async def fresh_client(fresh_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=fresh_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_refusal_problem_body_carries_type_and_trace_id(fresh_client: AsyncClient) -> None:
    # given
    job_id = new_job_id()
    # when
    response = await fresh_client.get(f"{JOBS_PATH}/{job_id}")
    # then
    assert response.status_code == 404
    assert "application/problem+json" in response.headers["content-type"]
    body = response.json()
    assert body["code"] == "JOB_NOT_FOUND"
    assert body["type"] == "https://ascend.ai/errors/job-not-found"
    assert body["title"] == "Not Found"
    assert body["status"] == 404
    assert body["instance"] == f"{JOBS_PATH}/{job_id}"
    assert re.fullmatch(TRACE_ID_PATTERN, body["traceId"]) is not None


async def test_queue_full_problem_body_carries_type_and_retry_after(
    fresh_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "OCR_JOB_QUEUE_MAX_DOCUMENTS", 1)
    await fresh_client.post(
        JOBS_PATH,
        files={"file": ("first.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
    )
    # when
    response = await fresh_client.post(
        JOBS_PATH,
        files={"file": ("second.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
    )
    # then
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "QUEUE_FULL"
    assert body["type"] == "https://ascend.ai/errors/queue-full"
    assert re.fullmatch(TRACE_ID_PATTERN, body["traceId"]) is not None
    assert int(response.headers["retry-after"]) >= 1


async def test_request_validation_failure_answers_400_with_sorted_errors(
    fresh_client: AsyncClient,
) -> None:
    # given
    path = JOBS_PATH
    # when
    response = await fresh_client.post(path)
    # then
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation"
    assert isinstance(body["errors"], list)
    assert len(body["errors"]) > 0
    fields = [entry["field"] for entry in body["errors"]]
    assert fields == sorted(fields)
    assert all("message" in entry for entry in body["errors"])


async def test_unknown_path_answers_problem_404_with_trace_id(fresh_client: AsyncClient) -> None:
    # given
    path = "/does-not-exist"
    # when
    response = await fresh_client.get(path)
    # then
    assert response.status_code == 404
    assert "application/problem+json" in response.headers["content-type"]
    body = response.json()
    assert body["code"] == "not_found"
    assert body["type"] == "https://ascend.ai/errors/not-found"
    assert re.fullmatch(TRACE_ID_PATTERN, body["traceId"]) is not None


async def test_wrong_method_answers_problem_405_with_allow(fresh_client: AsyncClient) -> None:
    # given
    path = "/health"
    # when
    response = await fresh_client.delete(path)
    # then
    assert response.status_code == 405
    body = response.json()
    assert body["code"] == "method_not_allowed"
    assert "allow" in {key.lower() for key in response.headers}


async def test_ready_not_ready_answers_503_with_checks(fresh_client: AsyncClient) -> None:
    # given
    cold = False
    # when
    with (
        patch("src.api.readiness.is_engine_warm", return_value=cold),
        patch("src.api.readiness.is_accepting_work", return_value=True),
    ):
        response = await fresh_client.get("/ready")
    # then
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not-ready"
    assert body["service"] == "ascend-ocr"
    assert isinstance(body["version"], str)
    assert isinstance(body["checks"], dict)


async def test_health_includes_service_and_version(fresh_client: AsyncClient) -> None:
    # given
    path = "/health"
    # when
    response = await fresh_client.get(path)
    # then
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "ascend-ocr"
    assert isinstance(body["version"], str)
    assert len(body["version"]) > 0


async def test_submission_after_limit_answers_429_problem_body(
    fresh_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "OCR_JOB_QUEUE_MAX_DOCUMENTS", 1000)
    allowed = int(settings.RATE_LIMIT_OCR.split("/")[0])
    # when
    statuses: list[int] = []
    for index in range(allowed):
        response = await fresh_client.post(
            JOBS_PATH,
            files={"file": (f"scan-{index}.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
        )
        statuses.append(response.status_code)
    refused = await fresh_client.post(
        JOBS_PATH,
        files={"file": ("one-too-many.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
    )
    # then
    assert set(statuses) == {202}
    assert refused.status_code == 429
    assert refused.json()["code"] == "rate_limited"
    assert "retry-after" in {key.lower() for key in refused.headers}


async def test_mcp_submit_after_limit_fails_with_rate_limited() -> None:
    # given
    from ascend_python_common.rate_limit import McpRateLimitMiddleware, build_limiter

    middleware = McpRateLimitMiddleware(build_limiter("2/minute"), "2/minute", {"ocr_submit": "2/minute"})
    context = SimpleNamespace(
        message=SimpleNamespace(name="ocr_submit"),
        fastmcp_context=None,
    )

    async def call_next(_context: Any) -> dict[str, str]:
        return {"status": "success"}

    for _ in range(2):
        # when
        result = await middleware.on_call_tool(context, call_next)  # type: ignore[arg-type]
        # then
        assert result == {"status": "success"}
    # when
    with pytest.raises(Exception, match=r"^rate_limited: ") as exc_info:
        await middleware.on_call_tool(context, call_next)  # type: ignore[arg-type]
    # then
    assert str(exc_info.value).startswith("rate_limited: ")
