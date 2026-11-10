import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastmcp.exceptions import ToolError

from src.api.mcp import mcp_server as mcp_module
from src.api.mcp.mcp_server import mcp, ocr_cancel_job, ocr_job_status, ocr_list_jobs, ocr_submit
from src.service.job_runner import JobRunner
from src.service.job_service import JobService
from src.service.job_store import JobStore
from tests.conftest import VALID_PNG_BYTES, FakeResultStore, make_record


@pytest.fixture
def pin_store(jobs_dir: Path, results: FakeResultStore) -> JobStore:
    _ = jobs_dir

    return JobStore(results)


@pytest.fixture
def pin_runner(pin_store: JobStore, results: FakeResultStore) -> JobRunner:
    return JobRunner(pin_store, results)


@pytest.fixture(autouse=True)
def pin_service(
    pin_store: JobStore, results: FakeResultStore, pin_runner: JobRunner, monkeypatch: pytest.MonkeyPatch
) -> JobService:
    built = JobService(pin_store, results, pin_runner)
    monkeypatch.setattr(mcp_module, "job_service", built)
    monkeypatch.setattr(mcp_module, "_fetch_file", AsyncMock(return_value=(VALID_PNG_BYTES, "scan.png")))

    return built


async def test_mcp_submit_pins_today_identifier_body() -> None:
    # given
    file_uri = "https://files.example/scan.png"
    # when
    result = await ocr_submit(file_uri=file_uri)
    # then
    assert result["state"] == "waiting"
    assert isinstance(result["job_id"], str)
    assert len(result["job_id"]) > 0


async def test_mcp_status_pins_today_waiting_body() -> None:
    # given
    submitted = await ocr_submit(file_uri="https://files.example/a.png")
    job_id = str(submitted["job_id"])
    # when
    result = ocr_job_status(job_id=job_id)
    # then
    assert result["state"] == "waiting"
    assert result["job_id"] == job_id


async def test_mcp_list_pins_today_envelope() -> None:
    # given
    first = str((await ocr_submit(file_uri="https://files.example/first.png"))["job_id"])
    second = str((await ocr_submit(file_uri="https://files.example/second.png"))["job_id"])
    # when
    result = ocr_list_jobs()
    # then
    jobs = result["jobs"]
    assert isinstance(jobs, list)
    assert [job["job_id"] for job in jobs] == [first, second]


async def test_mcp_cancel_pins_today_acceptance(pin_store: JobStore) -> None:
    # given
    job_id = str((await ocr_submit(file_uri="https://files.example/drop.png"))["job_id"])
    # when
    result = await ocr_cancel_job(job_id=job_id)
    # then
    assert result == {"job_id": job_id, "cancelled": True}
    assert pin_store.read(job_id).state == "cancelled"


async def test_mcp_failed_record_pins_today_code_and_reason(pin_store: JobStore) -> None:
    # given
    record = make_record(state="running", started_at=time.time())
    pin_store.write(record)
    pin_store.fail(record, "RESULT_STORE_UNAVAILABLE", "bucket is down")
    # when
    result = ocr_job_status(job_id=record.job_id)
    # then
    assert result["state"] == "failed"
    assert result["error_code"] == "RESULT_STORE_UNAVAILABLE"
    assert result["error_reason"] == "bucket is down"


async def test_mcp_unsupported_language_pins_today_tool_error() -> None:
    # given
    lang = "korean"
    # when
    with pytest.raises(ToolError, match=r"^UNSUPPORTED_LANGUAGE: ") as exc_info:
        await mcp.call_tool("ocr_submit", {"file_uri": "https://files.example/scan.png", "lang": lang})
    # then
    assert str(exc_info.value).startswith("UNSUPPORTED_LANGUAGE: ")


async def test_mcp_unknown_job_pins_today_tool_error() -> None:
    # given
    job_id = "00000000-0000-4000-8000-000000000000"
    # when
    with pytest.raises(ToolError, match=r"^JOB_NOT_FOUND: ") as exc_info:
        await mcp.call_tool("ocr_job_status", {"job_id": job_id})
    # then
    assert str(exc_info.value).startswith("JOB_NOT_FOUND: ")
