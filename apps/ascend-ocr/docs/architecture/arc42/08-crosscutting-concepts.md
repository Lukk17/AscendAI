# 8. Crosscutting Concepts

---

### Logging and startup banner

Logging is configured via `src/config/logging_config.py` and consumed through `get_logger(__name__)` in every module.
The Uvicorn logger instance is used for service-level messages. At startup, `log_startup_banner()` from
`src/config/startup_banner.py` emits a structured block that includes both probe URLs (`/health`, `/ready`), the MCP
endpoint, `file://` root status, allowed hosts, download timeout, default language, max upload size, the per-page
allowance, the page ceiling and the reading ceiling derived from it, the queue's two bounds, the retention window,
the jobs directory, the result store and whether its bucket answered at boot, and engine cache capacity. An operator
checking the container logs immediately after startup can read the full runtime configuration without inspecting
environment variables separately. Credentials never appear in it.

Beyond the banner, the service emits exactly one log line per job state transition, carrying the identifier, the page
count and the reason for a terminal state. No line carries document text, a presigned URL, or a credential.

Every line carries `correlation_id`. For a REST request it is the request's `x-request-id` header, or a fresh id
when the caller sent none, and the same value is echoed on the response. An inbound `x-request-id` is kept only when
it is 1 to 128 characters of letters, digits, `.`, `_`, `:` and `-` (`ACCEPTED_CORRELATION_ID_PATTERN`). Any other
value, including one that is too long, carries a byte outside ASCII or a control character, is replaced by a fresh
id, and that fresh id is both logged and echoed, so a malformed header never fails a request. Every MCP request, tool
calls, `tools/list`, resources and prompts alike, is logged under the id of the HTTP request that carried it, not the
one that opened the session, and each line written while that request is bound also carries `mcp_session_id`, the
first 16 hex characters of the SHA-256 digest of the session's `mcp-session-id`. `CorrelationIdMiddleware` also binds
that digest in the HTTP request's own task, for the whole request, because the MCP request itself runs in the SDK's
session task and a value bound there is not visible when uvicorn writes the access line in the request's task. It
does so only for a request to the MCP endpoint, whose path is exactly `MCP_ENDPOINT_PATH` (`/mcp`, in
`src/config/config.py`, the one constant `src/main.py` passes to both `mcp.http_app` and the middleware), and only
when that request carries an `mcp-session-id` header the MCP SDK accepts (visible ASCII, the SDK's
`SESSION_ID_PATTERN`). The digest is of the value the caller sent, not proof that the session exists: on the 404 the
SDK answers for an unknown or expired session it names no live session. A request to any other path never carries
the digest, so a caller cannot put a value of its choosing into a REST line by sending the header there. An
`initialize` request has no such header, since its response creates the session, so the middleware binds the digest of
the response's `mcp-session-id` header only while the response start is sent, which is when uvicorn writes the access
line. The digest groups the requests of one
session without writing the session handle itself, which would let anyone who reads the log and reaches the port open
or delete the session. `correlation_id` is chosen by the caller whenever the caller sends an acceptable
`x-request-id`, so it is a debugging aid and must never be used to decide who did something.

`CorrelationIdMiddleware` is the outermost layer of the app. `build_middleware_stack` of the FastAPI subclass in
`src/main.py` wraps Starlette's whole stack in it, `ServerErrorMiddleware` included, and it is registered nowhere
else. When an unhandled exception ends a request, the `INTERNAL_ERROR` line the global exception handler writes and
the 500's access line are written while the request's ids are bound, and the 500 carries `x-request-id` like every
other response. Uvicorn writes its own `Exception in ASGI application` line after the app has raised, outside every
ASGI layer, so the middleware attaches the request's ids to the exception on its way out and `CorrelationIdLogFilter`
uses them for a record whose exception carries them when no request is bound. That line carries the same
`correlation_id`, and the session digest for a request to the MCP endpoint.

In the JSON format every line names both fields. `correlation_id` is `-` on a line written outside any request, such
as a job state transition the job runner writes while it reads a document, while a transition written during a
submission or a cancel carries that request's id. `mcp_session_id` is `null` on every line of a request to any path
other than the MCP endpoint, which is every REST line, `/health`, `/ready` and `/metrics` included, even when the
request sends an `mcp-session-id` header, on a line of an MCP endpoint request that carries no acceptable
`mcp-session-id` header, which is every line of an `initialize` request except its access line, on a line written
outside any request, and on the MCP SDK's own transport lines written
outside a request that carries the header: `Created new transport` during `initialize`, and the idle timeout, crash
and clean-up lines the session's own task writes. `Terminating session` on DELETE is written in the DELETE request's
own task and carries the digest, and so does every access line of a request to the MCP endpoint that carries the
header, the 404 for an unknown session included. The color format prints both as
`[<correlation_id> <mcp_session_id>]` and prints `-` for either one when it is missing. The one line that cannot
carry the id of its own request is the MCP SDK's INFO line `Processing request of type ...`, written before any
FastMCP middleware runs: it carries the id of the `initialize` request that opened the session and no
`mcp_session_id`.

The raw session id never leaves the process. The MCP SDK writes it into its own transport lines (a new session, an
idle timeout, a crash with its traceback, a clean-up, and `Terminating session` on DELETE).
`McpSessionIdRedactionFilter` replaces every 32-hex-character token in those lines, and in their traceback text, with
its digest. It runs as a logger filter on the two loggers the SDK writes with, `mcp.server.streamable_http_manager`
and `mcp.server.streamable_http`, so it runs before any handler, including one added later such as OpenTelemetry's
`LoggingHandler`, and again as a handler filter on the root handler in both formats. It rewrites every run of exactly
32 hex characters in those two loggers' lines, not only session ids, so a 32-hex JSON-RPC id a client chose shows as
its digest if the SDK writes it in a DEBUG line. FastMCP's own `fastmcp` logger is set up by FastMCP with a handler of
its own and no propagation, and uvicorn applies its own logging config to `uvicorn` and `uvicorn.access` before it
imports the app, since the container starts it with `python3.11 -m uvicorn src.main:app --ws none` and no `--log-config`.
`setup_logging` runs when the app is imported and treats `fastmcp`, `uvicorn`, `uvicorn.error` and `uvicorn.access`
the same way: it removes their handlers, sets their level to `NOTSET` and turns propagation on. Their lines, access
lines and the startup banner included, pass through the root handler with its format and both filters under
`LOG_LEVEL`, and uvicorn's `--log-level` and `--no-access-log` have no effect. With tracing on, FastMCP puts the raw id
on every server span as `mcp.session.id`, and `McpSessionDigestSpanExporter` in `src/observability/tracing.py`
replaces it with the digest before the OTLP exporter sends the span. It does the same for
`http.request.header.mcp_session_id` and `http.response.header.mcp_session_id`, the keys a captured `mcp-session-id`
header would get if header capture were turned on, and the span it sends keeps the original's events, links, status,
resource, scope and dropped counts. The digest, the redaction and the exporter all use
`digest_of_mcp_session_id` in `src/api/middleware/correlation_id.py`. See the fourth 2026-09-25 amendment to
[ADR-002](../decisions/ADR-002-mcp-error-catalog.md).

---

### Error catalog

The eight domain exception classes (`OcrProcessingError`, `FileSizeExceededError`, `UnsupportedFileTypeError`,
`UnsafeUriError`, `DownloadFailedError`, `QueueFullError`, `JobNotFoundError`, `UnsupportedLanguageError`) and the
`INTERNAL_ERROR` fallback are all defined in `src/api/exception_handlers.py`. The mapping from exception to HTTP
status is in the handler registration (`register_exception_handlers` in that file). Every handler returns
`{"code": "...", "detail": "..."}`: a stable code string and a generic English phrase. A refusal that worked as
designed, `UNSAFE_URI`, `UNSUPPORTED_FILE_TYPE`, `FILE_TOO_LARGE`, `UNSUPPORTED_LANGUAGE`, `QUEUE_FULL`,
`JOB_NOT_FOUND` or the upstream `DOWNLOAD_FAILED`, is logged by `log_refusal` as one WARNING line naming its code,
with no traceback and never the userinfo of a URI, on the MCP surface as well as the REST one. `OCR_FAILED` is logged
at ERROR, and an unexpected exception at ERROR with its traceback. Internal stack frames, file paths, and upstream URLs
never appear in the response body. See the third 2026-09-25 amendment to
[ADR-002](../decisions/ADR-002-mcp-error-catalog.md).

A failure of the reading is not one of these. It is a successful read of a job record whose state is `failed`,
carrying `error_code`, `error_reason` and `retryable`, which is the one place the shape of a failure changed with the
job surface. See the 2026-09-24 amendment to [ADR-002](../decisions/ADR-002-mcp-error-catalog.md).

This catalog is shared between the REST and MCP surfaces. Adding a new failure mode requires one exception class,
one handler, one catalog entry, and tests. See [ADR-002](../decisions/ADR-002-mcp-error-catalog.md).

Every handler counts its error in `ascendocr_ocr_errors_total{error_code, surface}`. `surface` has two values. It is
`mcp` for a request whose path is exactly `MCP_ENDPOINT_PATH` (`/mcp`, in `src/config/config.py`), the same rule the
correlation middleware applies, and `rest` for every other path: the `/v1` job operations and the operational
endpoints `/health`, `/ready` and `/metrics`, which the endpoint table in the README lists beside them. A 500 from
`/ready` is therefore counted as `rest`, never as `mcp`.

---

### Async hygiene

The service follows a consistent pattern for CPU-bound work:

```
asyncio.wait_for(
    loop.run_in_executor(get_process_pool(), blocking_call, ...),
    timeout=remaining + settings.reclamation_grace_seconds(settings.model_pair(language)),
)
```

Only `job_runner.py` reaches that pattern, through `dispatch_ocr_request`, and a test asserts that no other module
even imports it. `PaddleOCR.predict()` holds the interpreter lock for the whole call, so the blocking work runs in
the single-worker `ProcessPoolExecutor` started by `start_worker_pool` (`src/service/ocr_service.py`), not in a
thread. The main process's event loop stays free during OCR, which is what keeps every status read answering while a
hundred page document is in flight.

Two more pieces of blocking work are kept off the loop for the same reason: a submission's bytes, which can be
`MAX_FILE_SIZE_MB` of them, are written through `asyncio.to_thread`, and so is every call into the object store. The
job record itself is small enough to write inline, and writing it inline is what makes the API process the single
serialised writer the store's correctness rests on.

The `aiohttp.ClientSession` in the MCP module is created once in `mcp_lifespan` and reused across all calls, avoiding
the per-request connection overhead that comes from creating a new session per tool call.

---

### Language allowlist, model resolution, and the LRU engine cache

`SUPPORTED_LANGUAGES` in `src/config/config.py` is a tuple of accepted language codes. A submission in any other
code is refused on both surfaces by `ensure_language_supported` in `src/service/job_service.py`, with 400
`UNSUPPORTED_LANGUAGE`, before anything is fetched, stored or queued. As a defence behind that, any language code outside
this tuple raises `ValueError` from `OcrService._get_engine` before a model name is resolved and before a
`PaddleOCR` instance is ever allocated. This prevents callers from driving unbounded memory use by sending unusual
language strings.

An accepted language then resolves to a `ModelPair` through `_resolve_model_pair`: the pair named by
`OCR_TEXT_DETECTION_MODEL` and `OCR_TEXT_RECOGNITION_MODEL`, unless the language appears in
`LANGUAGE_MODEL_OVERRIDES`, which names a pair for a language the default pair cannot read and is empty while `ru`
and `korean` are switched off. The engine is
constructed from those two names, never from a `lang` argument.

The `OrderedDict`-based LRU cache in `OcrService` is keyed by that `ModelPair`, so two languages resolving to one
pair share one engine. It promotes accessed entries to the tail and evicts from the head when the cache exceeds
`ENGINE_CACHE_MAX_SIZE`. The eviction is logged at INFO and counted by
`ascendocr_engine_cache_evictions_total{engine="<detection>/<recognition>"}`, so operators can tune the cap if
engine churn causes frequent evictions.

---

### Multi-page PDF handling

`OcrService._build_pages` (`src/service/ocr_service.py:77-85`) iterates over the list of page dicts returned by
`engine.predict` and assigns `page_number = index + 1`. Prior to today's hardening, the result was treated as
single-page; multi-page PDFs now produce one `OcrPageResult` per page with correct 1-based numbering.

---

### Versioning discipline

REST routes are mounted under the `APIRouter(prefix="/v1")` in `rest_endpoints.py`. The result description a
successful job carries still holds `schema_version: Literal["1"] = "1"` (`src/model/ocr_models.py`). Breaking changes
to the REST surface get a new URL prefix (`/v2/...`); breaking changes to an MCP tool get a new tool name. See
[ADR-003](../decisions/ADR-003-versioning-strategy.md) for the full compatibility matrix, and its 2026-09-24
amendment for the one breaking change that used neither mechanism, and why.
