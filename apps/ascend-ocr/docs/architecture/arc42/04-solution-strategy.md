# 4. Solution Strategy

---

### Dual REST and MCP surface

ascend-ocr exposes the same OCR capability via two surfaces mounted on a single FastAPI app. The REST router
(`src/api/rest/rest_endpoints.py`) handles multipart file uploads at `POST /v1/ocr`. The MCP server
(`src/api/mcp/mcp_server.py`) handles agent tool calls at `POST /mcp`. Both surfaces call
`ocr_service.process_file(file_bytes, filename, language)` from `src/service/ocr_service.py` and both raise the same
exception classes registered in `src/api/exception_handlers.py`. See [ADR-002](../decisions/ADR-002-mcp-error-catalog.md)
for why a shared error catalog matters.

The MCP server is mounted as an ASGI sub-application at the root (`/`) in `src/main.py:55`. Paths not matched by
FastAPI's own routes fall through to the MCP ASGI app, so the two surfaces co-exist on port 7022 without a proxy.

---

### Model warm-up in the OCR worker process

ascend-ocr's first OCR call per language triggers model loading, which takes 5-15 seconds on CPU. Doing that during
the first real request would make it appear to hang, and doing it in the main process would hold a second, unused
copy of the model (~316 MiB) for the container's whole life, since inference always runs in the separate OCR worker
process (see the next section). Instead, `ocr_service.warm_up_engine(settings.DEFAULT_LANGUAGE)` runs as the worker
pool's initializer, inside that worker process, and `start_worker_pool()` (`src/main.py`'s lifespan) blocks at
startup until it completes. The `/ready` endpoint reflects `engine_warm` by reading the worker's own warm-up signal
across the process boundary, not by warming anything itself. Until the worker reports warm, `/ready` returns
`{"status": "not-ready"}` and a load balancer can hold traffic. See
[ADR-004](../decisions/ADR-004-liveness-readiness-split.md).

---

### OCR offloaded to a worker process pool

`PaddleOCR.predict()` is CPU-bound, synchronous, and holds the GIL almost continuously for the entire call. Running it
directly on the async event loop, or even via `asyncio.to_thread`, would freeze that event loop for the call's whole
duration. Both the REST endpoint and the MCP tool instead submit the call to a single-worker `ProcessPoolExecutor`
(`start_worker_pool` in `src/service/ocr_service.py`) via `loop.run_in_executor(get_process_pool(), ...)`, wrapped in
`asyncio.wait_for` with a configurable timeout (`OCR_REQUEST_TIMEOUT`, default 120 s). Running inference in a
separate OS process, with its own GIL, keeps the event loop free for health probes and concurrent HTTP sessions
during a long OCR job.

---

### LRU engine cache with language allowlist

The OCR engine for each language is expensive to construct (model weights are loaded into memory). `OcrService` keeps
an `OrderedDict[str, PaddleOCR]` as an LRU cache capped at `ENGINE_CACHE_MAX_SIZE` (default 2, configured via env).
Access promotes an entry to the tail; eviction removes from the head. Languages not in `SUPPORTED_LANGUAGES` raise
`ValueError` before any engine allocation, preventing unbounded memory use from caller-controlled language codes.

The default of 2 matches what the Dockerfile actually pre-caches (`en`, `pl` — see its warm-up `RUN` instruction),
not the full twelve-language `SUPPORTED_LANGUAGES` allowlist. The honest trade: a caller may request any of the
twelve, but only two engines stay resident at once. A workload that alternates a third language on every call evicts
and reconstructs an engine each time instead of keeping it warm, trading request latency for a memory ceiling the
container can actually afford — see "Memory model and the single worker" in
[07-deployment-view.md](07-deployment-view.md) for why that ceiling is tight even at this lower default.

---

### URI-only MCP input with layered SSRF guard

Accepting arbitrary URIs in the MCP tool is a classic SSRF surface. The solution is a layered guard described in
[ADR-001](../decisions/ADR-001-mcp-file-transport-uri-only.md): a small explicit allowlist for internal docker
hostnames (`MCP_ALLOWED_HOSTS`), combined with a DNS-resolution IP block that rejects private, loopback, link-local,
and multicast addresses. The `file://` scheme is disabled by default and requires an operator opt-in via
`MCP_FILE_URI_ROOT`.
