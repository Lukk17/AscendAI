import io
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastmcp.exceptions import ToolError
from fastmcp.tools.tool import ToolResult
from httpx import ASGITransport, AsyncClient, Response

from src.api.mcp.mcp_server import mcp
from src.config.config import Settings
from src.config.config import settings as service_settings
from src.main import create_app
from src.service.job_runner import JobRunner
from src.service.job_service import JobService
from src.service.job_store import JobStore
from tests.conftest import VALID_PNG_BYTES, FakeResultStore

JOBS_PATH = "/v1/ocr/jobs"


def test_rate_limit_defaults_are_600_and_60_per_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.delenv("RATE_LIMIT_DEFAULT", raising=False)
    monkeypatch.delenv("RATE_LIMIT_OCR", raising=False)
    # when
    fresh = Settings()
    # then
    assert fresh.RATE_LIMIT_DEFAULT == "600/minute"
    assert fresh.RATE_LIMIT_OCR == "60/minute"


@pytest.fixture
def runner(jobs_dir: Path, results: FakeResultStore) -> JobRunner:
    _ = jobs_dir

    return JobRunner(JobStore(results), results)


@pytest.fixture
def service(runner: JobRunner, results: FakeResultStore, monkeypatch: pytest.MonkeyPatch) -> JobService:
    """One service behind both surfaces, so both draw from the same budget."""
    built = JobService(runner._store, results, runner)
    monkeypatch.setattr("src.api.rest.rest_endpoints.job_service", built)
    monkeypatch.setattr("src.api.mcp.mcp_server.job_service", built)

    return built


@pytest.fixture
def jail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(service_settings, "MCP_FILE_URI_ROOT", str(tmp_path))

    return tmp_path


@pytest.fixture
def limited_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    # given - a budget of two submissions shared by both surfaces
    monkeypatch.setattr(service_settings, "RATE_LIMIT_DEFAULT", "10/minute")
    monkeypatch.setattr(service_settings, "RATE_LIMIT_OCR", "2/minute")
    monkeypatch.setattr(service_settings, "REDIS_URL", "memory://")
    # when
    return create_app()


@pytest.fixture
async def rest_client(limited_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=limited_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _submit_rest(rest_client: AsyncClient, filename: str) -> Response:
    return await rest_client.post(
        JOBS_PATH,
        files={"file": (filename, io.BytesIO(VALID_PNG_BYTES), "image/png")},
    )


async def _submit_mcp(source_uri: str) -> ToolResult:
    result = await mcp.call_tool("ocr_submit", {"file_uri": source_uri, "lang": "en"})
    assert isinstance(result, ToolResult)

    return result


class TestOcrSubmitRateLimit:
    async def test_ocr_submit_call_after_limit_fails_with_rate_limited(
        self, service: JobService, jail: Path, limited_app: FastAPI
    ) -> None:
        # given
        _ = service
        _ = limited_app
        source = jail / "scan.png"
        source.write_bytes(VALID_PNG_BYTES)
        # when
        await _submit_mcp(source.as_uri())
        await _submit_mcp(source.as_uri())
        # then - the third submission is refused with the platform code
        with pytest.raises(ToolError, match=r"^rate_limited: ") as exc_info:
            await _submit_mcp(source.as_uri())
        assert str(exc_info.value).startswith("rate_limited: ")

    async def test_rest_and_mcp_submissions_share_one_budget(
        self, service: JobService, jail: Path, rest_client: AsyncClient
    ) -> None:
        # given
        _ = service
        source = jail / "scan.png"
        source.write_bytes(VALID_PNG_BYTES)
        # when - one submission on each surface spends the shared budget of two
        rest_first = await _submit_rest(rest_client, "rest-first.png")
        mcp_result = await _submit_mcp(source.as_uri())
        rest_over = await _submit_rest(rest_client, "rest-over.png")
        # then - the third submission is refused even though each surface made fewer calls than the limit
        assert rest_first.status_code == 202
        assert json.loads(str(mcp_result.content[0].text))["state"] == "waiting"
        assert rest_over.status_code == 429
        assert rest_over.json()["code"] == "rate_limited"
        assert "retry-after" in {key.lower() for key in rest_over.headers}
