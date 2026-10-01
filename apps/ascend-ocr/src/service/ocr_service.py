import asyncio
import multiprocessing
import time
from collections import OrderedDict
from collections.abc import Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any, Final, cast

import numpy as np
from paddleocr import PaddleOCR
from PIL import Image, ImageDraw, ImageFont

from src.api.exception_handlers import FileSizeExceededError, OcrProcessingError, UnsupportedFileTypeError
from src.config.config import DEFAULT_QUALITY, ModelPair, QualityMode, QualityProfile, settings
from src.config.cpu_limits import apply_cpu_thread_limit, detect_cpu_limit
from src.config.logging_config import get_logger, setup_logging
from src.model.ocr_models import OcrJsonResponse, OcrPageResult, OcrTextLine
from src.observability.metrics import (
    ENGINE_CACHE_EVICTIONS_TOTAL,
    ENGINE_WARMUP_DURATION_SECONDS,
    OCR_DEADLINE_STOPS_TOTAL,
    OCR_PAGE_DURATION_SECONDS,
    POOL_REBUILDS_TOTAL,
    WORKER_REPLACEMENTS_TOTAL,
)
from src.observability.tracing import configure_worker_tracing, extract_trace_context, get_tracer
from src.service.job_store import write_progress
from src.service.page_renderer import PageImage, render_pages

logger = get_logger(__name__)
tracer = get_tracer()

TEXTLINE_ORIENTATION_BATCH_SIZE: Final[int] = 1
TEXT_RECOGNITION_BATCH_SIZE: Final[int] = 1
WARM_UP_TEXT: Final[str] = "Warm up the reader"
WARM_UP_PAGE_SIZE: Final[tuple[int, int]] = (320, 64)
WARM_UP_TEXT_ORIGIN: Final[tuple[int, int]] = (16, 16)
WARM_UP_FONT_SIZE: Final[int] = 24
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


class OcrDeadlineExceededError(Exception):
    """Raised inside the worker when a request's budget expires before or during inference."""


class OcrService:
    def __init__(self) -> None:
        self._engines: OrderedDict[ModelPair, PaddleOCR] = OrderedDict()

    def process_file(
        self,
        file_bytes: bytes,
        filename: str,
        language: str,
        quality: QualityMode,
        trace_carrier: dict[str, str] | None = None,
        budget_seconds: float | None = None,
        job_id: str | None = None,
        straighten: bool = False,
    ) -> OcrJsonResponse:
        start_time: float = time.monotonic()
        engine: PaddleOCR = self._get_engine(language)
        profile = settings.quality_profile(quality)
        deadline: float | None = time.monotonic() + budget_seconds if budget_seconds is not None else None

        # trace_carrier, when present, was produced by inject_trace_context() in the
        # process that submitted this call. Extracting it here reattaches this span to
        # that request's trace instead of starting an orphaned one, since this method
        # itself runs inside a separate OCR worker process (see start_worker_pool).
        parent_context = extract_trace_context(trace_carrier) if trace_carrier else None

        with tracer.start_as_current_span(
            "ascend-ocr.engine.predict",
            context=parent_context,
            attributes={"language": language, "quality": quality, "straighten": straighten},
        ):
            pages: list[OcrPageResult] = self._predict_pages(
                engine, render_pages(file_bytes, profile), profile, deadline, job_id, straighten
            )

        elapsed: float = round(time.monotonic() - start_time, 3)

        return OcrJsonResponse(
            filename=filename,
            language=language,
            pages=pages,
            processing_time_seconds=elapsed,
        )

    def _predict_pages(
        self,
        engine: PaddleOCR,
        page_images: Iterator[PageImage],
        profile: QualityProfile,
        deadline: float | None,
        job_id: str | None = None,
        straighten: bool = False,
    ) -> list[OcrPageResult]:
        # One checkpoint per page, and it runs before the next page is pulled, i.e.
        # before that page is rendered and before its inference starts: next(page_images)
        # is what renders it.
        pages: list[OcrPageResult] = []
        page_number = 0

        while True:
            if deadline is not None and time.monotonic() >= deadline:
                raise OcrDeadlineExceededError(f"Budget exhausted after {page_number} of the document's pages")

            page_start = time.monotonic()
            remaining_budget = deadline - page_start if deadline is not None else None
            try:
                page_image = next(page_images)
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
                page_data = _predict_page(engine, page_image, profile, straighten)
                OCR_PAGE_DURATION_SECONDS.observe(time.monotonic() - page_start)
                if isinstance(page_data, dict):
                    pages.append(OcrPageResult(page_number=page_number, lines=self._extract_text_lines(page_data)))

            # The same seam the deadline uses, so progress is written exactly where the
            # worker is already free to be interrupted, and a poll arriving mid-document
            # reads a page count rather than nothing.
            if job_id is not None:
                write_progress(job_id, page_number)

        return pages

    def warm_up_engine(self, language: str) -> None:
        logger.info("Warming up OCR engine for language: %s", language)
        start = time.monotonic()

        with tracer.start_as_current_span(
            "ascend-ocr.engine.warmup",
            attributes={"language": language},
        ):
            engine = self._get_engine(language)
            _predict_page(engine, _warm_up_page(), settings.quality_profile(DEFAULT_QUALITY), straighten=False)

        ENGINE_WARMUP_DURATION_SECONDS.labels(language=language).observe(time.monotonic() - start)

    def _get_engine(self, language: str) -> PaddleOCR:
        if language not in settings.SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {language!r}")

        models = _resolve_model_pair(language)
        cached = self._engines.get(models)
        if cached is not None:
            self._engines.move_to_end(models)

            return cached

        engine = build_engine(models)
        self._engines[models] = engine
        self._evict_if_over_capacity()

        return engine

    def _evict_if_over_capacity(self) -> None:
        while len(self._engines) > settings.ENGINE_CACHE_MAX_SIZE:
            evicted_models, _ = self._engines.popitem(last=False)
            ENGINE_CACHE_EVICTIONS_TOTAL.labels(engine=str(evicted_models)).inc()
            logger.info("Evicted engine %s (cache full)", evicted_models)

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


def _resolve_model_pair(language: str) -> ModelPair:
    return settings.model_pair(language)


def build_engine(models: ModelPair) -> PaddleOCR:
    """Build one engine with every model it can be asked to run loaded, and no library default left to chance.

    Unwarping is loaded here but runs only on a call that asks for it (see ADR-011).
    """
    # Named rather than resolved from `lang`: PaddleOCR silently picks a model per
    # language, and passing both names and a language makes it warn and ignore the
    # language anyway (see PaddleOCR.__init__ in paddleocr/_pipelines/ocr.py).
    # ADR-007 records which models and why.
    return PaddleOCR(
        text_detection_model_name=models.detection,
        text_recognition_model_name=models.recognition,
        use_doc_orientation_classify=True,
        use_doc_unwarping=True,
        use_textline_orientation=True,
        textline_orientation_batch_size=TEXTLINE_ORIENTATION_BATCH_SIZE,
        text_recognition_batch_size=TEXT_RECOGNITION_BATCH_SIZE,
        enable_mkldnn=False,
        cpu_threads=detect_cpu_limit(),
    )


def preload_models() -> None:
    """Fetch every model any accepted language can load, so no request ever downloads one."""
    for models in sorted(settings.reachable_model_pairs(), key=str):
        build_engine(models)


def _predict_page(engine: PaddleOCR, page_image: PageImage, profile: QualityProfile, straighten: bool) -> object:
    """Read one rendered page, bounding what detection sees by the request's quality mode.

    The pipeline's own detection limit only ever scales an image up, so without "max" every
    page would reach the detector at its full rendered size (see ADR-006). Every preprocessing
    flag is passed on each call, so the engine's construction never decides what a page gets.
    """
    results = engine.predict_iter(
        page_image,
        text_det_limit_type="max",
        text_det_limit_side_len=profile.detector_max_side,
        use_doc_orientation_classify=True,
        use_doc_unwarping=straighten,
        use_textline_orientation=True,
    )

    return next(iter(results), None)


def _warm_up_page() -> PageImage:
    image = Image.new("RGB", WARM_UP_PAGE_SIZE, "white")
    font = ImageFont.load_default(WARM_UP_FONT_SIZE)
    ImageDraw.Draw(image).text(WARM_UP_TEXT_ORIGIN, WARM_UP_TEXT, fill="black", font=font)

    return np.ascontiguousarray(np.asarray(image, dtype=np.uint8)[:, :, ::-1])


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
# Keyed by a private token rather than a single shared scalar: OCR_WORKER_COUNT jobs
# can be in flight at once, each running _run_and_reclaim concurrently, and a single
# shared deadline would have one call's own finally overwrite or erase another's,
# silently blinding is_job_overrunning() to whichever job did not start or finish
# last (see _run_and_reclaim).
_active_deadlines: dict[object, float] = {}
_rebuild_lock: asyncio.Lock = asyncio.Lock()
_consecutive_rebuild_failures: int = 0
_pending_replacements: set[asyncio.Task[None]] = set()


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
    global _process_pool, _pool_generation, _admission_semaphore  # noqa: PLW0603
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

    # ProcessPoolExecutor spawns a worker per submit() call only when no worker is
    # already idle (see _adjust_process_count in the concurrent.futures.process
    # stdlib module), so one submission forces exactly one worker into existence, not
    # max_workers. Submitting every warm-up task before collecting any result keeps
    # the idle count at zero for the whole batch, forcing one worker per task, up to
    # OCR_WORKER_COUNT, and blocking here until every one of them has finished
    # warming the default-language engine. Without this, workers beyond the first are
    # only spawned lazily by real concurrent traffic, and each then pays its own
    # warm-up cost (seconds, per ENGINE_WARMUP_DURATION_SECONDS) inside that caller's
    # own request instead of at startup - the exact "discover it under load" failure
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
        # /ready can ever answer. Leaving it unwarm here is enough - is_engine_warm()
        # never observed a successful warm-up, so /ready honestly reports not-ready,
        # and a real OCR request against the broken pool surfaces as a handled,
        # rebuild-triggering failure rather than a crash.
        logger.exception("OCR worker pool failed to warm up; the pool is unusable until it is rebuilt")

        return False

    return True


def stop_worker_pool(terminate: bool = False) -> None:
    """Shut the pool down, optionally killing its workers first.

    `shutdown(wait=True)` on its own waits for the work item in flight, and one work
    item is a whole document, so a cancel that only shut the pool down would go on
    reading the document it was asked to stop. Killing the processes first is what makes
    the inference stop, and it is why cancellation passes `terminate`.
    """
    global _process_pool  # noqa: PLW0603  module-level pool reassigned once at shutdown
    if _process_pool is None:
        return

    if terminate:
        _terminate_pool_processes(_process_pool)

    _process_pool.shutdown(wait=True)
    _process_pool = None


def _terminate_pool_processes(pool: ProcessPoolExecutor) -> None:
    """Kill every worker process the pool owns.

    Reaches for the pool's own process table because concurrent.futures offers no
    public way to stop a work item that is already running, and the alternative, a
    cooperative signal the worker polls, is a second stopping mechanism beside the
    deadline the worker already checks (see ADR-008).
    """
    for process in list(pool._processes.values()):
        process.kill()


def get_process_pool() -> ProcessPoolExecutor:
    if _process_pool is None:
        raise RuntimeError("OCR worker pool is not initialised")

    return _process_pool


def get_pool_generation() -> int:
    return _pool_generation


def is_rebuild_in_progress() -> bool:
    return _rebuild_lock.locked() or bool(_pending_replacements)


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


def request_worker_replacement_for_cancel() -> None:
    """Start replacing the worker reading a cancelled document, and return without waiting for it.

    The replacement kills the worker and warms a new one, which takes as long as a warm-up,
    so a caller that awaited it would hold its own answer for that long. The task counts as
    a rebuild in progress from this call on, so readiness drops before it first runs.
    """
    task = asyncio.create_task(replace_worker_for_cancel())
    _pending_replacements.add(task)
    task.add_done_callback(_forget_replacement)


def _forget_replacement(task: asyncio.Task[None]) -> None:
    _pending_replacements.discard(task)
    if task.cancelled():
        return

    failure = task.exception()
    if failure is not None:
        logger.error("Replacing the OCR worker after a cancel failed", exc_info=failure)


async def wait_for_worker_replacements() -> None:
    """Wait until every replacement a cancel started has finished, without cancelling one if the waiter is cancelled."""
    if not _pending_replacements:
        return

    await asyncio.wait(set(_pending_replacements))


async def replace_worker_for_cancel() -> None:
    """Stop the document being read now by replacing the worker reading it.

    The third trigger of the replacement path, beside a worker that would not stop and a
    broken pool. It kills rather than drains, because the work item in flight is a whole
    document and draining it is exactly what a cancel is asking not to happen.
    """
    await _rebuild_pool(_pool_generation, reason="cancel", terminate=True)


async def _rebuild_pool(observed_generation: int, reason: str, terminate: bool = False) -> None:
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
        # thread for that whole span - bounded by roughly one page's own inference time when
        # OCR_WORKER_COUNT is 1, since there is never a second job to wait on, but bounded by
        # nothing shorter than another worker's own full budget once a second worker exists.
        await loop.run_in_executor(None, stop_worker_pool, terminate)
        warmed = await loop.run_in_executor(None, start_worker_pool)

        if warmed:
            POOL_REBUILDS_TOTAL.labels(reason=reason, outcome="ok").inc()
        else:
            _consecutive_rebuild_failures += 1
            POOL_REBUILDS_TOTAL.labels(reason=reason, outcome="failed").inc()


async def _await_admission(effective_budget: float, arrival: float, surface: str) -> asyncio.Semaphore:
    """Wait for a free worker permit, counting the wait against the request's own budget.

    Returns:
        The gate the permit came from, which the caller releases even if a rebuild replaced it.

    Raises:
        OcrProcessingError: if the budget expires before a permit is granted.
    """
    gate = _admission_semaphore
    remaining = effective_budget - (time.monotonic() - arrival)
    try:
        await asyncio.wait_for(gate.acquire(), timeout=max(remaining, 0.0))
    except TimeoutError:
        OCR_DEADLINE_STOPS_TOTAL.labels(surface=surface).inc()
        raise OcrProcessingError("Request budget exhausted while waiting for a worker") from None

    return gate


async def _run_and_reclaim(
    file_bytes: bytes,
    filename: str,
    language: str,
    quality: QualityMode,
    trace_carrier: dict[str, str] | None,
    remaining: float,
    surface: str,
    job_id: str | None,
    straighten: bool,
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
        wait_budget = remaining + settings.reclamation_grace_seconds(settings.model_pair(language))

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
            # the awaited future - a worker killed between requests is caught here,
            # not below. A worker that dies while this specific call is in flight still
            # surfaces the same exception through the await instead.
            future = loop.run_in_executor(
                pool,
                run_ocr_in_worker,
                file_bytes,
                filename,
                language,
                quality,
                trace_carrier,
                worker_budget,
                job_id,
                straighten,
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
    quality: QualityMode,
    effective_budget: float,
    surface: str,
    trace_carrier: dict[str, str] | None = None,
    job_id: str | None = None,
    straighten: bool = False,
) -> OcrJsonResponse:
    """Admit, dispatch and, if necessary, reclaim a single OCR request.

    Called only by the job runner, which is the single consumer of the queue, so the
    gate below has exactly one client and one document is read at a time.
    `effective_budget` is the whole duration this document may be read for, counted from
    the moment the runner picked it up rather than from when it was submitted.

    Raises:
        OcrProcessingError: on any failure - expired budget, a worker that would not
            stop, a broken pool, or a genuine OCR engine failure - mapped uniformly so
            both surfaces surface the existing OCR failure code with no partial result.
    """
    arrival = time.monotonic()

    if not is_pool_usable():
        raise OcrProcessingError("OCR worker pool is unavailable")

    gate = await _await_admission(effective_budget, arrival, surface)

    try:
        remaining = effective_budget - (time.monotonic() - arrival)
        if remaining <= 0:
            OCR_DEADLINE_STOPS_TOTAL.labels(surface=surface).inc()
            raise OcrProcessingError("Request budget exhausted before dispatch")

        return await _run_and_reclaim(
            file_bytes, filename, language, quality, trace_carrier, remaining, surface, job_id, straighten
        )
    finally:
        gate.release()


def run_ocr_in_worker(
    file_bytes: bytes,
    filename: str,
    language: str,
    quality: QualityMode,
    trace_carrier: dict[str, str] | None = None,
    budget_seconds: float | None = None,
    job_id: str | None = None,
    straighten: bool = False,
) -> OcrJsonResponse:
    """Entry point executed inside the worker process. Must stay top-level and picklable."""
    return ocr_service.process_file(
        file_bytes, filename, language, quality, trace_carrier, budget_seconds, job_id, straighten
    )


def _warm_worker_engine(language: str) -> None:
    """Pool initializer: runs once per worker process, before it accepts any task."""
    configure_worker_tracing()
    ocr_service.warm_up_engine(language)


def _noop_task() -> None:
    return None
