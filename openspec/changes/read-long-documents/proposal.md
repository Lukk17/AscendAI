## Why

Ask the service to read a twenty five page document today and it refuses before any work starts, with
`FILE_TOO_LARGE` and a 400. The accepted limit is two pages. Where that two comes from matters, because it is not
where people assume.

It is not memory. The fitted model in
[stop-ocr-getting-stuck-on-large-jobs](../stop-ocr-getting-stuck-on-large-jobs/design.md) prices a page at 11.5 MiB
of retained result and sets peak by the largest single page rather than by the length of the document. Page count
does not become the binding term until roughly ninety pages with no detector bound, and about a hundred and fifty
for A4 under the 1536 bound this module now deploys. Twenty five pages of A4 cost 276 MiB more than one page of A4.

It falls out of two deadlines. `OCR_MAX_PAGES` is a derived property, `floor(OCR_REQUEST_TIMEOUT /
OCR_PAGE_TIMEOUT_SECONDS)` in [config.py](../../../PaddleOCR/src/config/config.py). The deployed values are 300 s
(`docker-compose.yaml`) and 120 s, so the answer is two, and `enforce_page_limit` in
[limits.py](../../../PaddleOCR/src/api/limits.py) refuses anything above it. The refusal is correct given those
numbers: a document that provably cannot finish inside the service's own ceiling should not be started.

That ceiling was introduced for a good reason and this change keeps it. A twenty page document once failed at
300 seconds while the worker carried on for a further thirty minutes computing an answer nobody would receive, and
the refusal is an improvement on that. The task here is to serve long documents, not to delete the protection.

The reason a larger ceiling is not the answer is that nobody can wait for it. A page costs about 90 s measured,
consistent with the 47 to 100 s band recorded beside `OCR_PAGE_TIMEOUT_SECONDS` and with the 105 s per page the
twenty page incident implies, so twenty five pages is about 37 minutes of work. The platform's own callers give up
long before that: `app.ingestion.read-timeout` is 300000 ms in
[application.yaml](../../../AscendAgent/src/main/resources/application.yaml), which is the client the chat
attachment path uses through `PaddleOcrClient`, and `spring.ai.mcp.client.request-timeout` is 300 s for every MCP
server the agent talks to. Raise the ceiling to 4800 s and the service spends 75 minutes inferring pages for a
caller who disconnected at 300 s, which is the incident the previous change exists to end, arriving through the
front door.

So the document has to be accepted without the caller holding a connection open for it. Submit it, get a job back,
poll it, collect the result.

## What Changes

A job for long documents, alongside the synchronous endpoint that already works:

- New REST resource `POST /v1/ocr/jobs`, `GET /v1/ocr/jobs/{job_id}` and `DELETE /v1/ocr/jobs/{job_id}`. Submitting
  answers 202 with a job id and a `Location` header rather than holding the connection. The status resource carries
  the job's state, its progress in pages, and the completed result when there is one.
- The MCP surface gets the same three operations as tools, `ocr_submit`, `ocr_job_status` and `ocr_cancel_job`, with
  identical states, identical error codes and identical bounds. `ocr_process` is unchanged.
- `POST /v1/ocr` and the `ocr_process` tool keep their contract exactly. A caller that works today is untouched, and
  this change adds no request parameter to either.

A page ceiling that still exists, derived from memory instead of from a deadline:

- Jobs get their own page ceiling, `OCR_JOB_MAX_PAGES`, defaulting to 40. It comes from the fitted memory model at a
  stated resident budget rather than from a timeout, because a job's caller is not holding a connection and time is
  no longer the binding constraint. The derivation is in [design.md](design.md).
- The job's own time ceiling is derived rather than configured, `OCR_JOB_MAX_PAGES x OCR_PAGE_TIMEOUT_SECONDS`,
  which is 4800 s at the defaults. That keeps the existing rule that a document whose page count multiplied by the
  per-page allowance exceeds the applicable ceiling is refused up front, satisfied identically on both paths.
- Every deadline mechanism the previous change built is reused unchanged: the per-page cooperative deadline inside
  the worker, the reclamation grace, the pool rebuild and the admission gate. A job is not a new way to run
  inference, it is a new way to wait for it.

The two budget values the previous change left to the owner, now set:

- `OCR_PAGE_TIMEOUT_SECONDS` stays 120 s, and the reason is written down rather than left provisional.
- `OCR_REQUEST_TIMEOUT` moves from 300 s to 240 s, which changes no behaviour at all and makes the arithmetic
  honest. At a 120 s per-page allowance a two page document is already capped at 240 s by the per-page term, so the
  last 60 s of the deployed ceiling is unreachable by any document the service accepts. 240 is exactly two
  allowances, so the ceiling and the derived page limit agree, and it stays clear of the 300 s at which the
  platform's callers give up. The synchronous page limit stays 2, by design, because the job path now carries
  everything above it.

What comes with the job, which is the part that is easy to leave half built:

- Job state lives on disk in a jobs directory, one record per job, so a completed result survives a restart of the
  API process. A job that was queued or running when the service restarted is failed with a distinct, retryable
  reason instead of hanging forever.
- A completed result is kept for a bounded retention window and then deleted by the service. A caller can delete it
  earlier, which matters because a result is the document's own text sitting on disk.
- The queue is bounded twice, in pages and in documents, and a submission beyond either bound is refused with a new
  `QUEUE_FULL` code and a 503 rather than being accepted into an unbounded wait. A queue bounded in pages is what
  turns "come back later" into a promise with a number attached.
- Cancelling actually stops the work. A queued job is removed from the queue. A running job's worker is replaced by
  the path reclamation already uses, so the compute stops within the replacement rather than at the end of the
  current page.
- Jobs and synchronous requests share the one worker, first in first out, and the consequence is stated plainly
  rather than hidden: while a long job runs, a synchronous request waits behind it and fails on its own budget.

Two new error codes, `QUEUE_FULL` (503) and `JOB_NOT_FOUND` (404), plus a `SERVICE_RESTARTED` failure reason that
appears only inside a job record. Adding codes is non-breaking under
[ADR-003](../../../PaddleOCR/docs/architecture/decisions/ADR-003-versioning-strategy.md), and no existing code
changes meaning. `ReadinessResponse` gains `jobs_queued` and `jobs_running`, additive, with `/ready` keeping its 200
in both states as [ADR-004](../../../PaddleOCR/docs/architecture/decisions/ADR-004-liveness-readiness-split.md)
specifies.

Nothing here is BREAKING.

## Capabilities

### New Capabilities

- `ocr-long-document-jobs`: submitting a document as a job, the states a caller can observe, what each state returns
  on each surface, progress, cancellation, and the requirement that both surfaces behave identically.
- `ocr-job-admission`: what the service accepts as a job, the page ceiling it derives from memory rather than from a
  deadline, the two queue bounds and the refusal beyond them, and how jobs and synchronous requests share one
  worker.
- `ocr-job-retention`: how long a result lives, who deletes it, what a restart does to jobs in flight, and the
  storage the whole arrangement is allowed to hold.

### Modified Capabilities

None. No capability under `openspec/specs/` covers the PaddleOCR module yet: the four this module needs
(`ocr-request-deadlines`, `ocr-service-readiness`, `ocr-input-limits`, `ocr-memory-bounds`) are still deltas inside
`stop-ocr-getting-stuck-on-large-jobs` and land in `openspec/specs/` when that change is archived. This change adds
to them rather than altering them, and [design.md](design.md) states, requirement by requirement, why each of the
four still reads true once jobs exist.

## Impact

Code, all under `PaddleOCR/`:

- `src/service/job_store.py`: new. Job records on disk, atomic write and read, the id, the state transitions, the
  retention sweep and the startup recovery pass.
- `src/service/job_runner.py`: new. The single consumer that takes the next job, dispatches it through the existing
  `dispatch_ocr_request`, writes the outcome, and sweeps on its idle tick.
- `src/service/ocr_service.py`: the worker records per-page progress for the job it is serving, the scratch sweep
  horizon moves from the synchronous ceiling to the longest job the service accepts, and the pool replacement path
  gains cancellation as a third trigger beside reclamation and a broken pool.
- `src/api/rest/rest_endpoints.py` and `src/api/mcp/mcp_server.py`: three new operations each, sharing one service
  layer so the two surfaces cannot drift.
- `src/api/limits.py`: `enforce_page_limit` takes the applicable ceiling instead of reading the synchronous one, so
  the same guard serves both paths.
- `src/api/exception_handlers.py`: `QUEUE_FULL` and `JOB_NOT_FOUND` with their statuses and handlers.
- `src/model/ocr_models.py`: the job record and the job response models, plus `jobs_queued` and `jobs_running` on
  `ReadinessResponse`.
- `src/main.py`: the job runner starts and stops with the lifespan, and startup recovery runs before it does.
- `src/config/config.py`: `OCR_JOB_MAX_PAGES`, `OCR_JOBS_DIR`, `OCR_JOB_RETENTION_SECONDS`, `OCR_JOB_MAX_RETAINED`,
  `OCR_JOB_QUEUE_MAX_PAGES`, `OCR_JOB_QUEUE_MAX_DOCUMENTS`, and the derived job time ceiling. Every default is
  derived in [design.md](design.md).
- `src/observability/metrics.py`: job outcomes, queue depth in jobs and in pages, queue wait, job duration and
  retained record count.

Tests, all under `PaddleOCR/tests/`. The gate is `--cov-fail-under=100` with `--cov-branch`, so every branch added
needs a test. Detail in [tasks.md](tasks.md).

Configuration: `docker-compose.yaml` sets `OCR_REQUEST_TIMEOUT=240` in place of 300 and adds the job settings that
differ from their defaults. A jobs directory that must outlive a container recreate needs a volume, which the
deployment page documents rather than the compose file assuming.

API: additive on both surfaces. No existing response field, error code or request parameter changes.

Dependencies: none added. The job store is files and JSON, deliberately, so this module keeps its property of having
no external service dependency of its own.

Docs: the environment table in `PaddleOCR/AGENTS.md`, `PaddleOCR/README.md`, `PaddleOCR/docs/CONFIGURATION.md`, the
arc42 pages under `PaddleOCR/docs/architecture/arc42/`, an amendment to ADR-002 for the two new codes, an amendment
to ADR-004 for the two new readiness fields, and a new ADR recording why long documents became jobs rather than a
larger timeout. `PaddleOCR/e2e/README.md` says the service holds no persisted state, which stops being true, so it
changes in the same commit as the store that makes it false.

Test surfaces beyond the unit suite: three Bruno requests under `docs/api/request/AscendAI/paddle-ocr/`, and one new
capability spec plus its run template under `PaddleOCR/e2e/testing/`.

Out of scope, named rather than silently left: pointing the AscendAgent at the job API. Its `DocumentRouter` already
splits a PDF page by page and dispatches four at a time, so it never sends a long document as one request, and
[design.md](design.md) records what that parallelism does against a single worker and why changing it is the
agent's decision rather than this module's.

## Relevant Skills

Load before implementing:

- `/python-patterns`, `/python-testing`, `/tdd-workflow`
- `/api-design` for the job resource, its status codes and its polling contract
- `/docker-patterns`, `/deployment-patterns` for the jobs directory and its volume
- `/security-review` for the job id, the path handling in the job store, and results holding document text on disk
- `/coding-standards`, `/code-reviewer`
- `/architecture-decision-records` for the new ADR and the two amendments
- `/e2e-runbooks` for the long document capability test
