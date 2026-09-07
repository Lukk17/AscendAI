import asyncio
import multiprocessing
import os
import re
import tempfile
import time
from collections import OrderedDict
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any, cast

from paddleocr import PaddleOCR

from src.api.exception_handlers import FileSizeExceededError, OcrProcessingError, UnsupportedFileTypeError
from src.config.config import settings
from src.config.cpu_limits import apply_cpu_thread_limit
from src.config.logging_config import get_logger, setup_logging
from src.model.ocr_models import OcrJsonResponse, OcrPageResult, OcrTextLine
from src.observability.metrics import (
    ENGINE_CACHE_EVICTIONS_TOTAL,
    ENGINE_WARMUP_DURATION_SECONDS,
    OCR_DEADLINE_STOPS_TOTAL,
    OCR_PAGE_DURATION_SECONDS,
    OCR_QUEUE_DEPTH,
    OCR_QUEUE_WAIT_SECONDS,
    POOL_REBUILDS_TOTAL,
    WORKER_REPLACEMENTS_TOTAL,
)
from src.observability.tracing import configure_worker_tracing, extract_trace_context, get_tracer

logger = get_logger(__name__)
tracer = get_tracer()
# Runs once per process (main process and each spawned worker re-import this module
# fresh). setup_logging() must run first, because a spawned worker is a fresh
# interpreter that never executes create_app()'s own setup_logging() call. Without this,
# its root logger has no handler, so every log call the worker makes is silently
# dropped instead of reaching the container's log stream, including
# apply_cpu_thread_limit()'s own line, since that call happens right here at import
# time, before the pool initializer (_warm_worker_engine) ever runs.
# apply_cpu_thread_limit() must then run before _get_engine() ever constructs a
# PaddleOCR instance, so the cap is in place before any thread pool it configures gets
# created.
setup_logging()
apply_cpu_thread_limit()

_SAFE_EXT_PATTERN = re.compile(r"^\.[A-Za-z0-9]{1,8}$")


class OcrDeadlineExceededError(Exception):
    """Raised inside the worker when a request's budget expires before or during inference."""


class OcrService:
    def __init__(self) -> None:
        self._engines: OrderedDict[str, PaddleOCR] = OrderedDict()

    def process_file(
        self,
        file_bytes: bytes,
        filename: str,
        language: str,
        trace_carrier: dict[str, str] | None = None,
        budget_seconds: float | None = None,
    ) -> OcrJsonResponse:
        start_time: float = time.monotonic()
        engine: PaddleOCR = self._get_engine(language)
        deadline: float | None = time.monotonic() + budget_seconds if budget_seconds is not None else None

        file_ext = _safe_suffix(filename)
        os.makedirs(settings.OCR_SCRATCH_DIR, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=settings.OCR_SCRATCH_DIR, suffix=file_ext, delete=False) as temp_file:
            temp_file.write(file_bytes)
            temp_file_path: str = temp_file.name

        # trace_carrier, when present, was produced by inject_trace_context() in the
        # process that submitted this call. Extracting it here reattaches this span to
        # that request's trace instead of starting an orphaned one, since this method
        # itself runs inside a separate OCR worker process (see start_worker_pool).
        parent_context = extract_trace_context(trace_carrier) if trace_carrier else None

        try:
            with tracer.start_as_current_span(
                "ascend-ocr.engine.predict",
                context=parent_context,
                attributes={"language": language},
            ):
                pages: list[OcrPageResult] = self._predict_pages(engine, temp_file_path, deadline)
        finally:
            # A removal failure here must never replace whatever exception this method
            # is already propagating (Python re-raises whichever exception a `finally`
            # itself raises, discarding the original) — found live, on Windows, where a
            # library that still held the file open turned a clean deadline-exceeded
            # error into a confusing PermissionError. sweep_scratch_dir reclaims
            # anything left behind by age, so leaving the file behind here is safe.
            try:
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
            except OSError:
                logger.warning("Failed to remove scratch file after processing: %s", temp_file_path)

        elapsed: float = round(time.monotonic() - start_time, 3)

        return OcrJsonResponse(
            filename=filename,
            language=language,
            pages=pages,
            processing_time_seconds=elapsed,
        )

    def _predict_pages(self, engine: PaddleOCR, path: str, deadline: float | None) -> list[OcrPageResult]:
        # predict_iter() is what predict() itself is built on (predict() is just
        # list(predict_iter(...))): switching to the generator form gives one checkpoint
        # per page, which is the only seam the library offers a cooperative deadline.
        # The check runs before pulling the next item, i.e. before that page's own
        # inference starts, not after — next(iterator) is what actually does the work.
        iterator = iter(engine.predict_iter(path))
        pages: list[OcrPageResult] = []
        page_number = 0

        while True:
            if deadline is not None and time.monotonic() >= deadline:
                raise OcrDeadlineExceededError(f"Budget exhausted after {page_number} of the document's pages")

            page_start = time.monotonic()
            remaining_budget = deadline - page_start if deadline is not None else None
            try:
                page_data = next(iterator)
            except StopIteration:
                break

            page_number += 1
            with tracer.start_as_current_span(
                "ascend-ocr.engine.predict.page",
                attributes={
                    "page_index": page_number,
                    "remaining_budget_seconds": round(remaining_budget, 3) if remaining_budget is not None else -1.0,
                },
            ):
                OCR_PAGE_DURATION_SECONDS.observe(time.monotonic() - page_start)
                if isinstance(page_data, dict):
                    pages.append(OcrPageResult(page_number=page_number, lines=self._extract_text_lines(page_data)))

        return pages

    def warm_up_engine(self, language: str) -> None:
        logger.info("Warming up OCR engine for language: %s", language)
        start = time.monotonic()

        with tracer.start_as_current_span(
            "ascend-ocr.engine.warmup",
            attributes={"language": language},
        ):
            self._get_engine(language)

        ENGINE_WARMUP_DURATION_SECONDS.labels(language=language).observe(time.monotonic() - start)

    def _get_engine(self, language: str) -> PaddleOCR:
        if language not in settings.SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {language!r}")

        cached = self._engines.get(language)
        if cached is not None:
            self._engines.move_to_end(language)

            return cached

        engine_kwargs: dict[str, object] = {"lang": language, "enable_mkldnn": False}
        if settings.OCR_DETECTOR_MAX_SIDE is not None:
            # Detection is otherwise configured with a minimum-side limit, which only
            # ever scales an image up, so every real page reaches the detector at its
            # full rendered resolution. "max" bounds the longest side instead, which is
            # the fix the measured memory cost points at (design.md Decision 11).
            engine_kwargs["text_det_limit_type"] = "max"
            engine_kwargs["text_det_limit_side_len"] = settings.OCR_DETECTOR_MAX_SIDE

        engine = PaddleOCR(**engine_kwargs)
        self._engines[language] = engine
        self._evict_if_over_capacity()

        return engine

    def _evict_if_over_capacity(self) -> None:
        while len(self._engines) > settings.ENGINE_CACHE_MAX_SIZE:
            evicted_lang, _ = self._engines.popitem(last=False)
            ENGINE_CACHE_EVICTIONS_TOTAL.labels(language=evicted_lang).inc()
            logger.info("Evicted engine for language %s (cache full)", evicted_lang)

    def _extract_text_lines(self, page_data: dict[str, object]) -> list[OcrTextLine]:
        rec_texts = cast(Iterable[Any], page_data.get("rec_texts", []))
        rec_scores = cast(Iterable[Any], page_data.get("rec_scores", []))
        dt_polys = cast(Iterable[Any], page_data.get("dt_polys", []))

        return [
            OcrTextLine(
                text=str(text),
                confidence=float(score),
                bounding_box=_convert_polygon(box),
            )
            for text, score, box in zip(rec_texts, rec_scores, dt_polys, strict=False)
        ]


def _safe_suffix(filename: str) -> str:
    candidate = os.path.splitext(filename)[1]
    if _SAFE_EXT_PATTERN.match(candidate):
        return candidate

    return ""


def _convert_polygon(polygon: Any) -> list[list[float]]:
    # PaddleOCR returns dt_polys as numpy arrays. `if not array` triggers numpy's
    # "truth value is ambiguous" ValueError on arrays with more than one element,
    # so explicit None + length checks instead of falsy truthiness.
    if polygon is None:
        return []

    try:
        if len(polygon) == 0:
            return []

        return [[float(point[0]), float(point[1])] for point in polygon]
    except (TypeError, IndexError, ValueError):
        return []


ocr_service = OcrService()

_process_pool: ProcessPoolExecutor | None = None
_pool_generation: int = 0
_admission_semaphore: asyncio.Semaphore = asyncio.Semaphore(settings.OCR_WORKER_COUNT)
_queue_depth: int = 0
# Keyed by a private token rather than a single shared scalar: OCR_WORKER_COUNT jobs
# can be in flight at once, each running _run_and_reclaim concurrently, and a single
# shared deadline would have one call's own finally overwrite or erase another's,
# silently blinding is_job_overrunning() to whichever job did not start or finish
# last (see _run_and_reclaim).
_active_deadlines: dict[object, float] = {}
_rebuild_lock: asyncio.Lock = asyncio.Lock()
_consecutive_rebuild_failures: int = 0


def start_worker_pool() -> bool:
    """Start (or replace) the OCR worker process pool and block until it has warmed up.

    PaddleOCR's CPU inference holds the GIL almost continuously for the entire
    duration of a call, so running it via a thread (asyncio.to_thread) freezes this
    process's own asyncio event loop for as long as inference runs. Running it in a
    separate OS process instead gives it its own GIL, so the event loop stays free to
    service other requests (downloads, health checks) while inference is in flight.

    Returns:
        True if the pool's initializer warmed up successfully, False if it left the
        pool broken (caller decides how to count that towards the rebuild cap).
    """
    global _process_pool, _pool_generation, _admission_semaphore, _queue_depth  # noqa: PLW0603
    _process_pool = ProcessPoolExecutor(
        max_workers=settings.OCR_WORKER_COUNT,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_warm_worker_engine,
        initargs=(settings.DEFAULT_LANGUAGE,),
    )
    _pool_generation += 1
    # Tied to the same setting and rebuilt alongside the pool so the two can never
    # disagree about how many jobs may run at once (see settings.OCR_WORKER_COUNT).
    _admission_semaphore = asyncio.Semaphore(settings.OCR_WORKER_COUNT)
    _queue_depth = 0

    # ProcessPoolExecutor spawns a worker per submit() call only when no worker is
    # already idle (see _adjust_process_count in the concurrent.futures.process
    # stdlib module), so one submission forces exactly one worker into existence, not
    # max_workers. Submitting every warm-up task before collecting any result keeps
    # the idle count at zero for the whole batch, forcing one worker per task, up to
    # OCR_WORKER_COUNT, and blocking here until every one of them has finished
    # warming the default-language engine. Without this, workers beyond the first are
    # only spawned lazily by real concurrent traffic, and each then pays its own
    # warm-up cost (seconds, per ENGINE_WARMUP_DURATION_SECONDS) inside that caller's
    # own request instead of at startup — the exact "discover it under load" failure
    # mode the worker-count memory budget exists to avoid.
    warmup_futures = [_process_pool.submit(_noop_task) for _ in range(settings.OCR_WORKER_COUNT)]
    try:
        for future in warmup_futures:
            future.result()
    except BrokenProcessPool:
        # The initializer (_warm_worker_engine) raised, so the pool considers itself
        # broken and every future submission will raise this same exception. Log and
        # return instead of letting it propagate: this runs from the FastAPI lifespan,
        # and a startup exception there kills the whole container before /health or
        # /ready can ever answer. Leaving it unwarm here is enough — is_engine_warm()
        # never observed a successful warm-up, so /ready honestly reports not-ready,
        # and a real OCR request against the broken pool surfaces as a handled,
        # rebuild-triggering failure rather than a crash.
        logger.exception("OCR worker pool failed to warm up; the pool is unusable until it is rebuilt")

        return False

    return True


def stop_worker_pool() -> None:
    global _process_pool  # noqa: PLW0603  module-level pool reassigned once at shutdown
    if _process_pool is not None:
        _process_pool.shutdown(wait=True)
        _process_pool = None


def get_process_pool() -> ProcessPoolExecutor:
    if _process_pool is None:
        raise RuntimeError("OCR worker pool is not initialised")

    return _process_pool


def get_pool_generation() -> int:
    return _pool_generation


def get_queue_depth() -> int:
    return _queue_depth


def is_rebuild_in_progress() -> bool:
    return _rebuild_lock.locked()


def is_job_overrunning() -> bool:
    """Report whether any currently in-flight job has run past its own deadline.

    Checks every job tracked in _active_deadlines, not just the most recent one,
    because OCR_WORKER_COUNT jobs can be in flight at once.
    """
    now = time.monotonic()

    return any(now > deadline for deadline in _active_deadlines.values())


def is_pool_usable() -> bool:
    return _consecutive_rebuild_failures < settings.OCR_POOL_REBUILD_MAX_CONSECUTIVE


def is_accepting_work() -> bool:
    return is_pool_usable() and not is_rebuild_in_progress() and not is_job_overrunning()


def _reset_rebuild_failures() -> None:
    global _consecutive_rebuild_failures  # noqa: PLW0603
    _consecutive_rebuild_failures = 0


async def _rebuild_pool(observed_generation: int, reason: str) -> None:
    """Replace the worker pool. A no-op if another caller already rebuilt it first."""
    global _consecutive_rebuild_failures  # noqa: PLW0603
    async with _rebuild_lock:
        if _pool_generation != observed_generation:
            # Someone else already rebuilt past the pool this caller observed as dead;
            # rebuilding again would be a second, redundant rebuild for one failure.
            return

        if not is_pool_usable():
            logger.error(
                "OCR worker pool rebuild abandoned after %d consecutive failures", _consecutive_rebuild_failures
            )

            return

        logger.warning(
            "Rebuilding OCR worker pool (reason=%s, consecutive_failures=%d)", reason, _consecutive_rebuild_failures
        )
        loop = asyncio.get_running_loop()
        # Offloaded like start_worker_pool() below, not called directly: shutdown(wait=True)
        # blocks until every currently in-flight work item across every worker finishes, not
        # only the one that triggered this rebuild (ProcessPoolExecutor has no per-worker
        # teardown). Calling it directly here would freeze this coroutine's own event loop
        # thread for that whole span — bounded by roughly one page's own inference time when
        # OCR_WORKER_COUNT is 1, since there is never a second job to wait on, but bounded by
        # nothing shorter than another worker's own full budget once a second worker exists.
        await loop.run_in_executor(None, stop_worker_pool)
        warmed = await loop.run_in_executor(None, start_worker_pool)

        if warmed:
            POOL_REBUILDS_TOTAL.labels(reason=reason, outcome="ok").inc()
        else:
            _consecutive_rebuild_failures += 1
            POOL_REBUILDS_TOTAL.labels(reason=reason, outcome="failed").inc()


async def _await_admission(effective_budget: float, arrival: float, surface: str) -> None:
    """Wait for a free worker permit, counting the wait against the request's own budget.

    Raises:
        OcrProcessingError: if the budget expires before a permit is granted.
    """
    global _queue_depth  # noqa: PLW0603
    _queue_depth += 1
    OCR_QUEUE_DEPTH.set(_queue_depth)
    try:
        remaining = effective_budget - (time.monotonic() - arrival)
        try:
            await asyncio.wait_for(_admission_semaphore.acquire(), timeout=max(remaining, 0.0))
        except TimeoutError:
            OCR_DEADLINE_STOPS_TOTAL.labels(surface=surface).inc()
            raise OcrProcessingError("Request budget exhausted while waiting for a worker") from None
        finally:
            OCR_QUEUE_WAIT_SECONDS.observe(time.monotonic() - arrival)
    finally:
        _queue_depth -= 1
        OCR_QUEUE_DEPTH.set(_queue_depth)


async def _run_and_reclaim(
    file_bytes: bytes,
    filename: str,
    language: str,
    trace_carrier: dict[str, str] | None,
    remaining: float,
    surface: str,
) -> OcrJsonResponse:
    """Dispatch to the worker pool, replacing it if the worker fails to stop in time.

    Raises:
        OcrProcessingError: on a worker that overran its reclamation grace, a broken
            pool, a pool caught mid-rebuild by a concurrent request, or a genuine OCR
            engine failure.
    """
    worker_budget = max(remaining - settings.OCR_DISPATCH_MARGIN_SECONDS, 0.0)
    observed_generation = _pool_generation
    loop = asyncio.get_running_loop()

    dispatch_start = time.monotonic()
    # A private token, not this job's own future or id(), so two calls that happen to
    # compute the exact same deadline float can never be confused for one another.
    deadline_token = object()
    _active_deadlines[deadline_token] = dispatch_start + remaining
    try:
        wait_budget = remaining + settings.OCR_RECLAMATION_GRACE_SECONDS

        try:
            # get_process_pool() is inside this try, not before it, so a request that
            # lands in the brief window between a background rebuild tearing the pool
            # down and standing the replacement back up (see _rebuild_pool) gets the
            # same clean OcrProcessingError as any other dispatch failure, rather than
            # an unhandled RuntimeError.
            pool = get_process_pool()
            # executor.submit() (called synchronously inside run_in_executor, before
            # it returns a future) raises BrokenProcessPool immediately when the pool
            # was already broken at submission time, rather than surfacing it through
            # the awaited future — a worker killed between requests is caught here,
            # not below. A worker that dies while this specific call is in flight still
            # surfaces the same exception through the await instead.
            future = loop.run_in_executor(
                pool, run_ocr_in_worker, file_bytes, filename, language, trace_carrier, worker_budget
            )
            result = await asyncio.wait_for(future, timeout=wait_budget)
        except OcrDeadlineExceededError as exc:
            # The normal, expected stop: the worker observed its own deadline between
            # pages and returned on its own, so no replacement is needed (Decision 3).
            OCR_DEADLINE_STOPS_TOTAL.labels(surface=surface).inc()
            logger.info(
                "Request stopped by its own deadline (budget=%.3fs, elapsed=%.3fs): %s",
                remaining,
                time.monotonic() - dispatch_start,
                exc,
            )
            raise OcrProcessingError(f"Request budget exhausted during inference: {exc}") from None
        except TimeoutError:
            OCR_DEADLINE_STOPS_TOTAL.labels(surface=surface).inc()
            WORKER_REPLACEMENTS_TOTAL.inc()
            logger.warning(
                "Worker replaced: did not stop within its reclamation grace "
                "(budget=%.3fs, elapsed=%.3fs, wait_budget=%.3fs)",
                remaining,
                time.monotonic() - dispatch_start,
                wait_budget,
            )
            await _rebuild_pool(observed_generation, reason="reclaim")
            raise OcrProcessingError("Worker did not stop within its reclamation grace") from None
        except BrokenProcessPool:
            await _rebuild_pool(observed_generation, reason="broken")
            raise OcrProcessingError("OCR worker process failed") from None
        except (FileSizeExceededError, UnsupportedFileTypeError):
            raise
        except Exception as exc:
            logger.exception("Unhandled exception type %s reached OCR dispatch", type(exc).__name__)
            raise OcrProcessingError("OCR processing failed") from exc

        _reset_rebuild_failures()

        return result
    finally:
        _active_deadlines.pop(deadline_token, None)


async def dispatch_ocr_request(
    file_bytes: bytes,
    filename: str,
    language: str,
    effective_budget: float,
    surface: str,
    trace_carrier: dict[str, str] | None = None,
) -> OcrJsonResponse:
    """Admit, dispatch and, if necessary, reclaim a single OCR request.

    Shared by the REST and MCP surfaces so both queue on the same gate and enforce the
    same deadline. `effective_budget` is the whole duration this request may run for,
    counted from the moment it arrives (including any time spent waiting here).

    Raises:
        OcrProcessingError: on any failure — expired budget, a worker that would not
            stop, a broken pool, or a genuine OCR engine failure — mapped uniformly so
            both surfaces surface the existing OCR failure code with no partial result.
    """
    arrival = time.monotonic()

    if not is_pool_usable():
        raise OcrProcessingError("OCR worker pool is unavailable")

    await _await_admission(effective_budget, arrival, surface)

    try:
        remaining = effective_budget - (time.monotonic() - arrival)
        if remaining <= 0:
            OCR_DEADLINE_STOPS_TOTAL.labels(surface=surface).inc()
            raise OcrProcessingError("Request budget exhausted before dispatch")

        return await _run_and_reclaim(file_bytes, filename, language, trace_carrier, remaining, surface)
    finally:
        _admission_semaphore.release()


def run_ocr_in_worker(
    file_bytes: bytes,
    filename: str,
    language: str,
    trace_carrier: dict[str, str] | None = None,
    budget_seconds: float | None = None,
) -> OcrJsonResponse:
    """Entry point executed inside the worker process. Must stay top-level and picklable."""
    return ocr_service.process_file(file_bytes, filename, language, trace_carrier, budget_seconds)


def _warm_worker_engine(language: str) -> None:
    """Pool initializer: runs once per worker process, before it accepts any task."""
    configure_worker_tracing()
    sweep_scratch_dir()
    ocr_service.warm_up_engine(language)


def sweep_scratch_dir() -> None:
    """Remove scratch files no request could still legitimately own.

    A killed worker never runs its own cleanup, so it leaks the temporary copy of
    whatever it was reading. Every fresh worker (including every rebuilt one) and the
    API process at startup call this, so age is a sound test on its own: nothing in
    this directory legitimately outlives one request's own ceiling.
    """
    scratch_dir = settings.OCR_SCRATCH_DIR
    os.makedirs(scratch_dir, exist_ok=True)
    max_age_seconds = settings.OCR_REQUEST_TIMEOUT + settings.OCR_DISPATCH_MARGIN_SECONDS
    now = time.time()

    for entry in os.scandir(scratch_dir):
        if not entry.is_file():
            continue

        try:
            age = now - entry.stat().st_mtime
        except OSError:
            continue

        if age <= max_age_seconds:
            continue

        try:
            os.remove(entry.path)
        except OSError:
            logger.warning("Failed to sweep stale scratch file: %s", entry.path)


def _noop_task() -> None:
    return None
