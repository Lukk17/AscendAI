# 11. Risks and Technical Debt

---

### Risks

| Risk | Likelihood | Impact | Mitigation |
| :--- | :--- | :--- | :--- |
| **DNS TOCTOU on SSRF guard** | Low | High | `_validate_host` resolves the hostname and checks the resolved IPs, then aiohttp makes its own resolution. An attacker controlling the DNS answer can flip the IP between the two calls (DNS rebinding). Accepted trade-off today; production hardening would supply a custom aiohttp resolver that uses the already-validated address rather than re-resolving. Documented in [ADR-001](../decisions/ADR-001-mcp-file-transport-uri-only.md). |
| **PaddlePaddle wheel availability** | Medium | High | Pre-built wheels for PaddlePaddle 3.3.1 exist for Linux x86-64 on PyPI. macOS ARM and Windows builds require custom compilation or fallback to CPU-only community wheels. If PaddlePaddle drops support for a Python version before the service migrates, the build breaks with no drop-in alternative. |
| **fastmcp version skew with siblings** | Medium | Medium | ascend-audio-scribe, ascend-web-hunter, and PaddleOCR all use FastMCP but at different pinned versions (`fastmcp==3.3.1` here; sibling versions may differ). A breaking FastMCP change (e.g., session handling, tool response envelope format) may surface in some services before others. Resolution: align FastMCP versions across all Python MCP services in the same monorepo bump. |
| **Decompression bomb via declared-but-undecoded dimensions** | Closed | — | A 40 KB PNG can declare 100 megapixels in its header; bytes are not a proxy for pixels. `src/api/limits.py` reads the declared pixel count from the header before any decode and refuses above `OCR_MAX_INFERENCE_PIXELS`, with Pillow's own `MAX_IMAGE_PIXELS` set to the same ceiling as a backstop. Measured and closed by `stop-ocr-getting-stuck-on-large-jobs`; see [ADR-006](../decisions/ADR-006-detector-input-bound.md). |
| **One inference's memory cost was unmeasured** | Closed | — | Was: an unbounded page could exhaust the container with no guard against it. Now measured: `peak_MiB = 635 + 5302 x megapixels + 11.5 x pages` (0.9993 correlation), which is why `OCR_DETECTOR_MAX_SIDE` and `OCR_MAX_INFERENCE_PIXELS` exist and why `OCR_WORKER_COUNT` is documented as a memory constraint. See "Memory model and the single worker" in [07-deployment-view.md](07-deployment-view.md) and [ADR-005](../decisions/ADR-005-fixed-pdf-render-resolution.md)/[ADR-006](../decisions/ADR-006-detector-input-bound.md). |
| **A whole-document timeout abandoned rather than stopped long jobs** | Closed | — | Was: `asyncio.wait_for` around the entire call could only cancel the *awaiting* coroutine, not the `ProcessPoolExecutor` work already running, so an abandoned job kept the sole worker occupied — measured at thirty-plus minutes past a 300 s timeout on a twenty-page document. Now: the worker checks a per-page cooperative deadline via `predict_iter()`, a worker that still does not stop within its reclamation grace is replaced, and a broken pool rebuilds itself instead of answering 500 until a manual restart. See `openspec/changes/stop-ocr-getting-stuck-on-large-jobs/`. |
| **Single-worker Uvicorn** | Low | Medium | The default compose `CMD` starts one Uvicorn worker. `OCR_WORKER_COUNT` (default `1`) governs both the OCR worker pool size and the admission gate's permit count — see "Memory model and the single worker" in [07-deployment-view.md](07-deployment-view.md) for why this is deliberately a memory constraint, not merely a throughput one, and is not raised lightly. Adding `--workers N` to Uvicorn itself (a separate axis from `OCR_WORKER_COUNT`) still requires testing for session isolation of the module-level `_http_session` in `mcp_server.py`, which is a global. |

---

### Technical debt

| Item | File | Priority |
| :--- | :--- | :--- |
| No `HEALTHCHECK` instruction in Dockerfile | `PaddleOCR/Dockerfile` | Medium — Docker Desktop and compose mark the container healthy via process liveness only; operators must add a compose `healthcheck` stanza pointing at `/health` manually. |
| `MCP_ALLOWED_HOSTS` absent from default compose block | `docker-compose.yaml` | Medium — the e2e MCP test (spec 6) fails without `MCP_ALLOWED_HOSTS=host.docker.internal`, but nothing in the default compose configuration sets it, making the test silently non-runnable without a manual edit. |
| Module-level `_http_session` global in `mcp_server.py` | `src/api/mcp/mcp_server.py:24` | Low — works correctly with a single Uvicorn worker. Multi-worker deployments would require moving session state into a context variable or request-local holder. |
| No `Sunset` header or deprecation window policy for REST | `src/api/rest/rest_endpoints.py` | Low — [ADR-003](../decisions/ADR-003-versioning-strategy.md) defers `Sunset` to when the client population grows. |
| Pre-cached languages limited to `en` and `pl` in Dockerfile | `PaddleOCR/Dockerfile:23` | Low — other supported languages still trigger a download at first use inside the container (if `.paddlex` cache misses). Image rebuild is required to pre-cache additional languages. |
