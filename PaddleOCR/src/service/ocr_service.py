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

from src.config.config import settings
from src.config.cpu_limits import apply_cpu_thread_limit
from src.config.logging_config import get_logger, setup_logging
from src.model.ocr_models import OcrJsonResponse, OcrPageResult, OcrTextLine
from src.observability.metrics import (
    ENGINE_CACHE_EVICTIONS_TOTAL,
    ENGINE_WARMUP_DURATION_SECONDS,
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
_WORKER_POOL_SIZE: int = 1


class OcrService:
    def __init__(self) -> None:
        self._engines: OrderedDict[str, PaddleOCR] = OrderedDict()

    def process_file(
        self,
        file_bytes: bytes,
        filename: str,
        language: str,
        trace_carrier: dict[str, str] | None = None,
    ) -> OcrJsonResponse:
        start_time: float = time.monotonic()
        engine: PaddleOCR = self._get_engine(language)

        file_ext = _safe_suffix(filename)
        with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as temp_file:
            temp_file.write(file_bytes)
            temp_file_path: str = temp_file.name

        # trace_carrier, when present, was produced by inject_trace_context() in the
        # process that submitted this call. Extracting it here reattaches this span to
        # that request's trace instead of starting an orphaned one, since this method
        # itself runs inside a separate OCR worker process (see start_worker_pool).
        parent_context = extract_trace_context(trace_carrier) if trace_carrier else None

        try:
            with tracer.start_as_current_span(
                "paddleocr.engine.predict",
                context=parent_context,
                attributes={"language": language},
            ):
                ocr_result = engine.predict(temp_file_path)

            pages: list[OcrPageResult] = self._build_pages(ocr_result)
        finally:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

        elapsed: float = round(time.monotonic() - start_time, 3)

        return OcrJsonResponse(
            filename=filename,
            language=language,
            pages=pages,
            processing_time_seconds=elapsed,
        )

    def warm_up_engine(self, language: str) -> None:
        logger.info("Warming up OCR engine for language: %s", language)
        start = time.monotonic()

        with tracer.start_as_current_span(
            "paddleocr.engine.warmup",
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

        engine = PaddleOCR(lang=language, enable_mkldnn=False)
        self._engines[language] = engine
        self._evict_if_over_capacity()

        return engine

    def _evict_if_over_capacity(self) -> None:
        while len(self._engines) > settings.ENGINE_CACHE_MAX_SIZE:
            evicted_lang, _ = self._engines.popitem(last=False)
            ENGINE_CACHE_EVICTIONS_TOTAL.labels(language=evicted_lang).inc()
            logger.info("Evicted engine for language %s (cache full)", evicted_lang)

    def _build_pages(self, ocr_result: list[dict[str, object]] | None) -> list[OcrPageResult]:
        # Same numpy-truthiness trap as _convert_polygon: avoid `if not ocr_result`
        # since PaddleOCR may return numpy-backed sequences. Explicit None + length.
        if ocr_result is None or len(ocr_result) == 0:
            return []

        return [
            OcrPageResult(page_number=index + 1, lines=self._extract_text_lines(page))
            for index, page in enumerate(ocr_result)
            if isinstance(page, dict)
        ]

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


def start_worker_pool() -> None:
    """Start the OCR worker process pool and block until it has warmed up.

    PaddleOCR's CPU inference holds the GIL almost continuously for the entire
    duration of a call, so running it via a thread (asyncio.to_thread) freezes this
    process's own asyncio event loop for as long as inference runs. Running it in a
    separate OS process instead gives it its own GIL, so the event loop stays free to
    service other requests (downloads, health checks) while inference is in flight.
    """
    global _process_pool  # noqa: PLW0603  module-level pool reassigned once at startup
    _process_pool = ProcessPoolExecutor(
        max_workers=_WORKER_POOL_SIZE,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_warm_worker_engine,
        initargs=(settings.DEFAULT_LANGUAGE,),
    )
    # ProcessPoolExecutor only starts its worker(s) lazily on the first submitted
    # task, so force that here and block until the initializer above has finished
    # warming the default-language engine, matching today's synchronous startup cost.
    try:
        _process_pool.submit(_noop_task).result()
    except BrokenProcessPool:
        # The initializer (_warm_worker_engine) raised, so the pool considers itself
        # broken and every future submission will raise this same exception. Log and
        # return instead of letting it propagate: this runs from the FastAPI lifespan,
        # and a startup exception there kills the whole container before /health or
        # /ready can ever answer. Leaving it unwarm here is enough — is_engine_warm()
        # never observed a successful warm-up, so /ready honestly reports not-ready,
        # and a real OCR request against the broken pool surfaces as a handled 500
        # via the global exception handler rather than a crash.
        logger.exception("OCR worker pool failed to warm up; the pool is unusable until the process restarts")


def stop_worker_pool() -> None:
    global _process_pool  # noqa: PLW0603  module-level pool reassigned once at shutdown
    if _process_pool is not None:
        _process_pool.shutdown(wait=True)
        _process_pool = None


def get_process_pool() -> ProcessPoolExecutor:
    if _process_pool is None:
        raise RuntimeError("OCR worker pool is not initialised")

    return _process_pool


def run_ocr_in_worker(
    file_bytes: bytes,
    filename: str,
    language: str,
    trace_carrier: dict[str, str] | None = None,
) -> OcrJsonResponse:
    """Entry point executed inside the worker process. Must stay top-level and picklable."""
    return ocr_service.process_file(file_bytes, filename, language, trace_carrier)


def _warm_worker_engine(language: str) -> None:
    """Pool initializer: runs once per worker process, before it accepts any task."""
    configure_worker_tracing()
    ocr_service.warm_up_engine(language)


def _noop_task() -> None:
    return None
