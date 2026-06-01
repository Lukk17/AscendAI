# ADR-002: RFC 7807 error envelope + redacted internals

**Date**: 2026-06-01
**Status**: Accepted

---

## Context

Previously every error path used `HTTPException(detail=f"...{e}")`, interpolating the raw exception string into the
response body. Upstream errors from OpenAI / HF / faster-whisper can include API key fragments (`sk-...`,
`Bearer ...`), file paths, and stack frames. The endpoint contract diverged from sibling services (AscendMemory,
AscendWebSearch) which adopted RFC 7807 envelopes.

---

## Decision

All error responses use `application/problem+json` with the RFC 7807 shape (`type`, `title`, `status`, `instance`,
optionally `detail`). Three FastAPI exception handlers in `src/api/exception_handlers.py`:

- `ValueError` → 400 with `detail` carrying the service-authored message (safe to surface; we wrote it).
- `FileSizeExceededError` (ValueError subclass) → 413 with `detail` carrying the cap.
- `Exception` (catch-all) → 500 with `detail` dropped entirely. Only `instance` (request path) is surfaced.

The MCP surface uses an equivalent structured envelope:
`{"status": "error", "code": "validation_error" | "internal_error", "operation": "...", "message": "..."}`.

Every error path is correlated by the `X-Request-ID` header (regex-validated, max 128 chars). The full exception
is logged with `logger.exception(...)` server-side. (`src/api/exception_handlers.py`, `src/api/mcp/mcp_server.py`,
`src/observability/request_context.py`)

---

## Alternatives Considered

### Alternative 1: Keep ad-hoc `{"detail": str(e)}`

- **Cons**: Continued leakage of API key fragments and internal paths. Inconsistent with siblings.

### Alternative 2: Generic 500 with no body at all

- **Cons**: Loses the request-path correlation, debugging across services becomes harder.

---

## Consequences

### Positive

- Client error handling is uniform across the platform; one switch statement on `type` works for every service.
- API key fragments cannot leak via 500 responses.
- The `X-Request-ID` correlation makes "what failed for this request?" trivially answerable from log aggregation.

### Negative

- Slightly larger response bodies on errors (extra `type` / `instance` fields).
- One more middleware in the stack adds ~1 ms per request for the X-Request-ID parsing.
