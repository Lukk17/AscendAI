import io
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError
from httpx import ASGITransport, AsyncClient
from PIL import Image

from src.api.exception_handlers import FileSizeExceededError, UnsupportedFileTypeError
from src.api.mcp.mcp_server import ocr_submit
from src.api.middleware.rate_limit import limiter
from src.config.config import QualityMode, settings
from src.main import create_app
from src.service.job_runner import JobRunner
from src.service.job_service import JobService
from src.service.job_store import JobStore
from tests.conftest import (
    VALID_MULTI_PAGE_PDF_BYTES,
    VALID_PNG_BYTES,
    FakeResultStore,
)

JOBS_PATH = "/v1/ocr/jobs"


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    limiter.reset()


@pytest.fixture
def runner(jobs_dir: Path, results: FakeResultStore) -> JobRunner:
    _ = jobs_dir

    return JobRunner(JobStore(results), results)


@pytest.fixture(autouse=True)
def service(runner: JobRunner, results: FakeResultStore, monkeypatch: pytest.MonkeyPatch) -> JobService:
    """One service behind both surfaces, so a guard cannot be applied on one and not the other."""
    built = JobService(runner._store, results, runner)
    monkeypatch.setattr("src.api.rest.rest_endpoints.job_service", built)
    monkeypatch.setattr("src.api.mcp.mcp_server.job_service", built)

    return built


@pytest.fixture
def store_of(runner: JobRunner) -> JobStore:
    return runner._store


@pytest.fixture
async def rest_client():
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def jail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))

    return tmp_path


GUARD_CASES = [
    pytest.param(
        "source_pixel_ceiling",
        VALID_PNG_BYTES,
        "scan.png",
        "image/png",
        400,
        "FILE_TOO_LARGE",
        id="source-pixel-ceiling",
    ),
    pytest.param("bomb_guard", VALID_PNG_BYTES, "scan.png", "image/png", 400, "FILE_TOO_LARGE", id="bomb-guard"),
    pytest.param("byte_cap", VALID_PNG_BYTES * 200, "scan.png", "image/png", 400, "FILE_TOO_LARGE", id="byte-cap"),
    pytest.param(
        "type_check",
        b"plain text, not a document",
        "notes.txt",
        "text/plain",
        400,
        "UNSUPPORTED_FILE_TYPE",
        id="type-check",
    ),
    pytest.param(
        "page_ceiling",
        VALID_MULTI_PAGE_PDF_BYTES,
        "doc.pdf",
        "application/pdf",
        400,
        "FILE_TOO_LARGE",
        id="page-ceiling",
    ),
]


def arm_guard(guard: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure the service so the named guard is the one that refuses the fixture."""
    if guard == "source_pixel_ceiling":
        monkeypatch.setattr(settings, "OCR_MAX_SOURCE_PIXELS", 10)
    elif guard == "bomb_guard":
        # Pillow's own decompression-bomb guard, which raises rather than warning above
        # twice this value, and is remapped to the service's oversized-input code.
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
    elif guard == "byte_cap":
        monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 0)
    elif guard == "page_ceiling":
        monkeypatch.setattr(settings, "OCR_JOB_MAX_PAGES", 1)


class TestBothSurfacesApplyEveryInputGuardIdentically:
    @pytest.mark.parametrize(("guard", "payload", "filename", "content_type", "status", "code"), GUARD_CASES)
    async def test_a_refused_submission_is_refused_the_same_way_on_both_surfaces(
        self,
        guard: str,
        payload: bytes,
        filename: str,
        content_type: str,
        status: int,
        code: str,
        rest_client: AsyncClient,
        runner: JobRunner,
        jail: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Given
        arm_guard(guard, monkeypatch)
        source = jail / filename
        source.write_bytes(payload)

        # When - REST
        rest_response = await rest_client.post(
            JOBS_PATH,
            files={"file": (filename, io.BytesIO(payload), content_type)},
        )

        # When - MCP, through a jailed file:// URI
        expected_error = UnsupportedFileTypeError if code == "UNSUPPORTED_FILE_TYPE" else FileSizeExceededError
        with pytest.raises(ToolError) as mcp_exc_info:
            await ocr_submit(source.as_uri(), lang="en")

        # Then - the same code from both, and neither queued anything
        assert rest_response.status_code == status
        assert rest_response.json()["code"] == code
        assert str(mcp_exc_info.value).startswith(f"{code}: ")
        assert isinstance(mcp_exc_info.value.__cause__, expected_error)
        assert runner.documents_waiting() == 0

    async def test_a_document_both_surfaces_accept_reaches_the_queue_from_either(
        self, rest_client: AsyncClient, runner: JobRunner, jail: Path
    ) -> None:
        # Given
        source = jail / "scan.png"
        source.write_bytes(VALID_PNG_BYTES)

        # When
        rest_response = await rest_client.post(
            JOBS_PATH,
            files={"file": ("scan.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
        )
        mcp_result = await ocr_submit(source.as_uri(), lang="en")

        # Then
        assert rest_response.status_code == 202
        assert mcp_result["state"] == rest_response.json()["state"]
        assert runner.documents_waiting() == 2

    @pytest.mark.parametrize("quality", ["normal", "high"])
    async def test_both_surfaces_record_the_same_quality_mode(
        self, rest_client: AsyncClient, jail: Path, store_of: JobStore, quality: QualityMode
    ) -> None:
        # Given
        source = jail / "scan.png"
        source.write_bytes(VALID_PNG_BYTES)

        # When
        rest_response = await rest_client.post(
            JOBS_PATH,
            files={"file": ("scan.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
            data={"quality": quality},
        )
        mcp_result = await ocr_submit(source.as_uri(), lang="en", quality=quality)

        # Then
        assert store_of.read(rest_response.json()["job_id"]).quality == quality
        assert store_of.read(str(mcp_result["job_id"])).quality == quality

    @pytest.mark.parametrize("straighten", [True, False])
    async def test_both_surfaces_record_the_same_straighten_choice(
        self, rest_client: AsyncClient, jail: Path, store_of: JobStore, straighten: bool
    ) -> None:
        # Given
        source = jail / "photo.png"
        source.write_bytes(VALID_PNG_BYTES)

        # When
        rest_response = await rest_client.post(
            JOBS_PATH,
            files={"file": ("photo.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
            data={"straighten": str(straighten).lower()},
        )
        mcp_result = await ocr_submit(source.as_uri(), lang="en", straighten=straighten)

        # Then
        assert store_of.read(rest_response.json()["job_id"]).straighten is straighten
        assert store_of.read(str(mcp_result["job_id"])).straighten is straighten

    async def test_work_submitted_on_one_surface_is_readable_on_the_other(
        self, rest_client: AsyncClient, jail: Path
    ) -> None:
        # Given
        source = jail / "scan.png"
        source.write_bytes(VALID_PNG_BYTES)
        submitted = await ocr_submit(source.as_uri(), lang="en")

        # When
        response = await rest_client.get(f"{JOBS_PATH}/{submitted['job_id']}")

        # Then
        assert response.status_code == 200
        assert response.json()["state"] == "waiting"
        assert response.json()["page_count"] == submitted["page_count"]
