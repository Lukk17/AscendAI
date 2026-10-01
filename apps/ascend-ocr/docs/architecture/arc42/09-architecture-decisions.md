# 9. Architecture Decisions

---

### ADR index

| ADR | Title | Status | Key trade-off |
| :--- | :--- | :--- | :--- |
| [ADR-001](../decisions/ADR-001-mcp-file-transport-uri-only.md) | MCP file transport: URI-only with SSRF guard and `file://` jail | Accepted | Allowlist + IP block over either alone; `file://` opt-in only |
| [ADR-002](../decisions/ADR-002-mcp-error-catalog.md) | Shared error code catalog for REST and MCP | Accepted | One more indirection layer for stable retry semantics |
| [ADR-003](../decisions/ADR-003-versioning-strategy.md) | URL versioning (REST) and tool-name versioning (MCP) | Accepted | Tool-name versioning is awkward UX; only option MCP provides today |
| [ADR-004](../decisions/ADR-004-liveness-readiness-split.md) | Liveness (`/health`) and readiness (`/ready`) split | Accepted | Two endpoints to document; cheap O(1) probes |
| [ADR-005](../decisions/ADR-005-fixed-pdf-render-resolution.md) | The fixed 144 dpi PDF rendering resolution is accepted, recorded, and not exposed | Superseded by ADR-010 | A dense scan cannot be read at higher quality, in exchange for a bounded per-page cost |
| [ADR-006](../decisions/ADR-006-detector-input-bound.md) | Bound what text detection sees; the deployed value is measured against real documents | Partly superseded by ADR-010 | Memory against detected lines on small text; 1536 chosen as near lossless |
| [ADR-007](../decisions/ADR-007-explicit-ocr-model-selection.md) | Name the OCR models explicitly, ship PP-OCRv6 small, key the engine cache by the pair | Accepted | A vendor benchmark rather than a local measurement decides the family member; rollback is two settings |
| [ADR-008](../decisions/ADR-008-every-request-is-a-job.md) | Every request is a job, at every length, on both surfaces | Accepted | Two round trips for a one page image, in exchange for a length ceiling no client timeout sets |
| [ADR-009](../decisions/ADR-009-results-in-object-storage.md) | A finished result is a Markdown file in object storage, and the state carries its address | Accepted | An external service dependency this module did not have, in exchange for a polled answer that never grows |
| [ADR-010](../decisions/ADR-010-quality-modes-and-service-side-rendering.md) | Render pages in the service, two locked quality modes, and a page allowance per engine | Accepted | The service owns rasterization, and the slowest engine a supported language loads sets the reading ceiling and the maximum lifetime |
| [ADR-011](../decisions/ADR-011-explicit-preprocessing-and-straighten.md) | Name every preprocessing step, straighten a page only when the caller asks, and classify each text line on its own | Accepted | UVDoc stays resident in every engine so a straightened request needs no second engine, and one line orientation call per line costs time not yet measured |

---

### Decisions not (yet) recorded as ADRs

These choices exist in the code but are not currently backed by a formal ADR. They are candidates for documentation
if they become a source of debate or migration planning.

| Decision | Where it lives | Why not an ADR yet |
| :--- | :--- | :--- |
| Single-worker `ProcessPoolExecutor` for OCR offload | `ocr_service.py` (`start_worker_pool`), reached only through `job_runner.py` | Replaced an earlier `asyncio.to_thread` offload after that approach held the interpreter lock long enough to stall `/health` and `/ready` under load. Worth an ADR if the worker count or start method ever needs to change; [ADR-008](../decisions/ADR-008-every-request-is-a-job.md) now records why the count is also a promise about waiting. |
| Job records as files rather than Redis or SQLite | `service/job_store.py` | Recorded inside [ADR-009](../decisions/ADR-009-results-in-object-storage.md) rather than as its own ADR, because the choice only makes sense next to the decision to put results in a bucket. |
| `OrderedDict` as the LRU structure | `ocr_service.py:20` | Standard Python idiom; no external cache dependency considered. |
| Two-stage Docker build with pre-cached models | `Dockerfile:1-59` | Build-time model baking is common for ML services; no alternative was proposed. |
| Non-root container user (`appuser`) | `Dockerfile:41-53` | Standard hardening; no decision moment. |
