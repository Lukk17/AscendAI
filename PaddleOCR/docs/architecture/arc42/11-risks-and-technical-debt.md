# 11. Risks and Technical Debt

---

### Risks

| Risk | Likelihood | Impact | Mitigation |
| :--- | :--- | :--- | :--- |
| **DNS TOCTOU on SSRF guard** | Low | High | `_validate_host` resolves the hostname and checks the resolved IPs, then aiohttp makes its own resolution. An attacker controlling the DNS answer can flip the IP between the two calls (DNS rebinding). Accepted trade-off today; production hardening would supply a custom aiohttp resolver that uses the already-validated address rather than re-resolving. Documented in [ADR-001](../decisions/ADR-001-mcp-file-transport-uri-only.md). |
| **PaddlePaddle wheel availability** | Medium | High | Pre-built wheels for PaddlePaddle 3.3.1 exist for Linux x86-64 on PyPI. macOS ARM and Windows builds require custom compilation or fallback to CPU-only community wheels. If PaddlePaddle drops support for a Python version before the service migrates, the build breaks with no drop-in alternative. |
| **fastmcp version skew with siblings** | Medium | Medium | AudioScribe, AscendWebSearch, and PaddleOCR all use FastMCP but at different pinned versions (`fastmcp==3.3.1` here; sibling versions may differ). A breaking FastMCP change (e.g., session handling, tool response envelope format) may surface in some services before others. Resolution: align FastMCP versions across all Python MCP services in the same monorepo bump. |
| **No content sniffing** | Medium | Medium | A caller can upload a file with `Content-Type: image/png` whose bytes are a zip bomb or malformed archive. PaddleOCR would attempt to parse it, potentially consuming large amounts of memory. The `MAX_FILE_SIZE_MB` cap limits blast radius; `python-magic`-based sniffing would close the gap. |
| **Single-worker Uvicorn** | Low | Medium | The default compose `CMD` starts one Uvicorn worker. Long OCR jobs (large PDFs) queue all concurrent requests behind the thread pool. Adding `--workers N` requires testing for session isolation of the module-level `_http_session` in `mcp_server.py`, which is a global. |

---

### Technical debt

| Item | File | Priority |
| :--- | :--- | :--- |
| No `HEALTHCHECK` instruction in Dockerfile | `PaddleOCR/Dockerfile` | Medium — Docker Desktop and compose mark the container healthy via process liveness only; operators must add a compose `healthcheck` stanza pointing at `/health` manually. |
| `MCP_ALLOWED_HOSTS` absent from default compose block | `docker-compose.yaml` | Medium — the e2e MCP test (spec 6) fails without `MCP_ALLOWED_HOSTS=minio`, but nothing in the default compose configuration sets it, making the test silently non-runnable without a manual edit. |
| Module-level `_http_session` global in `mcp_server.py` | `src/api/mcp/mcp_server.py:24` | Low — works correctly with a single Uvicorn worker. Multi-worker deployments would require moving session state into a context variable or request-local holder. |
| No `Sunset` header or deprecation window policy for REST | `src/api/rest/rest_endpoints.py` | Low — [ADR-003](../decisions/ADR-003-versioning-strategy.md) defers `Sunset` to when the client population grows. |
| Pre-cached languages limited to `en` and `pl` in Dockerfile | `PaddleOCR/Dockerfile:23` | Low — other supported languages still trigger a download at first use inside the container (if `.paddlex` cache misses). Image rebuild is required to pre-cache additional languages. |
