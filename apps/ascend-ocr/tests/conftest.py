import io
import logging
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import pytest
from PIL import Image

from src.config.config import LANGUAGE_MODEL_OVERRIDES, ModelPair, settings
from src.model.ocr_models import (
    JobRecord,
    JobResultLocation,
    JobState,
    OcrJsonResponse,
    OcrPageResult,
    OcrTextLine,
)
from src.service.job_store import JobStore, new_job_id


class OcrResponseFactory:
    @staticmethod
    def with_single_line(
        filename: str = "test.png",
        language: str = "en",
        text: str = "Test",
        confidence: float = 0.9,
    ) -> OcrJsonResponse:
        line = OcrTextLine(
            text=text,
            confidence=confidence,
            bounding_box=[[0.0, 0.0], [100.0, 0.0], [100.0, 20.0], [0.0, 20.0]],
        )

        return OcrJsonResponse(
            filename=filename,
            language=language,
            pages=[OcrPageResult(page_number=1, lines=[line])],
            processing_time_seconds=0.5,
        )

    @staticmethod
    def empty(filename: str = "empty.png", language: str = "en") -> OcrJsonResponse:
        return OcrJsonResponse(
            filename=filename,
            language=language,
            pages=[OcrPageResult(page_number=1, lines=[])],
            processing_time_seconds=0.1,
        )


PNG_MAGIC_BYTES: bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG_MAGIC_BYTES: bytes = b"\xff\xd8\xff" + b"\x00" * 16
PDF_MAGIC_BYTES: bytes = b"%PDF-1.7\n" + b"\x00" * 16


def _make_png(width: int = 10, height: int = 10) -> bytes:
    """A real, decodable PNG, for tests that exercise header inspection (src/api/limits.py)."""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color="white").save(buffer, format="PNG")

    return buffer.getvalue()


def _make_pdf(*page_sizes: tuple[int, int]) -> bytes:
    """A real, decodable PDF with one page per (width, height) pair, at least one required."""
    buffer = io.BytesIO()
    pages = [Image.new("RGB", size, color="white") for size in page_sizes]
    pages[0].save(buffer, format="PDF", save_all=True, append_images=pages[1:])

    return buffer.getvalue()


VALID_PNG_BYTES: bytes = _make_png()
VALID_PDF_BYTES: bytes = _make_pdf((100, 100))
VALID_MULTI_PAGE_PDF_BYTES: bytes = _make_pdf((100, 100), (100, 100))


class FakeResultStore:
    """Stands in for the bucket: records what was written, deleted and signed."""

    def __init__(self) -> None:
        self.objects: dict[str, str] = {}
        self.deleted: list[str] = []
        self.signed: list[tuple[str, float]] = []
        self.delete_error: Exception | None = None
        self.upload_error: Exception | None = None
        self.bucket = "ocr-results"
        self.bucket_reachable: bool | None = None

    async def upload(self, job_id: str, markdown: str) -> JobResultLocation:
        if self.upload_error is not None:
            raise self.upload_error

        key = f"{job_id}.md"
        self.objects[key] = markdown

        return JobResultLocation(bucket=self.bucket, key=key)

    def delete_result(self, key: str) -> None:
        if self.delete_error is not None:
            raise self.delete_error

        self.deleted.append(key)
        self.objects.pop(key, None)

    def presigned_url(self, key: str, expires_in_seconds: float) -> str:
        self.signed.append((key, expires_in_seconds))

        return f"http://public.example/{self.bucket}/{key}?expires={int(expires_in_seconds)}"


def make_record(
    job_id: str | None = None,
    state: JobState = "waiting",
    page_count: int = 1,
    submitted_at: float | None = None,
    surface: Literal["rest", "mcp"] = "rest",
    filename: str = "scan.pdf",
    language: str = "en",
    **overrides: object,
) -> JobRecord:
    """Build a job record with the fields a test does not care about already filled in."""
    return JobRecord.model_validate(
        {
            "job_id": job_id or new_job_id(),
            "state": state,
            "surface": surface,
            "filename": filename,
            "language": language,
            "page_count": page_count,
            "submitted_at": time.time() if submitted_at is None else submitted_at,
            **overrides,
        }
    )


def write_finished_record(store: JobStore, state: JobState) -> JobRecord:
    """Write a record that started running and then reached the given terminal state."""
    record = make_record(state="running", started_at=time.time())
    store.write(record)

    if state == "succeeded":
        return store.succeed(record, JobResultLocation(bucket="ocr-results", key=f"{record.job_id}.md"), 1.0)

    if state == "failed":
        return store.fail(record, "OCR_FAILED", "engine gave up")

    return store.cancel(record)


@pytest.fixture
def jobs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the job store at a directory of this test's own."""
    directory = tmp_path / "jobs"
    monkeypatch.setattr(settings, "OCR_JOBS_DIR", str(directory))

    return directory


@pytest.fixture
def results() -> FakeResultStore:
    return FakeResultStore()


@pytest.fixture
def store(jobs_dir: Path, results: FakeResultStore) -> JobStore:
    _ = jobs_dir

    return JobStore(results)


@pytest.fixture
def emitted_logs() -> Iterator[list[logging.LogRecord]]:
    """Collect every record the service and FastMCP actually emit, at the levels they run at.

    One handler on the root logger is enough, because `setup_logging` sends FastMCP's own lines
    through the root logger, so a line FastMCP writes about a failed tool call is seen as well.
    """
    records: list[logging.LogRecord] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _ListHandler(level=logging.NOTSET)
    root = logging.getLogger()
    root.addHandler(handler)

    try:
        yield records
    finally:
        root.removeHandler(handler)


OFF_FAMILY_LANGUAGE = "ru"
OFF_FAMILY_PAIR = ModelPair("PP-OCRv5_server_det", "eslav_PP-OCRv5_mobile_rec")


@pytest.fixture
def off_family_language(monkeypatch: pytest.MonkeyPatch) -> str:
    """A language an operator has opted back in with a pair of its own, read on the slower measured detector."""
    monkeypatch.setitem(LANGUAGE_MODEL_OVERRIDES, OFF_FAMILY_LANGUAGE, OFF_FAMILY_PAIR)
    monkeypatch.setattr(settings, "SUPPORTED_LANGUAGES", (*settings.SUPPORTED_LANGUAGES, OFF_FAMILY_LANGUAGE))

    return OFF_FAMILY_LANGUAGE
