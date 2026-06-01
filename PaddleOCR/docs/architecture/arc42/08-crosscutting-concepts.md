# 8. Crosscutting Concepts

---

### Logging and startup banner

Logging is configured via `src/config/logging_config.py` and consumed through `get_logger(__name__)` in every module.
The Uvicorn logger instance is used for service-level messages. At startup, `log_startup_banner()` from
`src/config/startup_banner.py` emits a structured block that includes both probe URLs (`/health`, `/ready`), the MCP
endpoint, `file://` root status, allowed hosts, download timeout, default language, max upload size, OCR timeout, and
engine cache capacity. An operator checking the container logs immediately after startup can read the full runtime
configuration without inspecting environment variables separately.

---

### Error catalog

The five domain exception classes (`OcrProcessingError`, `FileSizeExceededError`, `UnsupportedFileTypeError`,
`UnsafeUriError`, `DownloadFailedError`) and the `INTERNAL_ERROR` fallback are all defined in
`src/api/exception_handlers.py`. The mapping from exception to HTTP status is in the handler registration
(`register_exception_handlers`, lines 38-44 of that file). Every handler returns `{"code": "...", "detail": "..."}`:
a stable code string and a generic English phrase. The original exception message is logged at WARNING or ERROR.
Internal stack frames, file paths, and upstream URLs never appear in the response body.

This catalog is shared between the REST and MCP surfaces. Adding a new failure mode requires one exception class,
one handler, one catalog entry, and tests. See [ADR-002](../decisions/ADR-002-mcp-error-catalog.md).

---

### Async hygiene

The service follows a consistent pattern for CPU-bound work:

```
asyncio.wait_for(
    asyncio.to_thread(blocking_call, ...),
    timeout=settings.OCR_REQUEST_TIMEOUT,
)
```

Both `rest_endpoints.py:34-37` and `mcp_server.py:66-69` use this pattern. The event loop stays free during OCR.
The `aiohttp.ClientSession` in the MCP module is created once in `mcp_lifespan` and reused across all calls, avoiding
the per-request connection overhead that comes from creating a new session per tool call.

---

### Language allowlist and LRU engine cache

`SUPPORTED_LANGUAGES` in `src/config/config.py` is a tuple of accepted language codes. Any language code outside
this tuple raises `ValueError` from `OcrService._get_engine` before a `PaddleOCR` instance is ever allocated. This
prevents callers from driving unbounded memory use by sending unusual language strings.

The `OrderedDict`-based LRU cache in `OcrService` (`src/service/ocr_service.py:20`) promotes accessed entries to the
tail and evicts from the head when the cache exceeds `ENGINE_CACHE_MAX_SIZE`. The eviction is logged at INFO so
operators can tune the cap if language churn causes frequent evictions.

---

### Multi-page PDF handling

`OcrService._build_pages` (`src/service/ocr_service.py:77-85`) iterates over the list of page dicts returned by
`engine.predict` and assigns `page_number = index + 1`. Prior to today's hardening, the result was treated as
single-page; multi-page PDFs now produce one `OcrPageResult` per page with correct 1-based numbering.

---

### Versioning discipline

REST routes are mounted under the `APIRouter(prefix="/v1")` in `rest_endpoints.py:17`. The `OcrJsonResponse` carries
`schema_version: Literal["1"] = "1"` (`src/model/ocr_models.py:5,21`). Breaking changes to the REST surface get a
new URL prefix (`/v2/...`); breaking changes to the MCP tool get a new tool name (`ocr_process_v2`). See
[ADR-003](../decisions/ADR-003-versioning-strategy.md) for the full compatibility matrix.
