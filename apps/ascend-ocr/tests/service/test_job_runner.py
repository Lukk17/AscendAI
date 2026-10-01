import asyncio
import time
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.exception_handlers import (
    ERROR_CODE_INTERNAL,
    ERROR_CODE_OCR_FAILED,
    OcrProcessingError,
    QueueFullError,
)
from src.config.config import settings
from src.model.ocr_models import FAILURE_RESULT_STORE_UNAVAILABLE, JobRecord, JobResultLocation
from src.observability.metrics import OCR_DURATION_SECONDS
from src.service import ocr_service as ocr_service_module
from src.service.job_runner import JobRunner, poll_hint_seconds
from src.service.job_service import JobService
from src.service.job_store import INPUT_SUFFIX, JobStore, write_progress
from src.service.result_store import ResultStoreUnavailableError
from tests.conftest import VALID_PNG_BYTES, FakeResultStore, OcrResponseFactory, make_record

DRAIN_TIMEOUT_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.01
POLL_ATTEMPTS = int(DRAIN_TIMEOUT_SECONDS / POLL_INTERVAL_SECONDS)


@pytest.fixture
def runner(store: JobStore, results: FakeResultStore) -> JobRunner:
    return JobRunner(store, results)


async def queue_job(
    runner: JobRunner, store: JobStore, page_count: int = 1, submitted_at: float | None = None, language: str = "en"
) -> JobRecord:
    record = make_record(page_count=page_count, submitted_at=submitted_at, language=language)
    await store.create(record, b"payload")
    runner.admit(record)

    return record


def start_running(runner: JobRunner, record: JobRecord) -> None:
    """Put a record in the seat the loop would give it, without driving the loop."""
    runner.admit(record)
    runner._running = runner._queue.popleft()


async def poll_until(condition: Callable[[], bool]) -> bool:
    """Give the runner's own task room to make progress, for a bounded number of turns."""
    for _ in range(POLL_ATTEMPTS):
        if condition():
            return True

        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    return False


async def drain_until_terminal(runner: JobRunner, store: JobStore, job_id: str) -> JobRecord:
    """Run the loop until one job reaches a terminal state, or give up."""
    await runner.start()
    try:
        finished = await poll_until(lambda: store.read(job_id).is_terminal)
        if not finished:
            raise AssertionError(f"job {job_id} never reached a terminal state")

        return store.read(job_id)
    finally:
        await runner.stop()


class TestPollHint:
    def test_the_hint_is_a_tenth_of_the_allowed_time_still_ahead(self):
        # When / Then
        assert poll_hint_seconds(180.0) == pytest.approx(18.0)

    def test_the_hint_never_asks_for_more_than_once_a_second(self):
        # When / Then
        assert poll_hint_seconds(0.0) == pytest.approx(1.0)

    def test_the_hint_never_leaves_a_finished_result_sitting(self):
        # When / Then
        assert poll_hint_seconds(100_000.0) == pytest.approx(30.0)


class TestAdmission:
    def test_a_submission_within_both_bounds_is_reserved(self, runner: JobRunner) -> None:
        # When / Then — no refusal
        runner.reserve(1)
        runner.release(1)

    def test_a_submission_beyond_the_document_bound_is_refused(
        self, runner: JobRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "OCR_JOB_QUEUE_MAX_DOCUMENTS", 2)
        for _ in range(2):
            runner.admit(make_record(page_count=1))

        # When / Then
        with pytest.raises(QueueFullError, match="documents are already waiting"):
            runner.reserve(1)

    def test_a_submission_beyond_the_page_bound_is_refused(
        self, runner: JobRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "OCR_JOB_QUEUE_MAX_PAGES", 10)
        runner.admit(make_record(page_count=8))

        # When / Then
        with pytest.raises(QueueFullError, match="queue bound of 10"):
            runner.reserve(3)

    def test_the_refusal_carries_a_retry_hint_from_the_time_already_waiting(
        self, runner: JobRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given: one page at the small engine's allowance is 112.95 s of waiting work
        monkeypatch.setattr(settings, "OCR_JOB_QUEUE_MAX_PAGES", 1)
        runner.admit(make_record(page_count=1, language="en"))

        # When
        with pytest.raises(QueueFullError) as exc_info:
            runner.reserve(1)

        # Then
        assert exc_info.value.retry_after_seconds == pytest.approx(
            settings.page_allowance_seconds(settings.model_pair("en")) / 10
        )

    def test_a_reservation_counts_against_the_bounds_before_the_record_is_written(
        self, runner: JobRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given — two submissions racing: the first is still being written to disk
        monkeypatch.setattr(settings, "OCR_JOB_QUEUE_MAX_DOCUMENTS", 1)
        runner.reserve(1)

        # When / Then
        with pytest.raises(QueueFullError):
            runner.reserve(1)

    def test_releasing_a_reservation_frees_the_place_again(
        self, runner: JobRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "OCR_JOB_QUEUE_MAX_DOCUMENTS", 1)
        runner.reserve(1)

        # When
        runner.release(1)

        # Then
        runner.reserve(1)

    def test_the_running_document_s_unread_pages_count_against_the_page_bound(
        self, runner: JobRunner, jobs_dir: Path
    ) -> None:
        # Given — a ten page document being read, three pages in
        _ = jobs_dir
        running = make_record(page_count=10)
        start_running(runner, running)
        write_progress(running.job_id, 3)

        # When / Then
        assert runner.pages_pending() == 7

    def test_a_finished_running_document_leaves_no_pages_pending(self, runner: JobRunner) -> None:
        # When / Then
        assert runner.pages_pending() == 0


class TestQueueView:
    def test_the_running_document_comes_first_and_positions_are_contiguous(
        self, runner: JobRunner, jobs_dir: Path
    ) -> None:
        # Given
        _ = jobs_dir
        running = make_record(page_count=4)
        first_waiting = make_record(page_count=2)
        second_waiting = make_record(page_count=3)
        start_running(runner, running)
        runner.admit(first_waiting)
        runner.admit(second_waiting)

        # When / Then
        assert runner.position_of(running.job_id) == 0
        assert runner.position_of(first_waiting.job_id) == 1
        assert runner.position_of(second_waiting.job_id) == 2
        assert runner.position_of(make_record().job_id) is None

    def test_pages_ahead_counts_the_running_remainder_and_everything_queued_before_it(
        self, runner: JobRunner, jobs_dir: Path
    ) -> None:
        # Given — a four page document one page in, then two waiting documents
        _ = jobs_dir
        running = make_record(page_count=4)
        start_running(runner, running)
        write_progress(running.job_id, 1)
        first_waiting = make_record(page_count=2)
        second_waiting = make_record(page_count=3)
        runner.admit(first_waiting)
        runner.admit(second_waiting)

        # When / Then
        assert runner.pages_ahead_of(running.job_id) == 0
        assert runner.pages_ahead_of(first_waiting.job_id) == 3
        assert runner.pages_ahead_of(second_waiting.job_id) == 5

    def test_the_time_still_ahead_is_each_document_s_unread_pages_at_its_own_engine_s_allowance(
        self, runner: JobRunner, jobs_dir: Path, off_family_language: str
    ) -> None:
        # Given: an English document one page into four, then an opted-in Russian and an English one
        _ = jobs_dir
        running = make_record(page_count=4, language="en")
        start_running(runner, running)
        write_progress(running.job_id, 1)
        russian = make_record(page_count=2, language=off_family_language)
        english = make_record(page_count=3, language="en")
        runner.admit(russian)
        runner.admit(english)
        small = settings.page_allowance_seconds(settings.model_pair("en"))
        server = settings.page_allowance_seconds(settings.model_pair(off_family_language))

        # When / Then
        assert runner.seconds_remaining_for(running.job_id) == pytest.approx(3 * small)
        assert runner.seconds_remaining_for(russian.job_id) == pytest.approx(3 * small + 2 * server)
        assert runner.seconds_remaining_for(english.job_id) == pytest.approx(6 * small + 2 * server)
        assert runner.seconds_pending() == pytest.approx(6 * small + 2 * server)

    def test_pages_ahead_of_work_the_runner_does_not_hold_is_everything_in_flight(self, runner: JobRunner) -> None:
        # Given
        runner.admit(make_record(page_count=2))

        # When / Then
        assert runner.pages_ahead_of("unknown-identifier--") == 2
        assert runner.seconds_remaining_for("unknown-identifier--") == 0.0

    def test_progress_is_only_reported_for_the_document_being_read(self, runner: JobRunner, jobs_dir: Path) -> None:
        # Given
        _ = jobs_dir
        waiting = make_record(page_count=3)
        runner.admit(waiting)
        write_progress(waiting.job_id, 2)

        # When / Then — a queued document has read nothing, whatever an old progress file says
        assert runner.pages_done_of(waiting.job_id) == 0

    def test_readiness_counters_report_what_is_waiting_and_running(self, runner: JobRunner) -> None:
        # Given
        runner.admit(make_record(page_count=1))
        runner.admit(make_record(page_count=1))

        # When / Then
        assert runner.documents_waiting() == 2
        assert runner.documents_running() == 0
        assert runner.pages_waiting() == 2


class TestReadingADocument:
    async def test_a_successful_read_uploads_the_markdown_then_records_success(
        self, runner: JobRunner, store: JobStore, results: FakeResultStore
    ) -> None:
        # Given
        record = await queue_job(runner, store, page_count=1)
        states_at_upload: list[str] = []
        original_upload = results.upload

        async def capture(job_id: str, markdown: str) -> JobResultLocation:
            states_at_upload.append(store.read(job_id).state)

            return await original_upload(job_id, markdown)

        # When
        with (
            patch.object(results, "upload", capture),
            patch(
                "src.service.job_runner.dispatch_ocr_request",
                AsyncMock(return_value=OcrResponseFactory.with_single_line(text="canary")),
            ),
        ):
            finished = await drain_until_terminal(runner, store, record.job_id)

        # Then — success is only recorded once the object is in the bucket
        assert states_at_upload == ["running"]
        assert finished.state == "succeeded"
        assert finished.result is not None
        assert results.objects[finished.result.key] == "## Page 1\ncanary\n"

    @pytest.mark.usefixtures("off_family_language")
    @pytest.mark.parametrize(("language", "measured"), [("en", 25.1), ("ru", 96.0)])
    async def test_the_reading_budget_is_the_page_count_times_its_own_engine_s_allowance(
        self, runner: JobRunner, store: JobStore, monkeypatch: pytest.MonkeyPatch, language: str, measured: float
    ) -> None:
        # Given — a document that waited far longer than its own reading ceiling, and
        # still inside the maximum lifetime, so nothing else touches it. ru is opted back in.
        monkeypatch.setattr(settings, "OCR_PAGE_ALLOWANCE_HEADROOM", 2.0)
        record = await queue_job(runner, store, page_count=4, submitted_at=time.time() - 5_000.0, language=language)
        dispatch = AsyncMock(return_value=OcrResponseFactory.with_single_line())

        # When
        with patch("src.service.job_runner.dispatch_ocr_request", dispatch):
            await drain_until_terminal(runner, store, record.job_id)

        # Then — the wait is not charged against it
        assert dispatch.call_args.args[4] == pytest.approx(4 * 2.0 * measured)

    async def test_the_submitting_surface_and_trace_context_reach_the_worker(
        self, runner: JobRunner, store: JobStore
    ) -> None:
        # Given
        record = make_record(surface="mcp", trace_carrier={"traceparent": "00-fake-01"})
        await store.create(record, b"payload")
        runner.admit(record)
        dispatch = AsyncMock(return_value=OcrResponseFactory.with_single_line())

        # When
        with patch("src.service.job_runner.dispatch_ocr_request", dispatch):
            await drain_until_terminal(runner, store, record.job_id)

        # Then
        assert dispatch.call_args.args[5] == "mcp"
        assert dispatch.call_args.args[6] == {"traceparent": "00-fake-01"}
        assert dispatch.call_args.args[7] == record.job_id

    async def test_the_submitted_quality_mode_reaches_the_worker(self, runner: JobRunner, store: JobStore) -> None:
        # Given
        record = make_record(quality="normal")
        await store.create(record, b"payload")
        runner.admit(record)
        dispatch = AsyncMock(return_value=OcrResponseFactory.with_single_line())

        # When
        with patch("src.service.job_runner.dispatch_ocr_request", dispatch):
            await drain_until_terminal(runner, store, record.job_id)

        # Then
        assert dispatch.call_args.args[3] == "normal"

    @pytest.mark.parametrize("straighten", [True, False])
    async def test_the_submitted_straighten_choice_reaches_the_worker(
        self, runner: JobRunner, store: JobStore, straighten: bool
    ) -> None:
        # Given
        record = make_record(straighten=straighten)
        await store.create(record, b"payload")
        runner.admit(record)
        dispatch = AsyncMock(return_value=OcrResponseFactory.with_single_line())

        # When
        with patch("src.service.job_runner.dispatch_ocr_request", dispatch):
            await drain_until_terminal(runner, store, record.job_id)

        # Then
        assert dispatch.call_args.args[8] is straighten

    async def test_documents_are_read_one_at_a_time_in_submission_order(
        self, runner: JobRunner, store: JobStore
    ) -> None:
        # Given
        first = await queue_job(runner, store)
        second = await queue_job(runner, store)
        third = await queue_job(runner, store)
        order: list[str] = []
        in_flight = 0
        peak = 0

        async def dispatch(_payload, _filename, _language, _quality, _budget, _surface, _carrier, job_id, straighten):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            order.append(job_id)
            await asyncio.sleep(0)
            in_flight -= 1

            return OcrResponseFactory.with_single_line()

        # When
        with patch("src.service.job_runner.dispatch_ocr_request", dispatch):
            await runner.start()
            try:
                assert await poll_until(lambda: len(order) == 3)
            finally:
                await runner.stop()

        # Then
        assert order == [first.job_id, second.job_id, third.job_id]
        assert peak == 1

    async def test_the_submitted_bytes_are_dropped_once_the_work_finishes(
        self, runner: JobRunner, store: JobStore, jobs_dir: Path
    ) -> None:
        # Given
        record = await queue_job(runner, store)

        # When
        with patch(
            "src.service.job_runner.dispatch_ocr_request",
            AsyncMock(return_value=OcrResponseFactory.with_single_line()),
        ):
            await drain_until_terminal(runner, store, record.job_id)

        # Then
        assert not (jobs_dir / f"{record.job_id}{INPUT_SUFFIX}").exists()


class TestDispatchOutcomes:
    @pytest.mark.parametrize(
        "failure",
        [
            OcrProcessingError("Request budget exhausted during inference"),
            OcrProcessingError("Worker did not stop within its reclamation grace"),
            OcrProcessingError("OCR worker process failed"),
        ],
    )
    async def test_every_reading_failure_is_recorded_with_the_ocr_failure_code(
        self, runner: JobRunner, store: JobStore, results: FakeResultStore, failure: OcrProcessingError
    ) -> None:
        # Given
        record = await queue_job(runner, store)

        # When
        with patch("src.service.job_runner.dispatch_ocr_request", AsyncMock(side_effect=failure)):
            finished = await drain_until_terminal(runner, store, record.job_id)

        # Then — no partial content, and no object left behind
        assert finished.state == "failed"
        assert finished.error_code == ERROR_CODE_OCR_FAILED
        assert finished.result is None
        assert finished.retryable is False
        assert results.objects == {}

    async def test_an_unexpected_failure_is_recorded_as_an_internal_error(
        self, runner: JobRunner, store: JobStore, results: FakeResultStore
    ) -> None:
        # Given
        record = await queue_job(runner, store)

        # When
        with patch("src.service.job_runner.dispatch_ocr_request", AsyncMock(side_effect=RuntimeError("boom"))):
            finished = await drain_until_terminal(runner, store, record.job_id)

        # Then
        assert finished.error_code == ERROR_CODE_INTERNAL
        assert "RuntimeError" in (finished.error_reason or "")
        assert results.objects == {}

    async def test_a_result_store_that_will_not_take_the_upload_fails_the_job_with_its_own_reason(
        self, runner: JobRunner, store: JobStore, results: FakeResultStore
    ) -> None:
        # Given
        results.upload_error = ResultStoreUnavailableError("could not write the result")
        record = await queue_job(runner, store)

        # When
        with patch(
            "src.service.job_runner.dispatch_ocr_request",
            AsyncMock(return_value=OcrResponseFactory.with_single_line()),
        ):
            finished = await drain_until_terminal(runner, store, record.job_id)

        # Then — distinguishable from a document the service could not read
        assert finished.state == "failed"
        assert finished.error_code == FAILURE_RESULT_STORE_UNAVAILABLE
        assert finished.retryable is True
        assert finished.result is None

    async def test_a_job_whose_bytes_vanished_before_it_ran_is_failed_rather_than_dispatched(
        self, runner: JobRunner, store: JobStore
    ) -> None:
        # Given
        record = await queue_job(runner, store)
        store.delete_input(record.job_id)
        dispatch = AsyncMock()

        # When
        with patch("src.service.job_runner.dispatch_ocr_request", dispatch):
            finished = await drain_until_terminal(runner, store, record.job_id)

        # Then
        assert finished.error_code == ERROR_CODE_INTERNAL
        dispatch.assert_not_awaited()

    async def test_a_job_cancelled_while_it_was_being_read_is_not_written_over(
        self, runner: JobRunner, store: JobStore
    ) -> None:
        # Given — the record turns cancelled while the dispatch is in flight
        record = await queue_job(runner, store)

        async def dispatch(*_args):
            current = store.read(record.job_id)
            store.cancel(current)

            raise OcrProcessingError("OCR worker process failed")

        # When
        with patch("src.service.job_runner.dispatch_ocr_request", dispatch):
            finished = await drain_until_terminal(runner, store, record.job_id)

        # Then
        assert finished.state == "cancelled"
        assert finished.error_code is None

    async def test_a_job_deleted_while_it_was_being_read_leaves_neither_a_record_nor_an_orphan(
        self, runner: JobRunner, store: JobStore, results: FakeResultStore
    ) -> None:
        # Given — the record is removed by a caller while the document is being read, so
        # by the time the result is written nothing is left to point at it
        record = await queue_job(runner, store)
        dispatched = asyncio.Event()

        async def dispatch(*_args):
            await store.delete(store.read(record.job_id))
            dispatched.set()

            return OcrResponseFactory.with_single_line()

        # When
        with patch("src.service.job_runner.dispatch_ocr_request", dispatch):
            await runner.start()
            try:
                assert await poll_until(dispatched.is_set)
                assert await poll_until(lambda: results.deleted != [])
            finally:
                await runner.stop()

        # Then — no record came back, and the object it would have named was cleaned up
        # rather than left in the bucket for the lifecycle rule to collect
        assert store.exists(record.job_id) is False
        assert results.deleted == [f"{record.job_id}.md"]
        assert results.objects == {}

    async def test_a_queued_job_whose_record_vanished_is_skipped(self, runner: JobRunner, store: JobStore) -> None:
        # Given
        record = await queue_job(runner, store)
        second = await queue_job(runner, store)
        await store.delete(record)
        dispatch = AsyncMock(return_value=OcrResponseFactory.with_single_line())

        # When
        with patch("src.service.job_runner.dispatch_ocr_request", dispatch):
            await drain_until_terminal(runner, store, second.job_id)

        # Then
        assert dispatch.await_count == 1

    async def test_a_queued_job_already_cancelled_is_never_dispatched(self, runner: JobRunner, store: JobStore) -> None:
        # Given
        record = await queue_job(runner, store)
        second = await queue_job(runner, store)
        store.cancel(record)
        dispatch = AsyncMock(return_value=OcrResponseFactory.with_single_line())

        # When
        with patch("src.service.job_runner.dispatch_ocr_request", dispatch):
            await drain_until_terminal(runner, store, second.job_id)

        # Then
        assert dispatch.await_count == 1


class TestCancellation:
    async def test_cancelling_waiting_work_removes_it_from_the_queue(self, runner: JobRunner, store: JobStore) -> None:
        # Given
        first = await queue_job(runner, store)
        second = await queue_job(runner, store)
        replace = MagicMock()

        # When
        with patch("src.service.job_runner.request_worker_replacement_for_cancel", replace):
            runner.cancel(store.read(first.job_id))

        # Then — the document behind it moves up, and no worker was replaced
        assert runner.documents_waiting() == 1
        assert runner.position_of(second.job_id) == 0
        assert store.read(first.job_id).state == "cancelled"
        replace.assert_not_called()

    async def test_cancelled_waiting_work_is_never_read(self, runner: JobRunner, store: JobStore) -> None:
        # Given
        cancelled = await queue_job(runner, store)
        survivor = await queue_job(runner, store)
        dispatch = AsyncMock(return_value=OcrResponseFactory.with_single_line())

        # When
        with patch("src.service.job_runner.request_worker_replacement_for_cancel", MagicMock()):
            runner.cancel(store.read(cancelled.job_id))

        with patch("src.service.job_runner.dispatch_ocr_request", dispatch):
            await drain_until_terminal(runner, store, survivor.job_id)

        # Then
        assert dispatch.await_count == 1
        assert dispatch.call_args.args[7] == survivor.job_id

    async def test_cancelling_work_behind_other_work_leaves_the_rest_in_order(
        self, runner: JobRunner, store: JobStore
    ) -> None:
        # Given — three queued documents, and the middle one is cancelled
        first = await queue_job(runner, store)
        middle = await queue_job(runner, store)
        last = await queue_job(runner, store)

        # When
        with patch("src.service.job_runner.request_worker_replacement_for_cancel", MagicMock()):
            runner.cancel(store.read(middle.job_id))

        # Then
        assert runner.position_of(first.job_id) == 0
        assert runner.position_of(last.job_id) == 1
        assert runner.position_of(middle.job_id) is None

    async def test_cancelling_dispatched_work_replaces_the_worker_once(
        self, runner: JobRunner, store: JobStore
    ) -> None:
        # Given
        record = await queue_job(runner, store)
        runner._running = runner._queue.popleft()
        runner._dispatched_job_id = record.job_id
        record.state = "running"
        record.started_at = time.time()
        store.write(record)
        replace = MagicMock()

        # When
        with patch("src.service.job_runner.request_worker_replacement_for_cancel", replace):
            runner.cancel(store.read(record.job_id))

        # Then
        replace.assert_called_once()
        assert store.read(record.job_id).state == "cancelled"

    async def test_the_next_document_waits_for_the_worker_a_cancel_is_replacing(
        self, runner: JobRunner, store: JobStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given: the first document is cancelled while it is read, and finishes on its own
        # before the replacement has killed its worker
        cancelled = await queue_job(runner, store)
        following = await queue_job(runner, store)
        kill_may_land = asyncio.Event()
        runner_is_waiting = asyncio.Event()
        pool_replaced: list[bool] = []
        replaced_at_dispatch: list[bool] = []

        async def replacement_that_lands_late() -> None:
            await kill_may_land.wait()
            pool_replaced.append(True)

        monkeypatch.setattr(ocr_service_module, "replace_worker_for_cancel", replacement_that_lands_late)
        real_wait = ocr_service_module.wait_for_worker_replacements

        async def observed_wait() -> None:
            if ocr_service_module._pending_replacements:
                runner_is_waiting.set()
            await real_wait()

        async def dispatch(_payload, _filename, _language, _quality, _budget, _surface, _carrier, job_id, _straighten):
            if job_id == cancelled.job_id:
                runner.cancel(store.read(job_id))
            else:
                replaced_at_dispatch.append(bool(pool_replaced))

            return OcrResponseFactory.with_single_line()

        with (
            patch("src.service.job_runner.dispatch_ocr_request", dispatch),
            patch("src.service.job_runner.wait_for_worker_replacements", observed_wait),
        ):
            await runner.start()
            try:
                # When: the runner reaches the next document while the kill has not landed
                assert await poll_until(lambda: runner_is_waiting.is_set() or replaced_at_dispatch != [])
                kill_may_land.set()
                assert await poll_until(lambda: store.read(following.job_id).is_terminal)
            finally:
                kill_may_land.set()
                await runner.stop()
                await real_wait()

        # Then: the next document went to the replaced, warm worker and was read
        assert replaced_at_dispatch == [True]
        assert store.read(following.job_id).state == "succeeded"
        assert store.read(cancelled.job_id).state == "cancelled"

    @pytest.mark.parametrize("bytes_read_before_the_cancel", [True, False])
    async def test_a_cancel_while_the_submitted_bytes_are_read_is_kept(
        self, runner: JobRunner, store: JobStore, monkeypatch: pytest.MonkeyPatch, bytes_read_before_the_cancel: bool
    ) -> None:
        # Given: the runner has taken the document and is awaiting its bytes when the cancel arrives
        record = await queue_job(runner, store)
        real_read_input = store.read_input
        dispatch = AsyncMock(return_value=OcrResponseFactory.with_single_line())
        replace = MagicMock()

        async def read_input_with_a_cancel_arriving(job_id: str) -> bytes:
            payload = await real_read_input(job_id) if bytes_read_before_the_cancel else b""
            runner.cancel(store.read(job_id))
            if bytes_read_before_the_cancel:
                return payload

            return await real_read_input(job_id)

        monkeypatch.setattr(store, "read_input", read_input_with_a_cancel_arriving)

        # When
        with (
            patch("src.service.job_runner.dispatch_ocr_request", dispatch),
            patch("src.service.job_runner.request_worker_replacement_for_cancel", replace),
        ):
            await runner.start()
            try:
                assert await poll_until(lambda: runner.documents_waiting() == 0 and runner.documents_running() == 0)
            finally:
                await runner.stop()

        # Then: the cancel stands, nothing was read, and no worker was killed for it
        finished = store.read(record.job_id)
        assert finished.state == "cancelled"
        assert finished.error_code is None
        dispatch.assert_not_awaited()
        replace.assert_not_called()

    async def test_cancelling_work_the_runner_no_longer_holds_replaces_nothing(
        self, runner: JobRunner, store: JobStore
    ) -> None:
        # Given — a record left waiting by a previous process, with an empty queue
        record = make_record(state="waiting")
        store.write(record)
        replace = MagicMock()

        # When
        with patch("src.service.job_runner.request_worker_replacement_for_cancel", replace):
            runner.cancel(record)

        # Then
        replace.assert_not_called()
        assert store.read(record.job_id).state == "cancelled"


class TestIdleTick:
    async def test_the_idle_tick_sweeps_expired_work_with_nobody_asking(
        self, runner: JobRunner, store: JobStore, results: FakeResultStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "OCR_JOB_RETENTION_SECONDS", 1.0)
        _ = results
        record = make_record(state="succeeded", finished_at=time.time() - 60.0)
        store.write(record)

        # When
        await runner._idle_tick()

        # Then
        assert store.exists(record.job_id) is False

    async def test_the_idle_tick_fails_work_past_its_maximum_lifetime(self, runner: JobRunner, store: JobStore) -> None:
        # Given
        record = make_record(state="running", submitted_at=time.time() - settings.OCR_JOB_MAX_LIFETIME_SECONDS - 1.0)
        store.write(record)

        # When
        await runner._idle_tick()

        # Then
        assert store.read(record.job_id).state == "failed"

    async def test_a_submission_wakes_the_runner_rather_than_waiting_for_the_tick(
        self, runner: JobRunner, store: JobStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given — an idle period far longer than this test would ever wait for
        monkeypatch.setattr("src.service.job_runner.IDLE_TICK_SECONDS", 3600.0)
        await runner.start()

        try:
            record = make_record()
            await store.create(record, b"payload")

            # When
            with patch(
                "src.service.job_runner.dispatch_ocr_request",
                AsyncMock(return_value=OcrResponseFactory.with_single_line()),
            ):
                runner.admit(record)
                assert await poll_until(lambda: store.read(record.job_id).is_terminal)
        finally:
            await runner.stop()

        # Then
        assert store.read(record.job_id).state == "succeeded"


class TestStartAndStop:
    async def test_stopping_a_runner_that_never_started_is_not_an_error(self, runner: JobRunner) -> None:
        # When / Then
        await runner.stop()

    async def test_starting_sweeps_before_taking_the_first_document(
        self, runner: JobRunner, store: JobStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "OCR_JOB_RETENTION_SECONDS", 1.0)
        expired = make_record(state="succeeded", finished_at=time.time() - 60.0)
        store.write(expired)

        # When
        await runner.start()
        await runner.stop()

        # Then
        assert store.exists(expired.job_id) is False


class TestCooperativeShutdown:
    async def test_the_loop_exits_on_the_stop_flag_even_if_the_cancellation_never_lands(
        self, runner: JobRunner, store: JobStore
    ) -> None:
        # Given — a runner whose task is asked to stop with the cancel suppressed, which
        # is what a cancellation delivered between the loop's own await points looks like
        await runner.start()
        task = runner._task
        assert task is not None

        # When
        runner._stopping = True
        runner._wakeup.set()

        assert await poll_until(task.done)

        # Then — the loop noticed the flag on its own, without being cancelled
        assert task.done() is True
        assert task.cancelled() is False
        await runner.stop()

    async def test_stopping_a_runner_that_is_reading_a_document_does_not_wait_for_it(
        self, runner: JobRunner, store: JobStore
    ) -> None:
        # Given — a document whose reading would never return on its own
        record = await queue_job(runner, store)
        reading = asyncio.Event()

        async def never_returns(*_args):
            reading.set()
            await asyncio.Event().wait()

        with patch("src.service.job_runner.dispatch_ocr_request", never_returns):
            await runner.start()
            await asyncio.wait_for(reading.wait(), timeout=DRAIN_TIMEOUT_SECONDS)

            # When
            await asyncio.wait_for(runner.stop(), timeout=DRAIN_TIMEOUT_SECONDS)

        # Then — the record is left non-terminal, which startup recovery then fails
        assert store.read(record.job_id).state == "running"


class TestReadingMetrics:
    async def test_the_reading_is_timed_under_the_surface_that_submitted_it(
        self, runner: JobRunner, store: JobStore
    ) -> None:
        # Given
        record = make_record(surface="mcp", language="pl")
        await store.create(record, b"payload")
        runner.admit(record)
        before = _duration_count("mcp", "pl")

        # When
        with patch(
            "src.service.job_runner.dispatch_ocr_request",
            AsyncMock(return_value=OcrResponseFactory.with_single_line(language="pl")),
        ):
            await drain_until_terminal(runner, store, record.job_id)

        # Then
        assert _duration_count("mcp", "pl") == before + 1

    async def test_a_failed_reading_is_timed_too(self, runner: JobRunner, store: JobStore) -> None:
        # Given
        record = await queue_job(runner, store)
        before = _duration_count("rest", "en")

        # When
        with patch(
            "src.service.job_runner.dispatch_ocr_request",
            AsyncMock(side_effect=OcrProcessingError("engine gave up")),
        ):
            await drain_until_terminal(runner, store, record.job_id)

        # Then
        assert _duration_count("rest", "en") == before + 1


def _duration_count(surface: str, language: str) -> float:
    """How many readings this label pair has timed, summed across the histogram's buckets."""
    child = OCR_DURATION_SECONDS.labels(surface=surface, language=language)

    return float(sum(bucket.get() for bucket in child._buckets))


class TestSinglePathToTheWorker:
    def test_only_the_runner_dispatches_to_the_worker(self):
        # Given — every promise the queue makes about what runs at once is only true
        # while one component decides it
        source_root = Path(__file__).resolve().parents[2] / "src"
        allowed = {"service/ocr_service.py", "service/job_runner.py"}

        # When
        callers = {
            path.relative_to(source_root).as_posix()
            for path in source_root.rglob("*.py")
            if "dispatch_ocr_request" in path.read_text(encoding="utf-8")
        }

        # Then
        assert callers == allowed

    def test_the_runner_is_the_only_holder_of_the_admission_gate(self):
        # Given — the gate is what enforces OCR_WORKER_COUNT, and it is acquired on the
        # runner's behalf inside the dispatch it is the only caller of
        source_root = Path(__file__).resolve().parents[2] / "src"

        # When
        holders = {
            path.relative_to(source_root).as_posix()
            for path in source_root.rglob("*.py")
            if "_admission_semaphore" in path.read_text(encoding="utf-8")
        }

        # Then
        assert holders == {"service/ocr_service.py"}


class TestTransitionLogging:
    async def test_a_full_lifecycle_produces_one_line_per_transition(
        self, runner: JobRunner, store: JobStore, results: FakeResultStore, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Given
        service = JobService(store, results, runner)
        caplog.set_level("INFO", logger="src.service.job_store")

        # When
        submitted = await service.submit(VALID_PNG_BYTES, "scan.png", "en", "high", "rest")
        with patch(
            "src.service.job_runner.dispatch_ocr_request",
            AsyncMock(return_value=OcrResponseFactory.with_single_line(text="canary text")),
        ):
            await drain_until_terminal(runner, store, submitted.job_id)

        # Then — waiting, running, succeeded, and nothing else
        lines = [record.getMessage() for record in caplog.records if record.getMessage().startswith("Job ")]
        assert len(lines) == 3
        assert lines[0].endswith("-> waiting (pages=1, reason=-)")
        assert lines[1].endswith("-> running (pages=1, reason=-)")
        assert lines[2].endswith("-> succeeded (pages=1, reason=-)")
        assert all(submitted.job_id in line for line in lines)

    async def test_no_transition_line_carries_text_an_address_or_a_credential(
        self,
        runner: JobRunner,
        store: JobStore,
        results: FakeResultStore,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "OCR_RESULT_S3_SECRET_KEY", "super-secret")
        service = JobService(store, results, runner)
        caplog.set_level("INFO", logger="src.service.job_store")

        # When
        submitted = await service.submit(VALID_PNG_BYTES, "scan.png", "en", "high", "rest")
        with patch(
            "src.service.job_runner.dispatch_ocr_request",
            AsyncMock(return_value=OcrResponseFactory.with_single_line(text="canary text")),
        ):
            await drain_until_terminal(runner, store, submitted.job_id)

        # Then
        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert "canary text" not in logged
        assert "http" not in logged
        assert "super-secret" not in logged

    async def test_a_terminal_line_names_the_reason(
        self, runner: JobRunner, store: JobStore, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Given
        record = await queue_job(runner, store)
        caplog.set_level("INFO", logger="src.service.job_store")

        # When
        with patch(
            "src.service.job_runner.dispatch_ocr_request",
            AsyncMock(side_effect=OcrProcessingError("engine gave up")),
        ):
            await drain_until_terminal(runner, store, record.job_id)

        # Then
        lines = [entry.getMessage() for entry in caplog.records if entry.getMessage().startswith("Job ")]
        assert lines[-1].endswith("-> failed (pages=1, reason=OCR_FAILED)")


class TestRunnerResilience:
    async def test_an_unexpected_failure_costs_one_turn_rather_than_every_turn_after_it(
        self, runner: JobRunner, store: JobStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given — the loop's own first idle tick raises from inside the sweep, which is a
        # failure no other path catches. The sweep start() runs is left alone, because a
        # jobs directory that cannot be read at boot is a configuration problem the
        # lifespan should surface rather than a turn the runner should survive.
        monkeypatch.setattr("src.service.job_runner.IDLE_TICK_SECONDS", 0.01)
        calls: list[int] = []
        original_sweep = store.sweep

        async def sweep_badly_once_inside_the_loop():
            calls.append(1)
            if len(calls) == 2:
                raise OSError("the jobs directory went away")

            await original_sweep()

        monkeypatch.setattr(store, "sweep", sweep_badly_once_inside_the_loop)
        record = make_record()
        await store.create(record, b"payload")

        # When — the runner starts, fails a turn, and is then given work
        with patch(
            "src.service.job_runner.dispatch_ocr_request",
            AsyncMock(return_value=OcrResponseFactory.with_single_line()),
        ):
            await runner.start()
            try:
                await poll_until(lambda: len(calls) >= 2)
                runner.admit(record)
                finished = await poll_until(lambda: store.read(record.job_id).is_terminal)
            finally:
                await runner.stop()

        # Then
        assert len(calls) >= 2
        assert finished is True
        assert store.read(record.job_id).state == "succeeded"
