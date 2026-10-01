# 4. Solution Strategy

---

### Every request is a job

There is one shape for every request, at every length. A submission is written to the jobs directory, queued, and
answered with an identifier; the document is read later by a single consumer; and the recognised text is written to
object storage as one Markdown file whose address the state carries. No connection is held for the length of a
reading, so no reading is ever spent on a caller who has gone, and the page ceiling stops being a function of any
client's timeout. [ADR-008](../decisions/ADR-008-every-request-is-a-job.md) records the rejected shapes, including
the synchronous path this replaced and the two-path design that kept both.

---

### Dual REST and MCP surface

ascend-ocr exposes the same four operations via two surfaces mounted on a single FastAPI app. The REST router
(`src/api/rest/rest_endpoints.py`) handles multipart submission at `POST /v1/ocr/jobs` plus the status, list and
delete operations under the same prefix. The MCP server (`src/api/mcp/mcp_server.py`) handles `ocr_submit`,
`ocr_job_status`, `ocr_list_jobs` and `ocr_cancel_job` at `POST /mcp`. Both surfaces call the same `JobService` in
`src/service/job_service.py`, which is what makes it impossible for one surface to apply a guard, offer a state or
enforce a bound the other does not, and both raise the same exception classes registered in
`src/api/exception_handlers.py`. See [ADR-002](../decisions/ADR-002-mcp-error-catalog.md) for why a shared error
catalog matters.

The MCP server is mounted as an ASGI sub-application at the root (`/`) in `src/main.py:55`. Paths not matched by
FastAPI's own routes fall through to the MCP ASGI app, so the two surfaces co-exist on port 7022 without a proxy.

---

### Model warm-up in the OCR worker process

ascend-ocr's first OCR call per model pair triggers model loading, which takes 5-15 seconds on CPU. Doing that during
the first real request would make it appear to hang, and doing it in the main process would hold a second, unused
copy of the model (~316 MiB) for the container's whole life, since inference always runs in the separate OCR worker
process (see the next section). Instead, `ocr_service.warm_up_engine(settings.DEFAULT_LANGUAGE)` runs as the worker
pool's initializer, inside that worker process, and `start_worker_pool()` (`src/main.py`'s lifespan) blocks at
startup until it completes. The `/ready` endpoint reflects `engine_warm` by reading the worker's own warm-up signal
across the process boundary, not by warming anything itself. Until the worker reports warm, `/ready` returns
`{"status": "not-ready"}` and a load balancer can hold traffic. See
[ADR-004](../decisions/ADR-004-liveness-readiness-split.md).

---

### One queue, one consumer, one worker

`JobRunner` (`src/service/job_runner.py`) is the only component that dispatches to the worker, and it takes its input
from the queue and nowhere else. That is what makes every statement this documentation makes about what runs at once,
what waits, and for how long, true by construction rather than by convention, and a test asserts that no other module
even imports `dispatch_ocr_request`. The queue is bounded twice, in pages and in documents: pages bound the wait a
caller is promised, documents bound the disk the waiting submissions hold.

`PaddleOCR.predict()` is CPU-bound, synchronous, and holds the GIL almost continuously for the entire call. Running it
directly on the async event loop, or even via `asyncio.to_thread`, would freeze that event loop for the call's whole
duration. The runner instead submits the call to a single-worker `ProcessPoolExecutor` (`start_worker_pool` in
`src/service/ocr_service.py`) via `loop.run_in_executor(get_process_pool(), ...)`, wrapped in `asyncio.wait_for`
around the document's own reading budget, its pages times the page allowance of the engine that reads it (ADR-010). Running inference in a separate OS
process, with its own GIL, keeps the event loop free for health probes, status reads and submissions while a document
is being read.

---

### State on disk, results in the bucket

The job record is a JSON file under `OCR_JOBS_DIR`, written by temporary file plus atomic replace, with the submitted
bytes beside it until the job reaches a terminal state and a small progress file while it runs. The recognised text
is not in any of them: it goes to object storage. The split follows the access pattern. A record is written on every
transition and read on every poll, which a local file serves better than a bucket, and keeping it local is what lets
the service record that a job failed even when the bucket is the thing that failed. A result is written once, read
once or twice, may be megabytes, and is the only part anyone wants to keep.
[ADR-009](../decisions/ADR-009-results-in-object-storage.md) records the trade, including the external dependency
this module did not have before.

---

### Explicit model selection, and an LRU engine cache keyed by the models

The service names the two models it runs, `OCR_TEXT_DETECTION_MODEL` and `OCR_TEXT_RECOGNITION_MODEL`, defaulting to
`PP-OCRv6_small_det` and `PP-OCRv6_small_rec`. It does not pass a language to PaddleOCR's own resolution table, which
is how the service previously ended up on a detection model nobody had chosen. A language outside the default pair's
coverage resolves through `LANGUAGE_MODEL_OVERRIDES` in `src/config/config.py`, which is empty while `ru` and
`korean`, the two it held, are switched off (see [ADR-011](../decisions/ADR-011-explicit-preprocessing-and-straighten.md)). [ADR-007](../decisions/ADR-007-explicit-ocr-model-selection.md)
records the family, the member within it, and the rejected alternatives.

An OCR engine is expensive to construct (model weights are loaded into memory), so `OcrService` keeps an
`OrderedDict[ModelPair, PaddleOCR]` as an LRU cache capped at `ENGINE_CACHE_MAX_SIZE` (default 2, configured via
env). The key is the resolved pair of model names rather than the language, because every supported language resolves
to one pair and keying by language would hold ten identical engines. Access promotes an entry to
the tail; eviction removes from the head. Languages not in `SUPPORTED_LANGUAGES` raise `ValueError` before any model
name is resolved, preventing unbounded memory use from caller-controlled language codes.

The default of 2 is the pre-cached default pair plus one slot. While every supported language reads with the
default pair the second slot holds nothing and costs nothing. A language opted back in with a pair of its own would
occupy it without evicting the pair almost every request uses, at about 209 MiB idle. See "Memory model and the
single worker" in [07-deployment-view.md](07-deployment-view.md) for the ceiling that slot is priced against.

---

### URI-only MCP input with layered SSRF guard

Accepting arbitrary URIs in the MCP tool is a classic SSRF surface. The solution is a layered guard described in
[ADR-001](../decisions/ADR-001-mcp-file-transport-uri-only.md): a small explicit allowlist for internal docker
hostnames (`MCP_ALLOWED_HOSTS`), combined with a DNS-resolution IP block that rejects private, loopback, link-local,
and multicast addresses. The `file://` scheme is disabled by default and requires an operator opt-in via
`MCP_FILE_URI_ROOT`.
