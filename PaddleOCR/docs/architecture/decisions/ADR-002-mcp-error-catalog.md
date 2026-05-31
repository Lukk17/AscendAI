# ADR-002: MCP error code catalog mirrors the REST surface

## Status

Accepted — 2026-05-31

## Context

PaddleOCR exposes the same OCR capability via two surfaces: REST (`POST /v1/ocr`, multipart) and MCP (`tools/call name="ocr_process"`). The two transports return errors very differently by default.

REST returns mapped HTTP status codes — `400` for input validation failures, `422` for OCR engine failure, `502` for downstream fetch failure, `500` for unhandled exceptions. The mapping is enforced by FastAPI's exception-handler registry.

MCP, by contrast, wraps the call in a JSON-RPC envelope. If the tool raises, FastMCP converts the exception to a JSON-RPC error frame. From the agent caller's perspective every exception arrives as "the tool errored" — there is no native equivalent of HTTP 4xx vs 5xx, no native way to distinguish "retry with different input" from "give up." An agent that batches OCR calls behind retries can either re-try `UnsafeUriError` indefinitely or stop retrying `OcrProcessingError` after a single transient failure.

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

`src/api/exception_handlers.py` defines the exception classes (`OcrProcessingError`, `FileSizeExceededError`, `UnsupportedFileTypeError`, `UnsafeUriError`, `DownloadFailedError`) and registers a FastAPI handler per class that emits the `{"code", "detail"}` body. The MCP tool wrapper raises the same exception classes. FastMCP currently surfaces the exception name + message in the JSON-RPC error frame; downstream agents should pattern-match on the exception name (which equals the code's domain — e.g., `UnsafeUriError` ↔ `UNSAFE_URI`) until FastMCP supports a structured `error.data.code` field natively.

### Detail messages are generic and locale-neutral

The `detail` field in the response carries a generic human-readable phrase ("OCR processing failed", "File too
large"), not the original exception's repr. Internal details — file paths, stack frames, upstream URLs — are
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
`{type, title, status, detail, instance}` shape. PaddleOCR deliberately deviates from RFC 7807 in favour of a
narrower `{code, detail}` body for these reasons:

- **`code` is the stable machine field**, not `type`. URIs as type identifiers add zero value for an internal
  monorepo service; agents already pattern-match on string identifiers, not URIs.
- **No `title` field.** `code` carries the categorisation; a separate `title` is duplicate information.
- **No `instance` field.** The correlation ID is already propagated via the `X-Request-ID` response header (see
  ADR-001 mentions of the `CorrelationIdMiddleware`); embedding a URI here would duplicate that signal.
- **HTTP status code already conveys severity class.** REST status is the authoritative signal for retry
  semantics; the `code` field disambiguates *which* category within that class fired.

The cost: tooling that auto-renders RFC 7807 bodies (some API gateway dashboards, the `httpx` problem-details
helper) will not auto-format our errors. Acceptable trade-off — neither AscendAgent nor the Bruno collection
relies on such tooling. If a public-facing surface is ever introduced, re-evaluate by minting a v2 catalog that
emits `application/problem+json` alongside the current shape.

## Consequences

### Why this shape

- **Stable contract for retry-aware agents.** A consumer can build a static map from code → retry strategy without inspecting the human message, which is allowed to change for readability.
- **Same code on both surfaces.** A future migration from REST to MCP (or vice versa) does not change the error model — only the transport.
- **Information hiding by default.** Internal stack frames stay server-side; clients see a category, not a leak.

### Trade-offs

- **One more layer of indirection.** Adding a new failure mode now requires (1) an exception class, (2) a handler, (3) an entry in this catalog, (4) tests. Acceptable for the value of stable codes.
- **MCP-side codes are only soft-stable** until FastMCP surfaces `error.data.code` natively. Until then agents pattern-match on the exception name in the JSON-RPC error frame's `message`. Worth re-visiting on the next FastMCP bump.

### Alternatives considered

- **REST stays HTTP-only, MCP raises freely.** Rejected — forces the agent to maintain two parallel error-handling code paths.
- **Use HTTP status codes for MCP too.** Rejected — MCP is JSON-RPC, not HTTP semantically; pretending the status code is the source of truth invites confusion when MCP runs over stdio or WebSocket.

## Related

- `PaddleOCR/src/api/exception_handlers.py` — class definitions, handlers, code constants.
- `PaddleOCR/src/api/mcp/mcp_server.py` — raises the same exception classes from the MCP path.
- `PaddleOCR/src/api/rest/rest_endpoints.py` — raises the same exception classes from the REST path.
- `PaddleOCR/tests/api/test_exception_handlers.py` — asserts shape and that no internal detail leaks.
- ADR-001 — defines the `UnsafeUriError` and `DownloadFailedError` raise conditions.
