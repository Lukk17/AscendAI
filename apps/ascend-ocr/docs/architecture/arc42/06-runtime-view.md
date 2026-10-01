# 6. Runtime View

---

### Cold start sequence

```mermaid
sequenceDiagram
    participant Docker as Docker / orchestrator
    participant Uvicorn as Uvicorn process
    participant Lifespan as FastAPI lifespan
    participant Pool as OCR worker process
    participant Store as JobStore / ResultStore
    participant Runner as JobRunner
    participant MCPLife as MCP lifespan

    Docker->>Uvicorn: container start
    Uvicorn->>Lifespan: startup
    Lifespan->>Pool: start_worker_pool() - spawn + block on initializer
    Pool->>Pool: warm_up_engine("en") - PaddleOCR(det+rec model names), 5-15 s CPU
    Pool->>Pool: observe ENGINE_WARMUP_DURATION_SECONDS (PROMETHEUS_MULTIPROC_DIR)
    Pool-->>Lifespan: initializer done (or BrokenProcessPool, logged, not re-raised)
    Lifespan->>Store: result_store.ensure_bucket() - head, create when missing, warn when unreachable
    Lifespan->>Store: job_store.recover_after_restart() - fail whatever was waiting or running
    Lifespan->>MCPLife: enter mcp_lifespan
    MCPLife->>MCPLife: open aiohttp.ClientSession
    Lifespan->>Runner: job_runner.start() - sweep, then take the first document
    Lifespan->>Lifespan: log_startup_banner()
    Lifespan-->>Uvicorn: yield (service ready)
    Docker->>Uvicorn: GET /ready
    Uvicorn->>Uvicorn: is_engine_warm("en") and is_accepting_work()
    Uvicorn-->>Docker: 200 {"status":"ready","engine_warm":true,"accepting_work":true,"jobs_queued":0,"jobs_running":0}
```

Both the bucket check and the recovery pass run **before** the runner takes its first document. Recovery is what
stops a caller polling work that nothing will ever finish: every record found waiting or running becomes failed with
the `SERVICE_RESTARTED` reason, which is marked retryable because nothing was learned about the document. The service
deliberately does not resume that work, because it cannot know whether the document it was reading is what brought it
down.

The Docker `HEALTHCHECK` targets `/health`, which returns 200 immediately after the process starts. The readiness
probe at `/ready` returns `ready` only once the OCR worker process has recorded a successful warm-up **and** the
service is accepting work - see "Request budget, deadline stop, and worker reclamation" below for the four
conditions that make `accepting_work` false. During the warm-up window, and if the worker's pool initializer fails
outright, `/ready` returns `{"status":"not-ready", ...}` rather than crashing the container. See
[ADR-004](../decisions/ADR-004-liveness-readiness-split.md).

---

### Submit, poll, collect

```mermaid
sequenceDiagram
    participant Client
    participant REST as POST /v1/ocr/jobs
    participant JobSvc as JobService
    participant Store as JobStore
    participant Runner as JobRunner (single consumer)
    participant Pool as OCR worker process
    participant Bucket as ocr-results bucket

    Client->>REST: multipart upload (file, lang=pl)
    REST->>JobSvc: submit(bytes, filename, "pl", "rest")
    JobSvc->>JobSvc: byte cap, mime sniff, pixel ceiling, page ceiling (header only, no decode)
    JobSvc->>Runner: reserve(pages) - refuses with QUEUE_FULL beyond either bound
    JobSvc->>Store: create(record, bytes) - bytes written off the event loop, then the record
    JobSvc->>Runner: admit(record) - appended, runner woken
    JobSvc-->>Client: 202 {job_id, state:"waiting", pages_ahead, poll_after_seconds} + Location

    Runner->>Store: read record, read bytes, mark running
    Runner->>Pool: dispatch_ocr_request(..., quality, pages * page allowance of the engine, job_id, straighten)
    loop each page
        Pool->>Store: write progress file (job_id, pages done)
    end
    Pool-->>Runner: OcrJsonResponse
    Runner->>Bucket: PUT {job_id}.md - rendered Markdown, bounded retries
    Runner->>Store: succeed(record, bucket, key, processing_time)

    Client->>REST: GET /v1/ocr/jobs/{job_id} (every poll_after_seconds)
    REST-->>Client: 200 {state:"succeeded", result:{bucket, key, url, page_count, ...}}
    Client->>Bucket: GET by bucket and key, or by the presigned URL
    Client->>REST: DELETE /v1/ocr/jobs/{job_id} - object and record removed together
```

The object is written **before** the terminal record, so a record never claims success with no result behind it. If
the upload cannot be made after its bounded retries, the job finishes with the `RESULT_STORE_UNAVAILABLE` reason,
which is retryable because nothing was learned about the document.

The MCP path is the same picture with `ocr_submit` in place of the REST endpoint and its own header-only guards in
front; only the source of the bytes differs (a download instead of a multipart body).

---

### Waiting, and what a caller is told

A document that arrives while another is being read waits, and is never failed for waiting. It is told how many pages
are ahead of it at submission and on every status read, and the poll hint it carries,
`clamp(pages_remaining * allowance / 10, 1 s, 30 s)`, shrinks as that work drains. `GET /v1/ocr/jobs` shows the whole
queue in submission order, with the running document first. The worst case is the queue's own page bound multiplied
by the per-page allowance, which is why the bound is expressed in pages: it converts directly into a time.

Cancelling a waiting document removes it from the queue. Cancelling a running one goes through the same pool
replacement path reclamation uses, with `cancel` as its third trigger, and kills the worker rather than draining it,
because one work item is a whole document and draining it is exactly what a cancel is asking not to happen. The
replacement runs as a background task, so the cancel answers as soon as the record reads `cancelled` rather than after
a new worker has warmed up, and `/ready` reports `not-ready` from that answer until the replacement finishes (see the
2026-09-25 amendment to [ADR-004](../decisions/ADR-004-liveness-readiness-split.md)). The runner starts each turn by
waiting for any pending replacement, so when the cancelled document finishes on its own before the kill lands, the
next document stays queued and is dispatched to the new, warm worker rather than to the one being killed. A document
the runner has taken but not yet dispatched, because it is still reading the submitted bytes, is simply left
cancelled: `JobStore.start` refuses to move a record that no longer reads `waiting`, so the document is never read
and no worker is replaced for it.

---

### Request budget, deadline stop, and worker reclamation

```mermaid
sequenceDiagram
    participant Client
    participant Gate as dispatch_ocr_request (API process)
    participant Pool as OCR worker process
    participant NewPool as Replacement worker process

    Client->>Gate: runner picks the document up, reading budget = pages * page allowance of the engine
    Gate->>Pool: dispatch with worker_budget = remaining - OCR_DISPATCH_MARGIN_SECONDS
    loop each page, via predict_iter()
        Pool->>Pool: check own deadline (time.monotonic() computed from the duration it was given)
        alt budget exhausted
            Pool-->>Gate: raises before the next page starts
        else budget remains
            Pool->>Pool: infer this page
        end
    end
    Gate->>Gate: OCR_FAILED, no partial result returned

    Note over Gate,Pool: If the worker does not return within one page allowance plus the dispatch margin<br/>past its own expired budget, or the pool is found broken:
    Gate->>NewPool: rebuild (discard old pool, spawn + warm new one)
    Gate->>Gate: /ready reports not-ready for the rebuild's duration
    NewPool-->>Gate: warmed, ready to serve
    Gate->>Client: next queued request served by NewPool - the killed request is never retried
```

A worker can only be asked to stop between pages, so a worker that overruns badly inside a single page keeps
computing until that page finishes - the reclamation grace bounds the total exposure to roughly one page's worth of
extra time, not the unbounded runaway this mechanism replaces. That "roughly one page" bound is exact at
`OCR_WORKER_COUNT=1`, where the rebuild step (`Gate->>NewPool: rebuild` above) has only the one stuck worker's own
work item to wait for. At more than one worker, the rebuild tears down and rebuilds the whole pool at once, so its
own duration is bounded by whichever of the *other*, otherwise healthy, in-flight jobs takes longest to finish - the
gate's rebuild step runs off the event loop so that wait no longer blocks every other request while it happens, but
it does not shorten it. See "the overrun signal at more than one worker" in
[ADR-004](../decisions/ADR-004-liveness-readiness-split.md) for the fix and its regression tests.

See the `ocr-request-deadlines`, `ocr-service-readiness`, `ocr-input-limits`, and `ocr-memory-bounds` capability specs
under `openspec/changes/stop-ocr-getting-stuck-on-large-jobs/specs/` for the full requirement set, and the
`ocr-job-lifecycle`, `ocr-job-admission` and `ocr-job-retention` specs under
`openspec/changes/read-long-documents/specs/` for the job surface that supersedes two of its requirements.

---

### MCP happy path via the S3-compatible object store

```mermaid
sequenceDiagram
    participant Agent as ascend-ai-agent
    participant MCP as ocr_submit tool
    participant Guard as SSRF guard
    participant ObjectStore as Object store :9070 (host.docker.internal)
    participant Pool as OCR worker process
    participant OcrSvc as OcrService

    Agent->>MCP: tools/call ocr_submit(file_uri="http://host.docker.internal:9070/e2e-fixtures/img.png", lang="en")
    MCP->>Guard: _validate_host("host.docker.internal")
    Guard->>Guard: "host.docker.internal" in MCP_ALLOWED_HOSTS → allow
    MCP->>ObjectStore: GET http://host.docker.internal:9070/e2e-fixtures/img.png (allow_redirects=False)
    ObjectStore-->>MCP: 200 image bytes (streamed, size checked)
    MCP->>MCP: JobService.submit - byte cap, pixel ceiling, page ceiling (header only)
    MCP-->>Agent: {"jsonrpc":"2.0","result":{"content":[{"type":"text","text":"{job_id, state:\"waiting\", ...}"}]}}
    Note over Agent,Pool: The document is read later, by the runner, exactly as on the REST path.
    Agent->>MCP: tools/call ocr_job_status(job_id) until a terminal state
    Pool->>OcrSvc: _get_engine("en") - cache hit (warm)
    OcrSvc->>OcrSvc: predict_iter() page by page, deadline checked between pages
```

The `host.docker.internal` hostname resolves to a private address inside the docker-compose network. Without
`MCP_ALLOWED_HOSTS=host.docker.internal`, the SSRF guard would reject it. See
[ADR-001](../decisions/ADR-001-mcp-file-transport-uri-only.md).

---

### Error catalog mapping

| Exception raised | HTTP status (REST) | MCP JSON-RPC | Code string |
| :--- | :--- | :--- | :--- |
| `OcrProcessingError` | 422 | tool error frame | `OCR_FAILED` |
| `FileSizeExceededError` | 400 | tool error frame | `FILE_TOO_LARGE` |
| `UnsupportedFileTypeError` | 400 | tool error frame | `UNSUPPORTED_FILE_TYPE` |
| `UnsafeUriError` | 400 | tool error frame | `UNSAFE_URI` |
| `DownloadFailedError` | 502 | tool error frame | `DOWNLOAD_FAILED` |
| `QueueFullError` | 503 + `Retry-After` | tool error frame | `QUEUE_FULL` |
| `JobNotFoundError` | 404 | tool error frame | `JOB_NOT_FOUND` |
| `UnsupportedLanguageError` | 400 | tool error frame, raised before the URI is fetched | `UNSUPPORTED_LANGUAGE` |
| `Exception` (unhandled) | 500 | tool error frame | `INTERNAL_ERROR` |

All handlers are registered in `register_exception_handlers` in `src/api/exception_handlers.py`. The `detail` field
carries a generic phrase; the original exception message is logged at WARNING or ERROR but never returned to the
client. The one exception is `UNSUPPORTED_LANGUAGE`, whose detail lists the supported languages from configuration
and never echoes what the caller sent.

A failure of the **reading** is not in this table, because it is not a failed request: it is a successful read of a
record whose `state` is `failed`, carrying `error_code`, `error_reason` and `retryable`. The codes a record can carry
are `OCR_FAILED`, `INTERNAL_ERROR`, and the three record-level reasons `SERVICE_RESTARTED`,
`RESULT_STORE_UNAVAILABLE` and `LIFETIME_EXCEEDED`.
