# ADR-002: MCP error code catalog mirrors the REST surface

## Status

Accepted - 2026-05-31. Amended - 2026-09-24: three codes join the catalogue and three record-level reasons appear
that are not HTTP statuses at all (see "Amendment" below). Amended again 2026-09-25: `UNSUPPORTED_LANGUAGE` joins
the catalogue (see "Second amendment" below). Amended a third time 2026-09-25: an expected refusal is logged as one
warning on both surfaces (see "Third amendment" below). Amended a fourth time 2026-09-25: every MCP request
is logged under its own correlation id, with a digest of its session in a separate field (see "Fourth amendment"
below).

## Context

ascend-ocr exposes the same OCR capability via two surfaces: REST (`POST /v1/ocr`, multipart) and MCP (`tools/call name="ocr_process"`). The two transports return errors very differently by default.

REST returns mapped HTTP status codes - `400` for input validation failures, `422` for OCR engine failure, `502` for downstream fetch failure, `500` for unhandled exceptions. The mapping is enforced by FastAPI's exception-handler registry.

MCP, by contrast, wraps the call in a JSON-RPC envelope. If the tool raises, FastMCP converts the exception to a JSON-RPC error frame. From the agent caller's perspective every exception arrives as "the tool errored" - there is no native equivalent of HTTP 4xx vs 5xx, no native way to distinguish "retry with different input" from "give up." An agent that batches OCR calls behind retries can either re-try `UnsafeUriError` indefinitely or stop retrying `OcrProcessingError` after a single transient failure.

## Decision

Define a stable error code catalog used by **both** surfaces. Each error code is a stable string that the agent can pattern-match on. The REST response body and the MCP tool response body both carry the same `{"code": "...", "detail": "..."}` shape.

### Catalog

| Code                       | REST status | Meaning                                                            | Caller action            |
| -------------------------- | ----------- | ------------------------------------------------------------------ | ------------------------ |
| `OCR_FAILED`               | 422         | OCR engine raised; the input is valid but processing failed.       | Retry once, then give up |
| `FILE_TOO_LARGE`           | 400         | Source exceeds `MAX_FILE_SIZE_MB`.                                 | Reduce size              |
| `UNSUPPORTED_FILE_TYPE`    | 400         | Content type prefix not in the allowlist (image/, application/pdf).| Use a supported type     |
| `UNSAFE_URI`               | 400         | URI rejected by the SSRF guard, `file://` jail, or scheme check.   | Use an allowed URI       |
| `DOWNLOAD_FAILED`          | 502         | Upstream URI fetch failed (non-200, network error, file not found).| Retry, then give up      |
| `INTERNAL_ERROR`           | 500         | Unhandled exception in the server.                                 | Page the operator        |

### Implementation

`src/api/exception_handlers.py` defines the exception classes (`OcrProcessingError`, `FileSizeExceededError`, `UnsupportedFileTypeError`, `UnsafeUriError`, `DownloadFailedError`) and registers a FastAPI handler per class that emits the `{"code", "detail"}` body. The MCP tool wrapper raises the same exception classes. FastMCP currently surfaces the exception name + message in the JSON-RPC error frame; downstream agents should pattern-match on the exception name (which equals the code's domain - e.g., `UnsafeUriError` ↔ `UNSAFE_URI`) until FastMCP supports a structured `error.data.code` field natively.

### Detail messages are generic and locale-neutral

The `detail` field in the response carries a generic human-readable phrase ("OCR processing failed", "File too
large"), not the original exception's repr. Internal details - file paths, stack frames, upstream URLs - are
logged at WARNING/ERROR but never returned to the client. This closes an information-leak class flagged in the
security audit: the previous handler echoed `str(exc)` directly, which included `OCR processing failed for
{filename}: {paddleocr stack frame…}`.

`detail` strings additionally must NOT carry units, quantities, or locale-formatted values (no `"File exceeds 50
MB"`, no `"Limit reached: 60/minute"`). Localisation of human-facing copy is the caller's responsibility; the
service speaks one stable English string per code. If a future failure mode genuinely needs to expose a number
to the caller (e.g., the actual size limit), add it as a separate top-level field (`"limit_mb": 50`) rather than
embedding it in `detail`. This rule was added to the catalog after the design-system-architect review on
2026-05-31.

### Relation to RFC 7807 Problem Details

The `/api-design` skill recommends `application/problem+json` per RFC 7807 with the canonical
`{type, title, status, detail, instance}` shape. ascend-ocr deliberately deviates from RFC 7807 in favour of a
narrower `{code, detail}` body for these reasons:

- **`code` is the stable machine field**, not `type`. URIs as type identifiers add zero value for an internal
  monorepo service; agents already pattern-match on string identifiers, not URIs.
- **No `title` field.** `code` carries the categorisation; a separate `title` is duplicate information.
- **No `instance` field.** The correlation ID is already propagated via the `X-Request-ID` response header (see
  ADR-001 mentions of the `CorrelationIdMiddleware`); embedding a URI here would duplicate that signal.
- **HTTP status code already conveys severity class.** REST status is the authoritative signal for retry
  semantics; the `code` field disambiguates *which* category within that class fired.

The cost: tooling that auto-renders RFC 7807 bodies (some API gateway dashboards, the `httpx` problem-details
helper) will not auto-format our errors. Acceptable trade-off - neither ascend-ai-agent nor the Bruno collection
relies on such tooling. If a public-facing surface is ever introduced, re-evaluate by minting a v2 catalog that
emits `application/problem+json` alongside the current shape.

## Consequences

### Why this shape

- **Stable contract for retry-aware agents.** A consumer can build a static map from code → retry strategy without inspecting the human message, which is allowed to change for readability.
- **Same code on both surfaces.** A future migration from REST to MCP (or vice versa) does not change the error model - only the transport.
- **Information hiding by default.** Internal stack frames stay server-side; clients see a category, not a leak.

### Trade-offs

- **One more layer of indirection.** Adding a new failure mode now requires (1) an exception class, (2) a handler, (3) an entry in this catalog, (4) tests. Acceptable for the value of stable codes.
- **MCP-side codes are only soft-stable** until FastMCP surfaces `error.data.code` natively. Until then agents pattern-match on the exception name in the JSON-RPC error frame's `message`. Worth re-visiting on the next FastMCP bump.

### Alternatives considered

- **REST stays HTTP-only, MCP raises freely.** Rejected - forces the agent to maintain two parallel error-handling code paths.
- **Use HTTP status codes for MCP too.** Rejected - MCP is JSON-RPC, not HTTP semantically; pretending the status code is the source of truth invites confusion when MCP runs over stdio or WebSocket.

## Related

- `apps/ascend-ocr/src/api/exception_handlers.py` - class definitions, handlers, code constants.
- `apps/ascend-ocr/src/api/mcp/mcp_server.py` - raises the same exception classes from the MCP path.
- `apps/ascend-ocr/src/api/rest/rest_endpoints.py` - raises the same exception classes from the REST path.
- `apps/ascend-ocr/tests/api/test_exception_handlers.py` - asserts shape and that no internal detail leaks.
- ADR-001 - defines the `UnsafeUriError` and `DownloadFailedError` raise conditions.


## Amendment (2026-09-24): two new codes, and three reasons that are not statuses

[ADR-008](ADR-008-every-request-is-a-job.md) made every request a job, which added two failures a caller can meet
and one distinction this catalogue did not previously have to make.

Two codes join the catalogue, on both surfaces, with the same `{"code": "...", "detail": "..."}` shape as every
existing one. Adding a code is non-breaking under [ADR-003](ADR-003-versioning-strategy.md)'s own table.

| Code | REST status | When raised |
| :--- | :--- | :--- |
| `QUEUE_FULL` | 503, with `Retry-After` | A submission would exceed `OCR_JOB_QUEUE_MAX_PAGES` or `OCR_JOB_QUEUE_MAX_DOCUMENTS`. |
| `JOB_NOT_FOUND` | 404 | The identifier is unknown, its retention window has passed, or it is not shaped like an identifier this service issues. The three are deliberately indistinguishable. |

`QUEUE_FULL` is a 503 rather than the rate limiter's 429 because the two mean different things to a client. 429 says
this caller is asking too often and the fix is to slow down. 503 says the service is temporarily out of capacity and
the fix is to come back, which is true regardless of who is asking, carries `Retry-After` naturally, and keeps the
rate limiter's own metrics honest.

**Three further reasons are never HTTP statuses.** `SERVICE_RESTARTED`, `RESULT_STORE_UNAVAILABLE` and
`LIFETIME_EXCEEDED` live inside a job record, in its `error_code` field beside a human `error_reason`, because the
request that reads a failed record succeeded. That is the one place where the shape of a failure changed with the job
surface, and it deserves saying plainly rather than being discovered: a failure of the reading is a successful read of
a record that says it failed.

| Reason | Meaning | Retryable |
| :--- | :--- | :--- |
| `OCR_FAILED` | The service tried to read this document and could not, including a reading that ran out of budget. | No |
| `SERVICE_RESTARTED` | The service stopped while the work was waiting or running. Nothing was learned about the document. | Yes |
| `RESULT_STORE_UNAVAILABLE` | The text could not be written to the bucket after bounded retries. Nothing was learned about the document. | Yes |
| `LIFETIME_EXCEEDED` | The record was still waiting or running past the longest legitimate wait plus the longest legitimate read. | No |
| `INTERNAL_ERROR` | An unexpected failure while reading. | No |

The record carries `retryable` as a boolean as well as the reason, so a caller acts on the contract rather than on a
hardcoded list of strings. `OCR_FAILED` keeps exactly the meaning it always had.

The input-limits requirement that refusals introduce no new error code is not contradicted. It governs refusals of
oversized input, and those still answer `FILE_TOO_LARGE`, including the page ceiling. Neither new code is
a refusal of oversized input.

## Second amendment (2026-09-25): `UNSUPPORTED_LANGUAGE`

A language outside `SUPPORTED_LANGUAGES` used to be accepted with 202 and a job identifier, queued, and only refused
inside the worker, where the engine lookup raised and the job ended `OCR_FAILED`. With `ru` and `korean` switched off
([ADR-011](ADR-011-explicit-preprocessing-and-straighten.md)) that became a live defect: a caller was handed an
identifier for work that could never succeed. The refusal now happens at submission, on both surfaces, before
anything is fetched, stored or queued, and no identifier is issued.

| Code | REST status | When raised |
| :--- | :--- | :--- |
| `UNSUPPORTED_LANGUAGE` | 400 | `POST /v1/ocr/jobs` or `ocr_submit` named a `lang` outside `SUPPORTED_LANGUAGES`. |

The REST body is `{"code": "UNSUPPORTED_LANGUAGE", "detail": "Language is not supported. Supported languages: en, pl, de, fr, es, it, pt, nl, ch, japan"}` at the shipped defaults. The MCP tool
error reads `UNSUPPORTED_LANGUAGE: ` followed by the same detail, and `ocr_submit` refuses before it fetches the URI.
Unlike every other code, the detail is not a fixed phrase: it lists the supported languages, so a caller can correct
the request without reading the documentation. It is built from configuration alone and never echoes the language
the caller sent. The worker's own check stays as a defence for a record that reached the queue some other way.
Adding a code is non-breaking under [ADR-003](ADR-003-versioning-strategy.md)'s own table.

## Third amendment (2026-09-25): an expected refusal is one warning, never an error with a traceback

The 2026-09-25 end-to-end run found every refused MCP call logged at ERROR with a full traceback. The tool raised the
service's own exception, and FastMCP logs any exception a tool raises through `logger.exception`, so a refusal that
worked exactly as designed, such as the SSRF guard or the `file://` jail, looked like a server fault in the log.

An expected refusal is now logged the same way on both surfaces: one WARNING line naming its code, with no
traceback, written by `log_refusal` in `src/api/exception_handlers.py`. The codes it covers are `UNSAFE_URI`,
`UNSUPPORTED_FILE_TYPE`, `FILE_TOO_LARGE`, `UNSUPPORTED_LANGUAGE`, `QUEUE_FULL` and `JOB_NOT_FOUND`, which are
refusals, and `DOWNLOAD_FAILED`, which is an upstream failure the REST handler already logged at WARNING and which is
kept identical across the two surfaces. `JOB_NOT_FOUND` and `UNSUPPORTED_LANGUAGE` move from INFO to WARNING with
them. The line carries the detail the service wrote, which names a scheme, a host or a path and never the userinfo of
a URI.

On MCP, `_mcp_error_codes` in `src/api/mcp/mcp_server.py` raises FastMCP's own `ToolError`, chained to the service's
exception, with its log level set to DEBUG, so FastMCP writes no line of its own at the level the service runs at.
The tool error a caller reads is now `CODE: detail`, for example `UNSAFE_URI: Credentials in URI are not permitted`,
without the `Error calling tool 'ocr_submit': ` prefix FastMCP used to put in front of it. The code is still the
first thing in the text, which is what callers match on. Every other exception, `OCR_FAILED` and `INTERNAL_ERROR`
included, keeps the level it had, and an unexpected exception is still logged at ERROR with its traceback.

## Fourth amendment (2026-09-25): every MCP request has its own correlation id

The 2026-09-25 end-to-end run found every tool call in one MCP session logged under the correlation id of the
`initialize` request that opened the session, so two calls in one session could not be told apart in the log. The
cause is how the MCP SDK runs a stateful Streamable HTTP session: the session's server task is started while the
`initialize` request is being handled, so it inherits that request's context variables, and every later tool call
runs inside that task rather than inside the HTTP request that carried it.

Every MCP request, tool calls, `tools/list`, resources and prompts alike, is now logged under the correlation id of
the HTTP request that carried it. `CorrelationIdMiddleware` leaves the id it chose in the request's ASGI scope, and
`McpRequestLogContextMiddleware` in `src/api/mcp/request_log_context.py`, a FastMCP middleware on `on_request`, reads
it from the request the MCP SDK attaches to the MCP request and binds it until that request is answered. The id
therefore matches the `x-request-id` header on that request's own response, and a caller that sends an acceptable
`x-request-id` sees its own value in the log. `CorrelationIdMiddleware` accepts an inbound value only when it is 1 to
128 characters of letters, digits, `.`, `_`, `:` and `-`, and replaces any other value with a fresh id. An MCP request
with no HTTP request attached keeps the id already bound, which for `initialize` is the id of its own HTTP request,
and gets a fresh id when none is bound.

The MCP SDK writes one INFO line of its own, `Processing request of type ...`, in `mcp/server/lowlevel/server.py`
before any FastMCP middleware runs. That line cannot carry the id of the request it names and carries the id of the
`initialize` request that opened the session instead. Its level is left as the SDK sets it.

Every line written while `McpRequestLogContextMiddleware` has an MCP request bound also carries `mcp_session_id`,
the first 16 hex characters of the SHA-256 digest of the `mcp-session-id` header, so the requests of one session can
still be grouped. The digest comes from one function, `digest_of_mcp_session_id` in
`src/api/middleware/correlation_id.py`, and the log field, the log redaction and the span exporter below all use it.
The raw session id is the handle to a live session, and anyone who could read the log and reach the service port
could open the session's stream or delete it, so it must not leave the process.

The MCP SDK writes the raw id itself. In the installed mcp 1.27.2, `mcp/server/streamable_http_manager.py` logs
`Created new transport with session ID ...`, `Session ... idle timeout` and `Cleaning up crashed session ...` at INFO
and `Session ... crashed` at ERROR with a traceback, and `mcp/server/streamable_http.py` logs
`Terminating session: ...` at INFO when a caller sends DELETE. Each module writes through a logger named after
itself, `mcp.server.streamable_http_manager` and `mcp.server.streamable_http`. `McpSessionIdRedactionFilter` in
`src/api/middleware/correlation_id.py` runs in two places. `setup_logging` attaches one instance as a logger filter on
each of those two loggers, and a second instance as a handler filter next to `CorrelationIdLogFilter` on the root
handler, in both log formats. A logger filter on the logger that creates a record always runs, before the record
reaches any handler, so a handler added to the root logger later, for example OpenTelemetry's `LoggingHandler`, never
sees the raw id. A logger filter on a parent logger would not run for records that propagate up from a child, which is
why the filter sits on the two exact loggers the SDK writes with. The handler filter on the root handler stays as a
second layer. For every record whose logger name starts with `mcp.server.streamable_http`, the filter replaces each
run of exactly 32 hex characters (the SDK makes a session id with `uuid4().hex`) with its digest, in the message and
in the traceback text when there is one. The digest is 16 characters, so a second pass changes nothing.

The rewrite is not limited to session ids. Every run of exactly 32 hex characters in a line from those two loggers is
written as its digest, whatever it is. A client can choose a JSON-RPC request id of that shape, and if the SDK writes
it in one of its DEBUG lines, the log shows its digest and not the value the client sent. This is accepted: the filter
cannot tell a session id from another 32-hex value without the SDK's own knowledge of which one it is, and the only
loss is a detail in the SDK's own transport lines.

These SDK lines are written outside the FastMCP middleware. The `Created new transport` line, and the idle timeout,
crash and clean-up lines that the session's own task writes, carry the correlation id of the `initialize` request,
the digest only inside their message text, and no `mcp_session_id` value. The `Terminating session` line carries the
id of the DELETE request and, since 2026-10-01, that request's session digest in `mcp_session_id` as well (see the
next paragraph).

The 2026-10-01 end-to-end run found uvicorn's access line for `POST /mcp` with the right `correlation_id` and
`mcp_session_id` `null`, although the request carried an `mcp-session-id` header and every other line of it carried
the digest. Uvicorn writes the access line inside the server's `send`, when the response start is sent, in the HTTP
request's own task. `McpRequestLogContextMiddleware` binds the digest in the SDK's session task, so the value is not
visible there. `CorrelationIdMiddleware` now binds the digest in the request's own task as well, for the whole
request, when the request carries an `mcp-session-id` header the MCP SDK accepts (visible ASCII, the SDK's
`SESSION_ID_PATTERN`, imported rather than restated). It digests the header with `digest_of_mcp_session_id`, the same
function the FastMCP middleware uses, and never stores or logs the raw value. Every line written in the request's own
task then carries the digest, the access line and `Terminating session` included. An `initialize` request carries no
such header, because its response creates the session. Its access line is the only line in which the opening
request's `correlation_id` can stand next to the session's digest as a field, so `CorrelationIdMiddleware` reads the
`mcp-session-id` header of the response and binds its digest only while the response start is sent. The other lines
of `initialize`, `Created new transport` among them, are written before that and keep `null`. Nothing outlives the
request: both bindings are reset when the request ends, whether the app returns, raises after the response start, is
cancelled inside the server's `send`, or sends the response start from a task it started (the SSE path).

A security review on 2026-10-01 found two gaps in that change. First, the request-level digest was bound on every
route, so a caller could send an `mcp-session-id` header to `POST /v1/ocr/jobs` or `GET /health` and every line of
that REST request then carried the digest of a value the caller chose. `CorrelationIdMiddleware` now binds a digest,
from the request header or from the response header, only for a request whose path is exactly `MCP_ENDPOINT_PATH`
(`/mcp`, in `src/config/config.py`). `src/main.py` passes that one constant to `mcp.http_app`, whose app is mounted at
`/`, and to the middleware, so the two cannot disagree. Every line of a request to any other path has
`mcp_session_id` `null`. On the MCP endpoint the digest is still of the value the caller sent and not proof that a
session exists: the access line of the 404 the SDK answers for an unknown or expired session carries the digest of
that value, and it names no live session.

Second, `CorrelationIdMiddleware` was registered with `add_middleware`, which places it inside Starlette's
`ServerErrorMiddleware`. When an unhandled exception ended a request, both bindings were already reset by the time
`ServerErrorMiddleware` ran `_global_exception_handler` and sent the 500, so the `INTERNAL_ERROR` line and the 500's
access line carried `correlation_id` `-` and the 500 had no `x-request-id`. The app is now a FastAPI subclass in
`src/main.py` whose `build_middleware_stack` wraps Starlette's whole stack in `CorrelationIdMiddleware`, which is
registered nowhere else. Uvicorn writes its own `Exception in ASGI application` line in its protocol code after the
app has raised, outside every ASGI layer, where no binding can reach. The middleware therefore attaches the request's
correlation id and session digest to the exception as it leaves, and `CorrelationIdLogFilter` uses them for a record
whose exception carries them when no request is bound, never in place of ids that are bound. Both ERROR lines and
the access line of a 500 now carry the request's `correlation_id`, and the session digest for a request to the MCP
endpoint, and the 500 carries `x-request-id`.

FastMCP 3.3.1 sets up its own `fastmcp` logger when it is imported, with a Rich handler and `propagate=False`, so its
lines skipped both filters and the JSON format. `setup_logging` in `src/config/logging_config.py` now removes that
logger's handlers, sets its level to `NOTSET` and turns propagation on. FastMCP's lines then go through the same
handlers, filters and format as every other line, and `LOG_LEVEL` decides which of them are written.
`FASTMCP_LOG_LEVEL` no longer has any effect.

Uvicorn sets up its own loggers too. The container starts the service with `python3.11 -m uvicorn src.main:app --ws none`
and no `--log-config`, and uvicorn 0.48.0 then applies its own `LOGGING_CONFIG`: plain text handlers on `uvicorn` and
`uvicorn.access` with `propagate=False` and neither filter. It applies that before it imports `src.main`, in every
launch mode (the container command, the local command with `--reload`, `python -m src.main`, and each child process
uvicorn starts). `setup_logging` runs when `src.main` is imported, so it treats `uvicorn`, `uvicorn.error` and
`uvicorn.access` exactly as it treats `fastmcp`: it removes their handlers, sets their level to `NOTSET` and turns
propagation on. Access lines, uvicorn's own lines and the service's lines written through the `uvicorn` logger (the
startup line in `src/main.py` and the startup banner in `src/config/startup_banner.py`) all go through the root
handler, with its format and both filters. There is one log setup, in `setup_logging`, and no separate uvicorn log
configuration. Only a line uvicorn writes before the app is imported, such as the error for an app that cannot be
imported, still uses uvicorn's own format. `LOG_LEVEL` decides which uvicorn lines are written. Uvicorn's
`--log-level` has no effect on them, and neither has `--no-access-log`, because the access logger reaches the root
handler again once propagation is on.

With tracing on (`OTEL_ENABLED=true`, which `compose.yaml` sets), FastMCP puts the raw id on every server span as the
attribute `mcp.session.id`. `_configure_provider` in `src/observability/tracing.py` wraps the OTLP exporter in
`McpSessionDigestSpanExporter`, which passes each span on with the raw id replaced by its digest, so every span that
leaves the process carries only the digest. It rewrites three attribute keys: `mcp.session.id`, and
`http.request.header.mcp_session_id` and `http.response.header.mcp_session_id`, which are the keys the installed
OpenTelemetry ASGI instrumentation 0.63b1 (`normalise_request_header_name` and `normalise_response_header_name` in
`opentelemetry.util.http`) gives the `mcp-session-id` header when header capture is turned on. Header capture is off
today, and the two header keys are rewritten so that turning it on cannot leak the id. A captured header is a list of
values, and each value is replaced by its digest. The rewritten span keeps everything else of the original: its
events, links, status, resource, instrumentation scope, and the counts of attributes, events and links the SDK
dropped at its limits. The main process and every OCR worker build their tracer provider through that one function.

Which lines carry which fields. In the JSON format every line names both `correlation_id` and `mcp_session_id`.
`correlation_id` is `-` on a line written outside any request, except uvicorn's `Exception in ASGI application` line,
which carries the id of the request whose exception it reports. `mcp_session_id` is the session digest on every line
written while an MCP request is bound in the SDK's session task, on every line written in the task of an HTTP request
to the MCP endpoint that carries an acceptable `mcp-session-id` header (its access line, the 404 for an unknown
session, `Terminating session` and the ERROR lines of a 500 included), and on the access line of `initialize`. It is
`null` on every other line: every line of a request to any other path (every REST line, `/health`, `/ready` and
`/metrics` included, whatever headers the request sends), every other line of `initialize` (`Created new transport`
included), every line written outside any request, and the idle timeout, crash and clean-up lines the session's own
task writes. The color format prints both as
`[<correlation_id> <mcp_session_id>]` after the module name on every line, uvicorn's included, and prints `-` for
either one when it is missing. The one SDK line that cannot carry the id of its own request
is `Processing request of type ...`, which `mcp/server/lowlevel/server.py` writes before any FastMCP middleware runs.
It carries the correlation id of the `initialize` request that opened the session, has no `mcp_session_id` value, and
names no session.

`correlation_id` is chosen by the caller whenever the caller sends an acceptable `x-request-id`. Two callers can send
the same value, and a caller can send a value it read on the response to someone else's request. It is a debugging
aid for following one request through the log, and it must never be used to decide who did something.
