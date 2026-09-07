from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.multiprocess import MultiProcessCollector

_ENGINE_WARMUP_METRIC_NAME = "ascendocr_engine_warmup_duration_seconds"
_ENGINE_WARMUP_COUNT_SAMPLE = f"{_ENGINE_WARMUP_METRIC_NAME}_count"

OCR_DURATION_SECONDS: Histogram = Histogram(
    "ascendocr_ocr_duration_seconds",
    "OCR engine execution duration in seconds.",
    labelnames=("surface", "language"),
    buckets=(0.5, 1.0, 2.0, 5.0, 15.0, 30.0, 60.0, 120.0),
)

OCR_REQUESTS_TOTAL: Counter = Counter(
    "ascendocr_ocr_requests_total",
    "Total OCR requests received.",
    labelnames=("surface", "language"),
)

OCR_ERRORS_TOTAL: Counter = Counter(
    "ascendocr_ocr_errors_total",
    "OCR errors by code and surface.",
    labelnames=("error_code", "surface"),
)

ENGINE_CACHE_EVICTIONS_TOTAL: Counter = Counter(
    "ascendocr_engine_cache_evictions_total",
    "Number of engine cache evictions per language.",
    labelnames=("language",),
)

ENGINE_WARMUP_DURATION_SECONDS: Histogram = Histogram(
    _ENGINE_WARMUP_METRIC_NAME,
    "Engine warm-up duration inside the OCR worker process.",
    labelnames=("language",),
    buckets=(1.0, 2.0, 5.0, 10.0, 15.0, 30.0, 60.0, 90.0),
)

MCP_DOWNLOAD_DURATION_SECONDS: Histogram = Histogram(
    "ascendocr_mcp_download_duration_seconds",
    "MCP file fetch duration in seconds, partitioned by outcome.",
    labelnames=("outcome",),
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0),
)

OCR_QUEUE_DEPTH: Gauge = Gauge(
    "ascendocr_ocr_queue_depth",
    "Requests currently waiting on the admission gate for a free worker.",
)

OCR_QUEUE_WAIT_SECONDS: Histogram = Histogram(
    "ascendocr_ocr_queue_wait_seconds",
    "Time a request spent waiting on the admission gate before being dispatched or refused.",
    buckets=(0.1, 0.5, 1.0, 5.0, 15.0, 30.0, 60.0, 120.0),
)

OCR_PAGE_DURATION_SECONDS: Histogram = Histogram(
    "ascendocr_ocr_page_duration_seconds",
    "Inference duration of a single page inside the OCR worker process.",
    buckets=(0.5, 1.0, 2.0, 5.0, 15.0, 30.0, 60.0, 120.0),
)

OCR_DEADLINE_STOPS_TOTAL: Counter = Counter(
    "ascendocr_ocr_deadline_stops_total",
    "Requests stopped because their own budget expired, by surface.",
    labelnames=("surface",),
)

WORKER_REPLACEMENTS_TOTAL: Counter = Counter(
    "ascendocr_worker_replacements_total",
    "Worker processes replaced because they did not stop within their reclamation grace.",
)

POOL_REBUILDS_TOTAL: Counter = Counter(
    "ascendocr_pool_rebuilds_total",
    "Worker pool rebuilds, by trigger reason and outcome.",
    labelnames=("reason", "outcome"),
)


def is_engine_warm(language: str) -> bool:
    """Report whether the OCR worker process has completed a warm-up for a language.

    The engine is built inside a separate `ProcessPoolExecutor` worker (see
    `service/ocr_service.py`), so this process has no in-memory state to inspect.
    Instead it reads the same PROMETHEUS_MULTIPROC_DIR mmap files the worker's own
    `ENGINE_WARMUP_DURATION_SECONDS.observe()` call writes to, the identical
    cross-process mechanism already used to surface the engine-cache eviction
    counter on `/metrics`. `observe()` only runs after a successful warm-up, so a
    failed or still-pending warm-up leaves the count at zero.
    """
    registry = CollectorRegistry()
    MultiProcessCollector(registry)

    for metric_family in registry.collect():
        if metric_family.name != _ENGINE_WARMUP_METRIC_NAME:
            continue

        for sample in metric_family.samples:
            if sample.name == _ENGINE_WARMUP_COUNT_SAMPLE and sample.labels.get("language") == language:
                return sample.value > 0

    return False
