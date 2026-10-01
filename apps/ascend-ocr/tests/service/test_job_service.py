import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.api.exception_handlers import (
    FileSizeExceededError,
    JobNotFoundError,
    QueueFullError,
    UnsupportedFileTypeError,
    UnsupportedLanguageError,
)
from src.config.config import settings
from src.model.ocr_models import JobResultLocation
from src.service.job_runner import JobRunner
from src.service.job_service import JobService, ensure_language_supported
from src.service.job_store import JobStore, new_job_id
from tests.conftest import (
    VALID_MULTI_PAGE_PDF_BYTES,
    VALID_PNG_BYTES,
    FakeResultStore,
    _make_png,
    make_record,
)

SHIPPED_LANGUAGE_REFUSAL = "Language is not supported. Supported languages: en, pl, de, fr, es, it, pt, nl, ch, japan"


def _holds_any_file(directory: Path) -> bool:
    return directory.exists() and any(directory.iterdir())


@pytest.fixture
def runner(store: JobStore, results: FakeResultStore) -> JobRunner:
    return JobRunner(store, results)


@pytest.fixture
def service(store: JobStore, results: FakeResultStore, runner: JobRunner) -> JobService:
    return JobService(store, results, runner)


class TestSubmit:
    async def test_a_submission_is_accepted_queued_and_answered_with_an_identifier(
        self, service: JobService, store: JobStore, runner: JobRunner
    ) -> None:
        # When
        submitted = await service.submit(VALID_PNG_BYTES, "scan.png", "en", "high", "rest")

        # Then
        assert submitted.state == "waiting"
        assert submitted.page_count == 1
        assert submitted.status_url == f"/v1/ocr/jobs/{submitted.job_id}"
        assert submitted.poll_after_seconds >= 1.0
        assert store.read(submitted.job_id).filename == "scan.png"
        assert runner.documents_waiting() == 1

    async def test_a_submission_reports_how_much_work_is_ahead_of_it(self, service: JobService) -> None:
        # Given
        await service.submit(VALID_MULTI_PAGE_PDF_BYTES, "first.pdf", "en", "high", "rest")

        # When
        second = await service.submit(VALID_PNG_BYTES, "second.png", "en", "high", "rest")

        # Then
        assert second.queue_position == 1
        assert second.pages_ahead == 2

    async def test_the_submitting_surface_is_recorded(self, service: JobService, store: JobStore) -> None:
        # When
        submitted = await service.submit(VALID_PNG_BYTES, "scan.png", "pl", "high", "mcp")

        # Then
        stored = store.read(submitted.job_id)
        assert stored.surface == "mcp"
        assert stored.language == "pl"

    async def test_a_document_over_the_byte_cap_is_refused_before_anything_is_queued(
        self, service: JobService, runner: JobRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 0)

        # When / Then
        with pytest.raises(FileSizeExceededError):
            await service.submit(VALID_PNG_BYTES * 200, "scan.png", "en", "high", "rest")

        assert runner.documents_waiting() == 0

    @pytest.mark.parametrize("language", ["ru", "korean", "xx"])
    async def test_a_language_the_service_does_not_read_is_refused_before_anything_is_stored_or_queued(
        self, service: JobService, runner: JobRunner, jobs_dir: Path, language: str
    ) -> None:
        # When / Then
        with pytest.raises(UnsupportedLanguageError, match="Supported languages: en, pl"):
            await service.submit(VALID_PNG_BYTES, "scan.png", language, "high", "rest")

        assert runner.documents_waiting() == 0
        assert not await asyncio.to_thread(_holds_any_file, jobs_dir)

    def test_the_refusal_names_every_supported_language_and_not_the_one_asked_for(self):
        # When
        with pytest.raises(UnsupportedLanguageError) as exc_info:
            ensure_language_supported("korean")

        # Then
        assert str(exc_info.value) == SHIPPED_LANGUAGE_REFUSAL

    def test_the_refusal_follows_the_configured_allowlist(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "SUPPORTED_LANGUAGES", ("en", "ru"))

        # When / Then: an operator's own list is both what passes and what the refusal names
        ensure_language_supported("ru")
        with pytest.raises(UnsupportedLanguageError) as exc_info:
            ensure_language_supported("pl")

        assert str(exc_info.value) == "Language is not supported. Supported languages: en, ru"

    async def test_the_quality_mode_is_recorded(self, service: JobService, store: JobStore) -> None:
        # When
        submitted = await service.submit(VALID_PNG_BYTES, "scan.png", "en", "normal", "rest")

        # Then
        assert store.read(submitted.job_id).quality == "normal"

    async def test_the_straighten_choice_is_recorded(self, service: JobService, store: JobStore) -> None:
        # When
        submitted = await service.submit(VALID_PNG_BYTES, "photo.png", "en", "high", "mcp", straighten=True)

        # Then
        assert store.read(submitted.job_id).straighten is True

    async def test_an_omitted_straighten_choice_is_recorded_as_off(self, service: JobService, store: JobStore) -> None:
        # When
        submitted = await service.submit(VALID_PNG_BYTES, "scan.png", "en", "high", "rest")

        # Then
        assert store.read(submitted.job_id).straighten is False

    async def test_an_oversized_scan_is_accepted_rather_than_refused(
        self, service: JobService, runner: JobRunner
    ) -> None:
        # When: 300 dpi A4, which the removed 2.5 megapixel inference ceiling refused
        submitted = await service.submit(_make_png(width=2480, height=3508), "scan.png", "en", "high", "rest")

        # Then
        assert submitted.state == "waiting"
        assert runner.documents_waiting() == 1

    async def test_a_document_over_the_source_pixel_ceiling_is_refused(
        self, service: JobService, runner: JobRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "OCR_MAX_SOURCE_PIXELS", 10)

        # When / Then
        with pytest.raises(FileSizeExceededError):
            await service.submit(VALID_PNG_BYTES, "scan.png", "en", "high", "rest")

        assert runner.documents_waiting() == 0

    async def test_a_document_over_the_page_ceiling_is_refused(
        self, service: JobService, runner: JobRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "OCR_JOB_MAX_PAGES", 1)

        # When / Then
        with pytest.raises(FileSizeExceededError, match="exceeding the limit of 1"):
            await service.submit(VALID_MULTI_PAGE_PDF_BYTES, "doc.pdf", "en", "high", "rest")

        assert runner.documents_waiting() == 0

    async def test_a_file_the_service_cannot_read_is_refused(self, service: JobService, runner: JobRunner) -> None:
        # When / Then
        with pytest.raises(UnsupportedFileTypeError):
            await service.submit(b"plain text, not a document", "notes.txt", "en", "high", "rest")

        assert runner.documents_waiting() == 0

    async def test_a_full_queue_refuses_the_submission_and_holds_no_record(
        self, service: JobService, store: JobStore, runner: JobRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "OCR_JOB_QUEUE_MAX_DOCUMENTS", 1)
        await service.submit(VALID_PNG_BYTES, "first.png", "en", "high", "rest")

        # When / Then
        with pytest.raises(QueueFullError):
            await service.submit(VALID_PNG_BYTES, "second.png", "en", "high", "rest")

        assert len(store.records()) == 1

    async def test_a_failed_write_releases_the_place_it_reserved(self, service: JobService, runner: JobRunner) -> None:
        # Given
        with (
            patch.object(type(service._store), "create", AsyncMock(side_effect=OSError("disk full"))),
            pytest.raises(OSError, match="disk full"),
        ):
            await service.submit(VALID_PNG_BYTES, "scan.png", "en", "high", "rest")

        # When
        submitted = await service.submit(VALID_PNG_BYTES, "scan.png", "en", "high", "rest")

        # Then — the next submission is not refused for a place nothing is holding
        assert submitted.job_id


class TestStatus:
    async def test_waiting_work_reports_its_place_and_when_to_ask_again(self, service: JobService) -> None:
        # Given
        submitted = await service.submit(VALID_PNG_BYTES, "scan.png", "en", "high", "rest")

        # When
        status = service.status(submitted.job_id)

        # Then
        assert status.state == "waiting"
        assert status.queue_position == 0
        assert status.pages_ahead == 0
        assert status.pages_done == 0
        assert status.poll_after_seconds is not None
        assert status.result is None
        assert status.finished_at is None

    async def test_successful_work_carries_the_address_and_the_bounded_description(
        self, service: JobService, store: JobStore, results: FakeResultStore
    ) -> None:
        # Given
        record = make_record(state="running", page_count=3, started_at=time.time())
        store.write(record)
        store.succeed(record, JobResultLocation(bucket="ocr-results", key=f"{record.job_id}.md"), 7.5)

        # When
        status = service.status(record.job_id)

        # Then
        assert status.state == "succeeded"
        assert status.poll_after_seconds is None
        assert status.result is not None
        assert status.result.bucket == "ocr-results"
        assert status.result.key == f"{record.job_id}.md"
        assert status.result.page_count == 3
        assert status.result.quality == "high"
        assert status.result.straighten is False
        assert status.result.processing_time_seconds == pytest.approx(7.5)
        assert status.result.url.startswith("http")
        assert results.signed[-1][0] == f"{record.job_id}.md"

    async def test_a_straightened_result_says_it_was_straightened(self, service: JobService, store: JobStore) -> None:
        # Given
        record = make_record(state="running", straighten=True, started_at=time.time())
        store.write(record)
        store.succeed(record, JobResultLocation(bucket="ocr-results", key=f"{record.job_id}.md"), 2.0)

        # When
        status = service.status(record.job_id)

        # Then
        assert status.result is not None
        assert status.result.straighten is True

    async def test_the_signed_link_expires_with_the_record_it_belongs_to(
        self, service: JobService, store: JobStore, results: FakeResultStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given — a record most of the way through its retention window
        monkeypatch.setattr(settings, "OCR_JOB_RETENTION_SECONDS", 600.0)
        record = make_record(state="succeeded", finished_at=time.time() - 500.0)
        record.result = JobResultLocation(bucket="ocr-results", key=f"{record.job_id}.md")
        store.write(record)

        # When
        service.status(record.job_id)

        # Then
        _key, expires_in = results.signed[-1]
        assert 90.0 < expires_in <= 100.0

    async def test_a_failed_record_carries_its_reason_and_no_address(
        self, service: JobService, store: JobStore
    ) -> None:
        # Given
        record = make_record(state="running", started_at=time.time())
        store.write(record)
        store.fail(record, "OCR_FAILED", "engine gave up")

        # When
        status = service.status(record.job_id)

        # Then
        assert status.state == "failed"
        assert status.error_code == "OCR_FAILED"
        assert status.error_reason == "engine gave up"
        assert status.result is None
        assert status.poll_after_seconds is None
        assert status.queue_position is None
        assert status.pages_ahead is None

    def test_running_work_reports_no_place_in_the_queue(self, service: JobService, store: JobStore) -> None:
        # Given
        record = make_record(state="running", started_at=time.time())
        store.write(record)

        # When
        status = service.status(record.job_id)

        # Then
        assert status.state == "running"
        assert status.queue_position is None
        assert status.pages_ahead is None
        assert status.poll_after_seconds is not None

    def test_an_unknown_identifier_is_not_found(self, service: JobService) -> None:
        # When / Then
        with pytest.raises(JobNotFoundError):
            service.status(new_job_id())

    def test_an_identifier_that_is_not_shaped_like_one_is_not_found(self, service: JobService) -> None:
        # When / Then
        with pytest.raises(JobNotFoundError):
            service.status("../../etc/passwd")

    async def test_the_answer_does_not_grow_with_the_document(self, service: JobService, store: JobStore) -> None:
        # Given — one page against the page ceiling, both finished
        short = make_record(state="running", page_count=1, started_at=time.time())
        long_document = make_record(state="running", page_count=settings.OCR_JOB_MAX_PAGES, started_at=time.time())
        for record in (short, long_document):
            store.write(record)
            store.succeed(record, JobResultLocation(bucket="ocr-results", key=f"{record.job_id}.md"), 1.0)

        # When
        short_answer = service.status(short.job_id).model_dump_json()
        long_answer = service.status(long_document.job_id).model_dump_json()

        # Then — the difference is the page count's own digits, not the document's text
        assert abs(len(long_answer) - len(short_answer)) < 10
        assert "Page 1" not in long_answer


class TestListJobs:
    def test_an_idle_service_lists_nothing(self, service: JobService) -> None:
        # When / Then
        assert service.list_jobs().jobs == []

    async def test_everything_in_flight_is_listed_in_submission_order(
        self, service: JobService, store: JobStore, runner: JobRunner
    ) -> None:
        # Given
        first = await service.submit(VALID_MULTI_PAGE_PDF_BYTES, "first.pdf", "en", "high", "rest")
        second = await service.submit(VALID_PNG_BYTES, "second.png", "en", "high", "rest")
        runner._running = runner._queue.popleft()

        # When
        listing = service.list_jobs()

        # Then
        assert [entry.job_id for entry in listing.jobs] == [first.job_id, second.job_id]
        assert [entry.state for entry in listing.jobs] == ["running", "waiting"]
        assert [entry.queue_position for entry in listing.jobs] == [None, 1]
        assert listing.jobs[0].page_count == 2

    async def test_finished_work_is_not_listed_but_is_still_readable(
        self, service: JobService, store: JobStore
    ) -> None:
        # Given
        record = make_record(state="succeeded", finished_at=time.time())
        store.write(record)

        # When / Then
        assert service.list_jobs().jobs == []
        assert service.status(record.job_id).state == "succeeded"

    async def test_work_whose_record_vanished_is_left_out_rather_than_failing_the_listing(
        self, service: JobService, store: JobStore, runner: JobRunner
    ) -> None:
        # Given
        submitted = await service.submit(VALID_PNG_BYTES, "scan.png", "en", "high", "rest")
        await store.delete(store.read(submitted.job_id))

        # When
        listing = service.list_jobs()

        # Then
        assert listing.jobs == []

    async def test_the_listing_is_bounded_by_the_queue_s_own_document_bound(
        self, service: JobService, runner: JobRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given — a full queue plus the one document being read
        monkeypatch.setattr(settings, "OCR_JOB_QUEUE_MAX_DOCUMENTS", 3)
        for index in range(3):
            await service.submit(VALID_PNG_BYTES, f"scan-{index}.png", "en", "high", "rest")

        runner._running = runner._queue.popleft()
        await service.submit(VALID_PNG_BYTES, "one-more.png", "en", "high", "rest")

        # When / Then
        assert len(service.list_jobs().jobs) == settings.OCR_JOB_QUEUE_MAX_DOCUMENTS + 1


class TestDelete:
    async def test_deleting_waiting_work_cancels_it(
        self, service: JobService, store: JobStore, runner: JobRunner
    ) -> None:
        # Given
        submitted = await service.submit(VALID_PNG_BYTES, "scan.png", "en", "high", "rest")

        # When
        await service.delete(submitted.job_id)

        # Then
        assert store.read(submitted.job_id).state == "cancelled"
        assert runner.documents_waiting() == 0

    async def test_deleting_finished_work_removes_the_record_and_the_object(
        self, service: JobService, store: JobStore, results: FakeResultStore
    ) -> None:
        # Given
        record = make_record(state="succeeded", finished_at=time.time())
        record.result = JobResultLocation(bucket="ocr-results", key=f"{record.job_id}.md")
        store.write(record)

        # When
        await service.delete(record.job_id)

        # Then
        assert results.deleted == [f"{record.job_id}.md"]
        with pytest.raises(JobNotFoundError):
            service.status(record.job_id)

    async def test_deleting_work_twice_reports_not_found_the_second_time(
        self, service: JobService, store: JobStore
    ) -> None:
        # Given
        record = make_record(state="failed", finished_at=time.time())
        store.write(record)
        await service.delete(record.job_id)

        # When / Then
        with pytest.raises(JobNotFoundError):
            await service.delete(record.job_id)

    async def test_deleting_an_unknown_identifier_is_not_found(self, service: JobService) -> None:
        # When / Then
        with pytest.raises(JobNotFoundError):
            await service.delete(new_job_id())
