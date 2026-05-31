from prometheus_client import Counter, Histogram

OCR_DURATION_SECONDS: Histogram = Histogram(
    "paddleocr_ocr_duration_seconds",
    "OCR engine execution duration in seconds.",
    labelnames=("surface", "language"),
    buckets=(0.5, 1.0, 2.0, 5.0, 15.0, 30.0, 60.0, 120.0),
)

OCR_REQUESTS_TOTAL: Counter = Counter(
    "paddleocr_ocr_requests_total",
    "Total OCR requests received.",
    labelnames=("surface", "language"),
)

OCR_ERRORS_TOTAL: Counter = Counter(
    "paddleocr_ocr_errors_total",
    "OCR errors by code and surface.",
    labelnames=("error_code", "surface"),
)

ENGINE_CACHE_EVICTIONS_TOTAL: Counter = Counter(
    "paddleocr_engine_cache_evictions_total",
    "Number of engine cache evictions per language.",
    labelnames=("language",),
)

ENGINE_WARMUP_DURATION_SECONDS: Histogram = Histogram(
    "paddleocr_engine_warmup_duration_seconds",
    "Engine warm-up duration during lifespan.",
    labelnames=("language",),
    buckets=(1.0, 2.0, 5.0, 10.0, 15.0, 30.0, 60.0, 90.0),
)

MCP_DOWNLOAD_DURATION_SECONDS: Histogram = Histogram(
    "paddleocr_mcp_download_duration_seconds",
    "MCP file fetch duration in seconds, partitioned by outcome.",
    labelnames=("outcome",),
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0),
)
