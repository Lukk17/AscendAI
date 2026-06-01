# 4. Solution Strategy

---

### Dual REST and MCP surface

PaddleOCR exposes the same OCR capability via two surfaces mounted on a single FastAPI app. The REST router
(`src/api/rest/rest_endpoints.py`) handles multipart file uploads at `POST /v1/ocr`. The MCP server
(`src/api/mcp/mcp_server.py`) handles agent tool calls at `POST /mcp`. Both surfaces call
`ocr_service.process_file(file_bytes, filename, language)` from `src/service/ocr_service.py` and both raise the same
exception classes registered in `src/api/exception_handlers.py`. See [ADR-002](../decisions/ADR-002-mcp-error-catalog.md)
for why a shared error catalog matters.

The MCP server is mounted as an ASGI sub-application at the root (`/`) in `src/main.py:55`. Paths not matched by
FastAPI's own routes fall through to the MCP ASGI app, so the two surfaces co-exist on port 7022 without a proxy.

---

### Model warm-up in lifespan

PaddleOCR's first OCR call per language triggers model loading, which takes 5-15 seconds on CPU. Doing that during
the first real request would make it appear to hang. Instead, `ocr_service.warm_up_engine(settings.DEFAULT_LANGUAGE)`
runs inside the FastAPI lifespan at startup (`src/main.py:29`). The `/ready` endpoint reflects `engine_warm` as soon
as the load completes. Until then, `/ready` returns `{"status": "not-ready"}` and a load balancer can hold traffic.
See [ADR-004](../decisions/ADR-004-liveness-readiness-split.md).

---

### OCR offloaded to a thread pool

`PaddleOCR.predict()` is CPU-bound and synchronous. Running it directly on the async event loop would block all
other in-flight requests. Both the REST endpoint and the MCP tool wrap the call in `asyncio.to_thread(...)` with a
configurable timeout (`OCR_REQUEST_TIMEOUT`, default 120 s). This keeps the event loop free for health probes and
concurrent HTTP sessions during a long OCR job.

---

### LRU engine cache with language allowlist

The OCR engine for each language is expensive to construct (model weights are loaded into memory). `OcrService` keeps
an `OrderedDict[str, PaddleOCR]` as an LRU cache capped at `ENGINE_CACHE_MAX_SIZE` (default 8, configured via env).
Access promotes an entry to the tail; eviction removes from the head. Languages not in `SUPPORTED_LANGUAGES` raise
`ValueError` before any engine allocation, preventing unbounded memory use from caller-controlled language codes.

---

### URI-only MCP input with layered SSRF guard

Accepting arbitrary URIs in the MCP tool is a classic SSRF surface. The solution is a layered guard described in
[ADR-001](../decisions/ADR-001-mcp-file-transport-uri-only.md): a small explicit allowlist for internal docker
hostnames (`MCP_ALLOWED_HOSTS`), combined with a DNS-resolution IP block that rejects private, loopback, link-local,
and multicast addresses. The `file://` scheme is disabled by default and requires an operator opt-in via
`MCP_FILE_URI_ROOT`.
