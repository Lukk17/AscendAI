import asyncio
import os
import string
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.api.exception_handlers import ERROR_CODE_OCR_FAILED, JobNotFoundError
from src.config.config import settings
from src.model.ocr_models import (
    FAILURE_LIFETIME_EXCEEDED,
    FAILURE_RESULT_STORE_UNAVAILABLE,
    FAILURE_SERVICE_RESTARTED,
    JOB_ID_LENGTH,
    JobResultLocation,
)
from src.service.job_store import (
    INPUT_SUFFIX,
    PROGRESS_SUFFIX,
    RECORD_SUFFIX,
    JobStore,
    atomic_write_bytes,
    job_path,
    new_job_id,
    read_progress,
    validate_job_id,
    write_progress,
)
from tests.conftest import FakeResultStore, make_record


def files_named_after(directory: Path, job_id: str) -> list[str]:
    """Every file the store still holds for one job, by name."""
    return sorted(path.name for path in directory.glob(f"{job_id}*"))


TRAVERSAL_CANDIDATES = [
    "../../etc/passwd",
    "..",
    "a/b",
    "a\\b",
    "job id",
    "",
    "x" * 200,
    "short",
    "abcdefghijklmnopqrstu.",
]


class TestIdentifier:
    def test_identifier_is_url_safe_and_fixed_length(self):
        # When
        job_id = new_job_id()

        # Then
        assert len(job_id) == JOB_ID_LENGTH
        assert set(job_id) <= set(string.ascii_letters + string.digits + "-_")

    def test_identifier_carries_at_least_128_bits_of_randomness(self):
        # Given — 22 base64url characters encode 16 bytes, and none of them repeats
        # across a batch, so the source is not a counter or a hash of the input
        identifiers = {new_job_id() for _ in range(500)}

        # Then
        assert len(identifiers) == 500

    @pytest.mark.parametrize("candidate", TRAVERSAL_CANDIDATES)
    def test_candidate_that_is_not_an_identifier_is_refused(self, candidate):
        # Then
        with pytest.raises(JobNotFoundError):
            validate_job_id(candidate)

    def test_a_refused_identifier_never_reaches_the_filesystem(self):
        # Given
        with (
            patch("src.service.job_store.jobs_dir") as mock_jobs_dir,
            pytest.raises(JobNotFoundError),
        ):
            job_path("../../etc/passwd", RECORD_SUFFIX)

        mock_jobs_dir.assert_not_called()

    def test_a_valid_identifier_is_returned_unchanged(self):
        # Given
        job_id = new_job_id()

        # Then
        assert validate_job_id(job_id) == job_id


class TestRecordLifecycle:
    async def test_create_writes_the_bytes_and_then_the_record(self, store: JobStore, jobs_dir: Path) -> None:
        # Given
        record = make_record()

        # When
        await store.create(record, b"payload")

        # Then
        assert store.read(record.job_id).job_id == record.job_id
        assert (jobs_dir / f"{record.job_id}{INPUT_SUFFIX}").read_bytes() == b"payload"

    async def test_read_input_returns_the_submitted_bytes(self, store: JobStore) -> None:
        # Given
        record = make_record()
        await store.create(record, b"payload")

        # When
        payload = await store.read_input(record.job_id)

        # Then
        assert payload == b"payload"

    async def test_read_input_raises_not_found_once_the_bytes_are_gone(self, store: JobStore) -> None:
        # Given
        record = make_record()
        await store.create(record, b"payload")
        store.delete_input(record.job_id)

        # Then
        with pytest.raises(JobNotFoundError):
            await store.read_input(record.job_id)

    def test_reading_an_unknown_identifier_raises_not_found(self, store: JobStore) -> None:
        # Then
        with pytest.raises(JobNotFoundError):
            store.read(new_job_id())

    def test_reading_a_corrupt_record_raises_not_found(self, store: JobStore, jobs_dir: Path) -> None:
        # Given
        job_id = new_job_id()
        jobs_dir.mkdir(parents=True, exist_ok=True)
        (jobs_dir / f"{job_id}{RECORD_SUFFIX}").write_bytes(b"{not json")

        # Then
        with pytest.raises(JobNotFoundError):
            store.read(job_id)

    def test_exists_reports_whether_a_record_is_held(self, store: JobStore) -> None:
        # Given
        record = make_record()

        # When
        store.write(record)

        # Then
        assert store.exists(record.job_id) is True
        assert store.exists(new_job_id()) is False

    async def test_delete_removes_the_record_the_bytes_and_the_progress(self, store: JobStore, jobs_dir: Path) -> None:
        # Given
        record = make_record()
        await store.create(record, b"payload")
        write_progress(record.job_id, 1)

        # When
        await store.delete(record)

        # Then
        assert await asyncio.to_thread(files_named_after, jobs_dir, record.job_id) == []

    async def test_delete_removes_the_result_object_before_the_record(
        self, store: JobStore, results: FakeResultStore, jobs_dir: Path
    ) -> None:
        # Given
        record = make_record(state="succeeded")
        record.result = JobResultLocation(bucket="ocr-results", key=f"{record.job_id}.md")
        store.write(record)

        # When
        await store.delete(record)

        # Then
        assert results.deleted == [f"{record.job_id}.md"]
        assert await asyncio.to_thread(files_named_after, jobs_dir, record.job_id) == []

    async def test_delete_leaves_the_record_when_the_object_will_not_go(
        self, store: JobStore, results: FakeResultStore
    ) -> None:
        # Given
        results.delete_error = RuntimeError("bucket unreachable")
        record = make_record(state="succeeded")
        record.result = JobResultLocation(bucket="ocr-results", key=f"{record.job_id}.md")
        store.write(record)

        # When / Then
        with pytest.raises(RuntimeError):
            await store.delete(record)

        assert store.exists(record.job_id) is True

    async def test_deleting_a_record_with_no_result_touches_no_object(
        self, store: JobStore, results: FakeResultStore
    ) -> None:
        # Given
        record = make_record(state="failed")
        store.write(record)

        # When
        await store.delete(record)

        # Then
        assert results.deleted == []


class TestAtomicWrites:
    def test_a_failed_replace_leaves_the_previous_content_intact(self, store: JobStore, jobs_dir: Path) -> None:
        # Given
        record = make_record(page_count=3)
        store.write(record)

        # When — the replace fails part-way through a second write
        record.page_count = 9
        with (
            patch("src.service.job_store.os.replace", side_effect=OSError("replace failed")),
            pytest.raises(OSError, match="replace failed"),
        ):
            store.write(record)

        # Then — a reader still sees the whole previous record, never half of either
        assert store.read(record.job_id).page_count == 3

    def test_write_goes_through_a_temporary_file_in_the_same_directory(self, tmp_path: Path) -> None:
        # Given
        target = tmp_path / "record.json"
        seen: list[list[str]] = []
        real_replace = os.replace

        def capture(source, destination):
            seen.append(sorted(path.name for path in tmp_path.iterdir()))
            real_replace(source, destination)

        # When
        with patch("src.service.job_store.os.replace", side_effect=capture):
            atomic_write_bytes(target, b"content")

        # Then
        assert seen == [["record.json.tmp"]]
        assert target.read_bytes() == b"content"


class TestProgress:
    def test_progress_starts_at_zero_before_the_first_page(self, jobs_dir: Path) -> None:
        _ = jobs_dir

        # Then
        assert read_progress(new_job_id()) == 0

    def test_progress_advances_page_by_page(self, jobs_dir: Path) -> None:
        _ = jobs_dir
        job_id = new_job_id()

        # When
        write_progress(job_id, 1)
        first = read_progress(job_id)
        write_progress(job_id, 2)

        # Then
        assert first == 1
        assert read_progress(job_id) == 2

    def test_unreadable_progress_reads_as_zero(self, jobs_dir: Path) -> None:
        # Given
        job_id = new_job_id()
        jobs_dir.mkdir(parents=True, exist_ok=True)
        (jobs_dir / f"{job_id}{PROGRESS_SUFFIX}").write_bytes(b"not a number")

        # Then
        assert read_progress(job_id) == 0


class TestTerminalWriters:
    async def test_failing_a_job_records_the_reason_and_drops_the_bytes(self, store: JobStore, jobs_dir: Path) -> None:
        # Given
        record = make_record()
        await store.create(record, b"payload")

        # When
        store.fail(record, ERROR_CODE_OCR_FAILED, "engine gave up")

        # Then
        stored = store.read(record.job_id)
        assert stored.state == "failed"
        assert stored.error_code == ERROR_CODE_OCR_FAILED
        assert stored.error_reason == "engine gave up"
        assert stored.retryable is False
        assert stored.finished_at is not None
        assert not (jobs_dir / f"{record.job_id}{INPUT_SUFFIX}").exists()

    @pytest.mark.parametrize(
        ("reason", "retryable"),
        [
            (FAILURE_SERVICE_RESTARTED, True),
            (FAILURE_RESULT_STORE_UNAVAILABLE, True),
            (FAILURE_LIFETIME_EXCEEDED, False),
            (ERROR_CODE_OCR_FAILED, False),
        ],
    )
    def test_only_the_reasons_that_learned_nothing_are_marked_retryable(
        self, store: JobStore, reason: str, retryable: bool
    ) -> None:
        # Given
        record = make_record()

        # When
        store.fail(record, reason, "detail")

        # Then
        assert store.read(record.job_id).retryable is retryable

    @pytest.mark.parametrize("reason", [FAILURE_SERVICE_RESTARTED, FAILURE_LIFETIME_EXCEEDED, ERROR_CODE_OCR_FAILED])
    def test_a_job_failed_after_some_pages_reports_the_pages_it_read(
        self, store: JobStore, jobs_dir: Path, reason: str
    ) -> None:
        # Given
        record = make_record(state="running", page_count=5, started_at=time.time())
        write_progress(record.job_id, 2)

        # When
        store.fail(record, reason, "detail")

        # Then
        assert store.read(record.job_id).pages_done == 2
        assert not (jobs_dir / f"{record.job_id}{PROGRESS_SUFFIX}").exists()

    def test_a_job_failed_before_its_first_page_reports_no_pages_read(self, store: JobStore) -> None:
        # Given
        record = make_record(state="waiting", page_count=5)

        # When
        store.fail(record, FAILURE_LIFETIME_EXCEEDED, "detail")

        # Then
        assert store.read(record.job_id).pages_done == 0

    def test_a_restart_reports_the_pages_the_interrupted_job_had_read(self, store: JobStore) -> None:
        # Given
        record = make_record(state="running", page_count=5, started_at=time.time())
        store.write(record)
        write_progress(record.job_id, 4)

        # When
        store.recover_after_restart()

        # Then
        assert store.read(record.job_id).pages_done == 4

    def test_cancelling_records_cancellation_rather_than_failure(self, store: JobStore) -> None:
        # Given
        record = make_record(state="running", started_at=time.time())

        # When
        store.cancel(record)

        # Then
        stored = store.read(record.job_id)
        assert stored.state == "cancelled"
        assert stored.error_code is None
        assert stored.result is None

    def test_a_job_cancelled_after_some_pages_reports_the_pages_it_read(self, store: JobStore, jobs_dir: Path) -> None:
        # Given
        record = make_record(state="running", page_count=5, started_at=time.time())
        write_progress(record.job_id, 3)

        # When
        store.cancel(record)

        # Then
        assert store.read(record.job_id).pages_done == 3
        assert not (jobs_dir / f"{record.job_id}{PROGRESS_SUFFIX}").exists()

    def test_a_job_cancelled_before_its_first_page_reports_no_pages_read(self, store: JobStore) -> None:
        # Given
        record = make_record(state="waiting", page_count=5)

        # When
        store.cancel(record)

        # Then
        assert store.read(record.job_id).pages_done == 0

    def test_starting_waiting_work_records_it_as_running(self, store: JobStore) -> None:
        # Given
        record = make_record(state="waiting")
        store.write(record)

        # When
        started = store.start(record.job_id, 1234.5)

        # Then
        assert started is not None
        stored = store.read(record.job_id)
        assert stored.state == "running"
        assert stored.started_at == pytest.approx(1234.5)

    def test_starting_never_writes_over_a_cancel(self, store: JobStore) -> None:
        # Given: the work was cancelled after the runner took it from the queue
        record = make_record(state="waiting")
        store.write(record)
        store.cancel(store.read(record.job_id))

        # When
        started = store.start(record.job_id, 1234.5)

        # Then
        assert started is None
        stored = store.read(record.job_id)
        assert stored.state == "cancelled"
        assert stored.started_at is None

    def test_starting_work_whose_record_is_gone_starts_nothing(self, store: JobStore) -> None:
        # Given
        record = make_record(state="waiting")

        # When / Then
        assert store.start(record.job_id, 1234.5) is None
        assert store.exists(record.job_id) is False

    def test_succeeding_records_the_result_and_every_page_as_done(self, store: JobStore) -> None:
        # Given
        record = make_record(state="running", page_count=4, started_at=time.time())
        location = JobResultLocation(bucket="ocr-results", key=f"{record.job_id}.md")

        # When
        store.succeed(record, location, processing_time_seconds=12.5)

        # Then
        stored = store.read(record.job_id)
        assert stored.state == "succeeded"
        assert stored.result == location
        assert stored.pages_done == 4
        assert stored.processing_time_seconds == pytest.approx(12.5)


class TestStartupRecovery:
    def test_waiting_and_running_work_is_failed_and_finished_work_is_left_alone(self, store: JobStore) -> None:
        # Given — one of every state the store can hold
        waiting = make_record(state="waiting")
        running = make_record(state="running", started_at=time.time())
        succeeded = make_record(state="succeeded", finished_at=time.time())
        failed = make_record(state="failed", finished_at=time.time())
        cancelled = make_record(state="cancelled", finished_at=time.time())
        for record in (waiting, running, succeeded, failed, cancelled):
            store.write(record)

        # When
        recovered = store.recover_after_restart()

        # Then
        assert {record.job_id for record in recovered} == {waiting.job_id, running.job_id}
        assert store.read(waiting.job_id).error_code == FAILURE_SERVICE_RESTARTED
        assert store.read(running.job_id).retryable is True
        assert store.read(succeeded.job_id).state == "succeeded"
        assert store.read(cancelled.job_id).state == "cancelled"
        assert all(record.is_terminal for record in store.records())

    async def test_recovery_drops_the_submitted_bytes_of_work_in_flight(self, store: JobStore, jobs_dir: Path) -> None:
        # Given
        record = make_record(state="running")
        await store.create(record, b"payload")

        # When
        store.recover_after_restart()

        # Then
        assert not (jobs_dir / f"{record.job_id}{INPUT_SUFFIX}").exists()

    def test_a_finished_record_keeps_its_original_expiry(self, store: JobStore) -> None:
        # Given
        finished_at = time.time() - 100.0
        record = make_record(state="succeeded", finished_at=finished_at)
        store.write(record)

        # When
        store.recover_after_restart()

        # Then
        assert store.read(record.job_id).finished_at == pytest.approx(finished_at)

    def test_an_unreadable_record_is_ignored_rather_than_crashing_recovery(
        self, store: JobStore, jobs_dir: Path
    ) -> None:
        # Given
        jobs_dir.mkdir(parents=True, exist_ok=True)
        (jobs_dir / f"{new_job_id()}{RECORD_SUFFIX}").write_bytes(b"{not json")
        waiting = make_record(state="waiting")
        store.write(waiting)

        # When
        recovered = store.recover_after_restart()

        # Then
        assert [record.job_id for record in recovered] == [waiting.job_id]


class TestRetentionSweep:
    async def test_a_record_past_its_window_is_removed_with_its_object(
        self, store: JobStore, results: FakeResultStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "OCR_JOB_RETENTION_SECONDS", 60.0)
        record = make_record(state="succeeded", finished_at=time.time() - 120.0)
        record.result = JobResultLocation(bucket="ocr-results", key=f"{record.job_id}.md")
        store.write(record)

        # When
        removed = await store.sweep_retention()

        # Then
        assert [swept.job_id for swept in removed] == [record.job_id]
        assert results.deleted == [f"{record.job_id}.md"]
        assert store.exists(record.job_id) is False

    async def test_a_record_inside_its_window_is_kept(self, store: JobStore, monkeypatch: pytest.MonkeyPatch) -> None:
        # Given
        monkeypatch.setattr(settings, "OCR_JOB_RETENTION_SECONDS", 3600.0)
        record = make_record(state="succeeded", finished_at=time.time() - 60.0)
        store.write(record)

        # When
        removed = await store.sweep_retention()

        # Then
        assert removed == []
        assert store.exists(record.job_id) is True

    async def test_the_oldest_finished_records_are_evicted_beyond_the_count_bound(
        self, store: JobStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given — three finished records, all inside their window, with room for two
        monkeypatch.setattr(settings, "OCR_JOB_MAX_RETAINED", 2)
        now = time.time()
        oldest = make_record(state="succeeded", submitted_at=now - 30.0, finished_at=now - 30.0)
        middle = make_record(state="succeeded", submitted_at=now - 20.0, finished_at=now - 20.0)
        newest = make_record(state="succeeded", submitted_at=now - 10.0, finished_at=now - 10.0)
        for record in (oldest, middle, newest):
            store.write(record)

        # When
        removed = await store.sweep_retention()

        # Then
        assert [swept.job_id for swept in removed] == [oldest.job_id]
        assert store.retained_count() == 2

    async def test_neither_pass_removes_waiting_or_running_work(
        self, store: JobStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given — a count bound of one, with two pieces of work still in flight
        monkeypatch.setattr(settings, "OCR_JOB_MAX_RETAINED", 1)
        monkeypatch.setattr(settings, "OCR_JOB_RETENTION_SECONDS", 1.0)
        waiting = make_record(state="waiting", submitted_at=time.time() - 3600.0)
        running = make_record(state="running", submitted_at=time.time() - 3600.0)
        for record in (waiting, running):
            store.write(record)

        # When
        removed = await store.sweep_retention()

        # Then
        assert removed == []
        assert store.exists(waiting.job_id) is True
        assert store.exists(running.job_id) is True

    async def test_a_record_whose_object_will_not_delete_stays_in_place(
        self, store: JobStore, results: FakeResultStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "OCR_JOB_RETENTION_SECONDS", 1.0)
        results.delete_error = RuntimeError("bucket unreachable")
        record = make_record(state="succeeded", finished_at=time.time() - 60.0)
        record.result = JobResultLocation(bucket="ocr-results", key=f"{record.job_id}.md")
        store.write(record)

        # When
        removed = await store.sweep_retention()

        # Then — the record still names the object, so the next sweep tries again
        assert removed == []
        assert store.exists(record.job_id) is True

    async def test_a_record_with_no_finish_time_falls_back_to_its_submission(
        self, store: JobStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given — a terminal record written by hand with no finish time recorded
        monkeypatch.setattr(settings, "OCR_JOB_RETENTION_SECONDS", 60.0)
        record = make_record(state="failed", submitted_at=time.time() - 600.0)
        store.write(record)

        # When
        removed = await store.sweep_retention()

        # Then
        assert [swept.job_id for swept in removed] == [record.job_id]


class TestLifetimeSweep:
    async def test_work_past_the_maximum_lifetime_is_failed_and_its_bytes_dropped(
        self, store: JobStore, jobs_dir: Path
    ) -> None:
        # Given
        record = make_record(state="running", submitted_at=time.time() - settings.OCR_JOB_MAX_LIFETIME_SECONDS - 1.0)
        await store.create(record, b"payload")

        # When
        expired = store.sweep_lifetime()

        # Then
        assert [wedged.job_id for wedged in expired] == [record.job_id]
        stored = store.read(record.job_id)
        assert stored.state == "failed"
        assert stored.error_code == FAILURE_LIFETIME_EXCEEDED
        assert not (jobs_dir / f"{record.job_id}{INPUT_SUFFIX}").exists()

    def test_work_inside_the_maximum_lifetime_is_untouched(self, store: JobStore) -> None:
        # Given — a document at the page ceiling, behind a full queue, still legitimate
        record = make_record(
            state="waiting",
            page_count=settings.OCR_JOB_MAX_PAGES,
            submitted_at=time.time() - settings.OCR_JOB_MAX_LIFETIME_SECONDS + 60.0,
        )
        store.write(record)

        # When
        expired = store.sweep_lifetime()

        # Then
        assert expired == []
        assert store.read(record.job_id).state == "waiting"

    def test_a_terminal_record_is_never_failed_for_its_lifetime(self, store: JobStore) -> None:
        # Given
        record = make_record(state="succeeded", submitted_at=0.0, finished_at=time.time())
        store.write(record)

        # When
        expired = store.sweep_lifetime()

        # Then
        assert expired == []
        assert store.read(record.job_id).state == "succeeded"

    async def test_sweep_runs_both_passes(self, store: JobStore, monkeypatch: pytest.MonkeyPatch) -> None:
        # Given — one wedged record and one expired one
        monkeypatch.setattr(settings, "OCR_JOB_RETENTION_SECONDS", 1.0)
        wedged = make_record(state="running", submitted_at=time.time() - settings.OCR_JOB_MAX_LIFETIME_SECONDS - 1.0)
        expired = make_record(state="succeeded", finished_at=time.time() - 60.0)
        for record in (wedged, expired):
            store.write(record)

        # When
        await store.sweep()

        # Then
        assert store.read(wedged.job_id).error_code == FAILURE_LIFETIME_EXCEEDED
        assert store.exists(expired.job_id) is False


class TestOffLoopWrites:
    async def test_the_event_loop_stays_free_while_a_submission_is_written(
        self, store: JobStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given — a write of MAX_FILE_SIZE_MB that blocks until this test releases it
        released = threading.Event()
        original = atomic_write_bytes

        def blocking_write(path, payload):
            released.wait(timeout=5.0)
            original(path, payload)

        monkeypatch.setattr("src.service.job_store.atomic_write_bytes", blocking_write)
        payload = b"x" * (settings.MAX_FILE_SIZE_MB * 1024 * 1024)
        record = make_record()

        # When — the handler keeps running while that write is in flight
        create = asyncio.create_task(store.create(record, payload))
        ticks = 0
        while ticks < 5:
            await asyncio.sleep(0)
            ticks += 1

        released.set()
        await create

        # Then
        assert ticks == 5
        assert store.exists(record.job_id) is True


class TestRetainedCount:
    def test_only_finished_records_are_counted(self, store: JobStore) -> None:
        # Given
        for record in (make_record(state="waiting"), make_record(state="succeeded"), make_record(state="failed")):
            store.write(record)

        # Then
        assert store.retained_count() == 2


class TestFileRemovalFailures:
    def test_a_file_that_will_not_delete_is_logged_rather_than_raised(
        self, store: JobStore, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Given
        record = make_record()
        store.write(record)
        caplog.set_level("WARNING")

        # When / Then — a locked file must not turn a finish into a crash
        with patch("src.service.job_store.Path.unlink", side_effect=OSError("locked")):
            store.delete_input(record.job_id)

        assert any("Failed to remove job file" in message for message in caplog.messages)
