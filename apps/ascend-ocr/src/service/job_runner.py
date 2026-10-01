import asyncio
import contextlib
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from src.api.exception_handlers import (
    ERROR_CODE_INTERNAL,
    ERROR_CODE_OCR_FAILED,
    JobNotFoundError,
    OcrProcessingError,
    QueueFullError,
)
from src.config.config import settings
from src.config.logging_config import get_logger
from src.model.ocr_models import FAILURE_RESULT_STORE_UNAVAILABLE, JobRecord
from src.observability.metrics import (
    JOB_QUEUE_DOCUMENTS,
    JOB_QUEUE_PAGES,
    JOB_QUEUE_WAIT_SECONDS,
    JOBS_RETAINED,
    OCR_DURATION_SECONDS,
)
from src.service.job_store import JobStore, log_transition, read_progress
from src.service.ocr_service import (
    dispatch_ocr_request,
    request_worker_replacement_for_cancel,
    wait_for_worker_replacements,
)
from src.service.result_store import ResultStoreUnavailableError, render_markdown

if TYPE_CHECKING:
    from src.service.result_store import ResultWriter

logger = get_logger(__name__)

# How often the runner sweeps while nothing is queued, so expiry never waits for a
# caller to arrive. A submission wakes it immediately, so this is the idle period only.
IDLE_TICK_SECONDS: Final[float] = 5.0
# The hint asks a caller to wake about ten times across the allowed time still ahead of it.
POLL_HINT_WAKES_PER_WAIT: Final[float] = 10.0
POLL_HINT_MIN_SECONDS: Final[float] = 1.0
POLL_HINT_MAX_SECONDS: Final[float] = 30.0


@dataclass(frozen=True, slots=True)
class QueueEntry:
    job_id: str
    page_count: int
    page_allowance_seconds: float


def poll_hint_seconds(seconds_remaining: float) -> float:
    """Return how long a caller should wait before reading a non-terminal state again."""
    hint = seconds_remaining / POLL_HINT_WAKES_PER_WAIT

    return min(max(hint, POLL_HINT_MIN_SECONDS), POLL_HINT_MAX_SECONDS)


class JobRunner:
    """The single consumer of the queue, and the only path from a submission to the worker.

    Everything this module promises about what runs, what waits and for how long is only
    true because one component decides it, so nothing else dispatches to the worker.
    """

    def __init__(self, store: JobStore, results: "ResultWriter") -> None:
        self._store = store
        self._results = results
        self._queue: deque[QueueEntry] = deque()
        self._running: QueueEntry | None = None
        self._dispatched_job_id: str | None = None
        self._reserved_pages: int = 0
        self._reserved_documents: int = 0
        self._wakeup = asyncio.Event()
        self._stopping = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._store.sweep()
        self._stopping = False
        self._task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        """Stop taking documents, and abandon the one being read rather than waiting for it.

        Both halves are needed. The flag and the wake-up are what make the loop exit
        promptly and deterministically, because a cancellation delivered while the loop
        is between its own await points is not guaranteed to reach it at all. The cancel
        is what stops a document already in flight, which would otherwise hold shutdown
        for as long as the whole document takes to read.
        """
        if self._task is None:
            return

        self._stopping = True
        self._wakeup.set()
        task, self._task = self._task, None
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def reserve(self, page_count: int) -> None:
        """Hold a place in the queue for a submission that is still being written to disk.

        Raises:
            QueueFullError: when admitting the document would exceed either bound. The
                check and the reservation happen without awaiting, so two submissions
                racing each other cannot both pass it.
        """
        if self.documents_waiting() + self._reserved_documents >= settings.OCR_JOB_QUEUE_MAX_DOCUMENTS:
            raise QueueFullError(
                f"{settings.OCR_JOB_QUEUE_MAX_DOCUMENTS} documents are already waiting",
                self._retry_after_seconds(),
            )

        pending = self.pages_pending() + self._reserved_pages
        if pending + page_count > settings.OCR_JOB_QUEUE_MAX_PAGES:
            raise QueueFullError(
                f"{pending} pages are already waiting, and {page_count} more would exceed "
                f"the queue bound of {settings.OCR_JOB_QUEUE_MAX_PAGES}",
                self._retry_after_seconds(),
            )

        self._reserved_pages += page_count
        self._reserved_documents += 1

    def release(self, page_count: int) -> None:
        self._reserved_pages -= page_count
        self._reserved_documents -= 1

    def admit(self, record: JobRecord) -> None:
        """Put a written record into the queue and wake the runner."""
        self._queue.append(
            QueueEntry(
                job_id=record.job_id,
                page_count=record.page_count,
                page_allowance_seconds=_page_allowance_of(record),
            )
        )
        self._publish_queue_gauges()
        self._wakeup.set()

    def documents_waiting(self) -> int:
        return len(self._queue)

    def documents_running(self) -> int:
        return 0 if self._running is None else 1

    def pages_waiting(self) -> int:
        return sum(entry.page_count for entry in self._queue)

    def pages_pending(self) -> int:
        """Pages that must be read before a document submitted now could start.

        Counts the running document's unread pages as well as the waiting ones, because
        the wait the page bound promises is the whole of what is ahead.
        """
        return self.pages_waiting() + self._running_pages_remaining()

    def entries_in_flight(self) -> list[tuple[QueueEntry, str]]:
        """Return the running document first, then the waiting ones in submission order."""
        running = [] if self._running is None else [(self._running, "running")]

        return running + [(entry, "waiting") for entry in self._queue]

    def position_of(self, job_id: str) -> int | None:
        for position, (entry, _state) in enumerate(self.entries_in_flight()):
            if entry.job_id == job_id:
                return position

        return None

    def pages_ahead_of(self, job_id: str) -> int:
        """Pages that will be read before this document starts, zero once it is running."""
        ahead = 0
        for entry, state in self.entries_in_flight():
            if entry.job_id == job_id:
                return ahead

            ahead += self._remaining_pages_of(entry, state)

        return ahead

    def seconds_remaining_for(self, job_id: str) -> float:
        """The allowed time of everything ahead of this document plus its own unread pages."""
        allowed = 0.0
        for entry, state in self.entries_in_flight():
            allowed += self._remaining_seconds_of(entry, state)
            if entry.job_id == job_id:
                return allowed

        return 0.0

    def seconds_pending(self) -> float:
        """The allowed time of every unread page in flight, which a submission now would wait behind."""
        return sum(self._remaining_seconds_of(entry, state) for entry, state in self.entries_in_flight())

    def pages_done_of(self, job_id: str) -> int:
        if self._running is not None and self._running.job_id == job_id:
            return read_progress(job_id)

        return 0

    def cancel(self, record: JobRecord) -> None:
        """Stop work that has not finished, and make sure a running document really stops.

        The record reads cancelled when this returns. The worker reading a dispatched document
        is replaced in the background, and readiness reports not-ready until it is. A document
        taken from the queue but not yet dispatched is never started, so no worker is replaced.
        """
        self._remove_queued(record.job_id)
        was_dispatched = self._dispatched_job_id == record.job_id
        self._store.cancel(record)

        if was_dispatched:
            request_worker_replacement_for_cancel()

    async def _run_forever(self) -> None:
        while not self._stopping:
            try:
                await self._take_one_turn()
            except Exception:
                # A runner that dies takes the whole service's throughput with it while
                # /ready still reports the service able to take work, so an unexpected
                # failure costs one turn rather than every turn after it. Waiting before
                # the next turn is what stops a failure that repeats instantly from
                # becoming a hot loop.
                logger.exception("The job runner hit an unexpected failure, continuing with the next turn")
                await self._wait_for_work()

    async def _take_one_turn(self) -> None:
        await wait_for_worker_replacements()
        entry = self._queue.popleft() if self._queue else None
        if entry is None:
            await self._idle_tick()

            return

        self._publish_queue_gauges()
        await self._run_one(entry)

    async def _idle_tick(self) -> None:
        await self._store.sweep()
        JOBS_RETAINED.set(self._store.retained_count())
        await self._wait_for_work()

    async def _wait_for_work(self) -> None:
        """Wait for a submission, or for the next sweep, whichever arrives first.

        `asyncio.wait` reports a timeout by returning rather than by raising, so nothing
        here has to tell a timeout apart from a cancellation, which is exactly the
        confusion that would otherwise let a shutdown be swallowed.
        """
        waiter = asyncio.ensure_future(self._wakeup.wait())
        try:
            await asyncio.wait((waiter,), timeout=IDLE_TICK_SECONDS)
        finally:
            waiter.cancel()
            self._wakeup.clear()

    async def _run_one(self, entry: QueueEntry) -> None:
        record = self._claim(entry.job_id)
        if record is None:
            return

        self._running = entry
        try:
            await self._read_document(record)
        finally:
            self._running = None
            self._publish_queue_gauges()

    def _claim(self, job_id: str) -> JobRecord | None:
        """Return the record to read, or nothing when it was cancelled or removed while queued."""
        try:
            record = self._store.read(job_id)
        except JobNotFoundError:
            return None

        return record if record.state == "waiting" else None

    async def _read_document(self, record: JobRecord) -> None:
        try:
            payload = await self._store.read_input(record.job_id)
        except JobNotFoundError:
            self._finish_failed(record, ERROR_CODE_INTERNAL, "The submitted bytes were no longer held")

            return

        started_record = self._mark_running(record.job_id)
        if started_record is None:
            return

        record = started_record
        self._dispatched_job_id = record.job_id
        started = time.monotonic()
        try:
            result = await dispatch_ocr_request(
                payload,
                record.filename,
                record.language,
                record.quality,
                record.page_count * _page_allowance_of(record),
                record.surface,
                record.trace_carrier,
                record.job_id,
                record.straighten,
            )
        except OcrProcessingError as exc:
            self._finish_failed(record, ERROR_CODE_OCR_FAILED, str(exc))

            return
        except Exception as exc:
            logger.exception("Unexpected failure reading job %s", record.job_id)
            self._finish_failed(record, ERROR_CODE_INTERNAL, f"Unexpected failure: {type(exc).__name__}")

            return
        finally:
            self._dispatched_job_id = None
            # Still labelled by the surface the document was submitted on, so the metric
            # means what it meant before a submission and its reading came apart.
            OCR_DURATION_SECONDS.labels(surface=record.surface, language=record.language).observe(
                time.monotonic() - started
            )

        await self._store_result(record, result.processing_time_seconds, render_markdown(result))

    async def _store_result(self, record: JobRecord, processing_time_seconds: float, markdown: str) -> None:
        try:
            location = await self._results.upload(record.job_id, markdown)
        except ResultStoreUnavailableError as exc:
            self._finish_failed(record, FAILURE_RESULT_STORE_UNAVAILABLE, str(exc))

            return

        current = self._current_if_unfinished(record.job_id)
        if current is None:
            # Cancelled or removed while its result was being written. The object is an
            # orphan the moment nothing records its key, and this is the last place that
            # key is known, so it goes now rather than waiting for the bucket's own
            # lifecycle rule to collect it.
            await asyncio.to_thread(self._results.delete_result, location.key)

            return

        self._store.succeed(current, location, processing_time_seconds)

    def _mark_running(self, job_id: str) -> JobRecord | None:
        """Start the record, or return nothing when a cancel or a sweep finished it first."""
        started_at = time.time()
        record = self._store.start(job_id, started_at)
        if record is None:
            return None

        JOB_QUEUE_WAIT_SECONDS.observe(max(started_at - record.submitted_at, 0.0))
        log_transition(record)

        return record

    def _finish_failed(self, record: JobRecord, code: str, detail: str) -> None:
        current = self._current_if_unfinished(record.job_id)
        if current is None:
            return

        self._store.fail(current, code, detail)

    def _current_if_unfinished(self, job_id: str) -> JobRecord | None:
        """Re-read the record, so a cancel or a lifetime sweep is never written over."""
        try:
            current = self._store.read(job_id)
        except JobNotFoundError:
            return None

        return None if current.is_terminal else current

    def _remove_queued(self, job_id: str) -> bool:
        for entry in self._queue:
            if entry.job_id != job_id:
                continue

            self._queue.remove(entry)
            self._publish_queue_gauges()

            return True

        return False

    def _running_pages_remaining(self) -> int:
        if self._running is None:
            return 0

        return self._remaining_pages_of(self._running, "running")

    def _remaining_pages_of(self, entry: QueueEntry, state: str) -> int:
        if state != "running":
            return entry.page_count

        return max(entry.page_count - read_progress(entry.job_id), 0)

    def _remaining_seconds_of(self, entry: QueueEntry, state: str) -> float:
        return self._remaining_pages_of(entry, state) * entry.page_allowance_seconds

    def _retry_after_seconds(self) -> float:
        return poll_hint_seconds(self.seconds_pending())

    def _publish_queue_gauges(self) -> None:
        JOB_QUEUE_DOCUMENTS.set(self.documents_waiting())
        JOB_QUEUE_PAGES.set(self.pages_waiting())


def _page_allowance_of(record: JobRecord) -> float:
    return settings.page_allowance_seconds(settings.model_pair(record.language))
