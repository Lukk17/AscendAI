# 9. Architecture Decisions

---

### ADR index

| ADR | Title | Status | Key trade-off |
| :--- | :--- | :--- | :--- |
| [ADR-001](../decisions/ADR-001-mcp-file-transport-uri-only.md) | MCP file transport: URI-only with SSRF guard and `file://` jail | Accepted | Allowlist + IP block over either alone; `file://` opt-in only |
| [ADR-002](../decisions/ADR-002-mcp-error-catalog.md) | Shared error code catalog for REST and MCP | Accepted | One more indirection layer for stable retry semantics |
| [ADR-003](../decisions/ADR-003-versioning-strategy.md) | URL versioning (REST) and tool-name versioning (MCP) | Accepted | Tool-name versioning is awkward UX; only option MCP provides today |
| [ADR-004](../decisions/ADR-004-liveness-readiness-split.md) | Liveness (`/health`) and readiness (`/ready`) split | Accepted | Two endpoints to document; cheap O(1) probes |

---

### Decisions not (yet) recorded as ADRs

These choices exist in the code but are not currently backed by a formal ADR. They are candidates for documentation
if they become a source of debate or migration planning.

| Decision | Where it lives | Why not an ADR yet |
| :--- | :--- | :--- |
| `asyncio.to_thread` for OCR offload | `rest_endpoints.py:34`, `mcp_server.py:66` | Uncontroversial for a CPU-bound library; no alternative was seriously evaluated. |
| `OrderedDict` as the LRU structure | `ocr_service.py:20` | Standard Python idiom; no external cache dependency considered. |
| Two-stage Docker build with pre-cached models | `Dockerfile:1-59` | Build-time model baking is common for ML services; no alternative was proposed. |
| Non-root container user (`appuser`) | `Dockerfile:41-53` | Standard hardening; no decision moment. |
