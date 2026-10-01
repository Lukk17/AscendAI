## Why

Ask the service to read a twenty five page document today and it refuses before any work starts, with
`FILE_TOO_LARGE` and a 400. The accepted limit is two pages. Where that two comes from matters, because it is not
where people assume.

It is not memory, and since [upgrade-ocr-to-ppocrv6](../upgrade-ocr-to-ppocrv6/proposal.md) it is not even close to
memory. That change is implemented and gate-green and not yet archived, it moved the library to PaddleOCR 3.7.0 and
named `PP-OCRv6_small_det` and `PP-OCRv6_small_rec` as the pair almost every language now runs, and the owner's
measurements against that pair are what this change is built on. One A4 page costs about 440 MB of a 12 GB
container, flat, whether it carries six lines or fifty. (Superseded 2026-09-25: measured as a Linux container's cgroup `memory.peak`, one A4 page at 300 dpi peaks at 1016 MiB, see `fix-ocr-page-resolution` design.md Decision 10.) **This change depends on that one** and cannot be
implemented against the model it replaced.

It falls out of two deadlines. `OCR_MAX_PAGES` is a derived property, `floor(OCR_REQUEST_TIMEOUT /
OCR_PAGE_TIMEOUT_SECONDS)` in [config.py](../../../apps/ascend-ocr/src/config/config.py). The deployed values are
300 s and 150 s, both set in `compose.yaml`, so the answer is two, and `enforce_page_limit` in
[limits.py](../../../apps/ascend-ocr/src/api/limits.py) refuses anything above it. That was defensible when a page
cost 51 to 94 seconds. A page now costs 4.1 s at six lines and 10.0 s at fifty, so a limit of two pages derived from
a 150 s per-page allowance is refusing a four minute job on the grounds that it might take an hour.

That ceiling was introduced for a good reason and this change keeps the protection behind it. A twenty page document
once failed at 300 seconds while the worker carried on for a further thirty minutes computing an answer nobody would
receive. The task here is to serve long documents, not to delete the protection.

Raising the ceiling and keeping a held connection is the obvious cheap answer, and the speedup made it less
ridiculous than it was. Twenty five clean pages now fit inside the agent's own 300 s read timeout. It still loses,
for three reasons the speedup does not touch. The ceiling this change sets is a hundred pages, which is about
seventeen minutes and far outside every client timeout in the platform. The queue, not the reading, is now the
dominant term: one worker serving first in first out means a held connection waits for everything ahead of it, and
that wait does not shrink when inference gets faster. And FastAPI still does not notice that a client has gone, so
any held connection can be abandoned while the service keeps inferring pages for nobody, which is the incident the
previous change exists to end.

An earlier version of this change answered that by adding a job path beside the synchronous one and letting a page
count decide which a caller got. The owner overturned it, and the reason generalises the argument above rather than
contradicting it. No document of any length can be answered on a held connection without the service betting that
the caller is still there, and the only thing a page count changes is the odds on that bet. So the connection stops
being part of the contract. Every request answers 202 immediately with an identifier, there is no length at which
the behaviour differs, and the caller asks whether the work is ready.

## What Changes

Four REST operations, and nothing else on the REST surface:

- `POST /v1/ocr/jobs` takes the document and answers 202 with an identifier and a relative `Location` pointing at
  the status resource. It never carries page content.
- `GET /v1/ocr/jobs/{job_id}` answers with the state, the page count, the progress, the hint for when to ask again,
  and, once the work has succeeded, the address of the result.
- `GET /v1/ocr/jobs` lists everything currently queued and running, with the identifier, the state, pages done of
  total, how long each has been waiting or running, and its position in the queue.
- `DELETE /v1/ocr/jobs/{job_id}` stops the work if it is running, deletes its result, and forgets it, in one verb.

Four tools, and nothing else on the MCP surface: `ocr_submit`, `ocr_job_status`, `ocr_list_jobs` and
`ocr_cancel_job`, taking the same arguments as their REST counterparts, returning the same records, raising the same
codes.

**The result goes to object storage.** A successful job writes one Markdown file, `{job_id}.md`, to an
S3-compatible bucket, and the status answer carries the bucket, the key, a presigned GET URL and the metadata that
does not grow with the document. The platform already runs that storage, locally Floci on port 9070, the
ascend-ai-agent already ingests documents from it with the AWS SDK, and this service's SSRF allowlist already names
the host it lives on. The earlier version of this change had the status answer carry the whole result inline, and
[design.md](design.md)'s Decision 10 inverts that decision and records why rather than deleting it.

The synchronous surface is removed, asymmetrically and deliberately:

- `POST /v1/ocr` answers 410 with a new `ENDPOINT_REMOVED` code that names `POST /v1/ocr/jobs` as its replacement,
  for one documented window, so a caller that has not been rewritten gets an answer that tells it what to do.
- The `ocr_process` tool is removed outright. A tool catalogue is discovered on every connection rather than
  hardcoded, so a removed tool is a tool the model stops seeing rather than a call that fails.
- Design Decision 17 states the asymmetry and why each surface gets what it gets.

The settings move with the contract:

- `OCR_REQUEST_TIMEOUT` and the derived `OCR_MAX_PAGES` are deleted. Both bounded a held connection, and no
  connection is held. Their consumers move: the page limit becomes `OCR_JOB_MAX_PAGES`, the effective budget loses
  the second term of its `min`, the scratch sweep horizon becomes the job reading ceiling, and the startup banner
  reports the ceiling instead of the timeout.
- Six job settings arrive: `OCR_JOB_MAX_PAGES`, `OCR_JOBS_DIR`, `OCR_JOB_RETENTION_SECONDS`,
  `OCR_JOB_MAX_RETAINED`, `OCR_JOB_QUEUE_MAX_PAGES` and `OCR_JOB_QUEUE_MAX_DOCUMENTS`.
- Five result store settings arrive: `OCR_RESULT_S3_ENDPOINT`, `OCR_RESULT_S3_PUBLIC_ENDPOINT`,
  `OCR_RESULT_S3_BUCKET`, `OCR_RESULT_S3_ACCESS_KEY` and `OCR_RESULT_S3_SECRET_KEY`. Each mirrors the property the
  agent already uses for the same store.
- Three new quantities are derived rather than configured: the job reading ceiling, the maximum lifetime a record
  may spend in a non-terminal state, and the poll hint. Two existing derivations are repointed rather than added,
  the document's own reading budget and the scratch sweep horizon.
- `OCR_PAGE_TIMEOUT_SECONDS` becomes the service's only configured time input and is settled at 45 s, down from
  120 s in code and 150 s in `compose.yaml`. Every default and every derivation, with the measurement behind it, is
  in [design.md](design.md)'s number table. Superseded on 2026-09-24: one allowance could not cover two engines, so
  [fix-ocr-page-resolution](../fix-ocr-page-resolution/design.md) replaces it with one allowance per engine,
  `OCR_PAGE_ALLOWANCE_HEADROOM` times the worst page measured on that engine's detector, and that change now owns the
  allowance and every duration derived from it.

**Every number in that table was re-derived from the owner's measurements rather than scaled down.** The old table
was built on a fitted memory model whose detection term was `PP-OCRv5_server_det`'s cost, and the measurements
against the pair that replaced it are 439, 439 and 441 MB for six, twenty and fifty lines on one A4 page at 300
dots per inch. (Superseded 2026-09-25: measured as a Linux container's cgroup `memory.peak`, one A4 page at 300 dpi peaks at 1016 MiB, see `fix-ocr-page-resolution` design.md Decision 10.) The predictions the old table rested on were 9,060 MB at 144 dots per inch and 44,847 MB at 300, so
both were wrong by more than an order of magnitude. design.md's "What memory no longer constrains" section lists
what is deleted as void rather than left standing: the fitted model as a whole-model statement, the claim that one
page is most of the container, the ninety page crossover, the three-page-size ceiling table, the ninety percent
resident budget, and the forty page ceiling derived from all of it. One term survives, the roughly 11.5 MiB each
page's retained result costs, and task 1.2 measures it on the new pair.

The container allocation is named and not settled. The service is allocated 12 GB and needs about 1.1. The
recommendation is 3 GB with the arithmetic recorded, and it should be set only after the end-to-end specs have run
against real scanned documents, because every duration here comes from a synthetic page of clean rendered text.
Memory is safe to conclude from that page, because detection dominates and detection does not care about text
density. Time is not, because a real scan may detect many more regions.

What comes with a job, which is the part that is easy to leave half built:

- Job state lives on disk in a jobs directory, one record per job, so a completed job survives a restart of the API
  process. The result itself lives in the bucket and survives a container recreate as well. A record that was
  waiting or running when the service restarted is failed with a distinct, retryable reason instead of hanging
  forever.
- A completed result is kept for a bounded retention window and then deleted by the service, object first and record
  second. A caller can delete it earlier, which matters because a result is the document's own text.
- The queue is bounded twice, in pages and in documents, and a submission beyond either bound is refused with
  `QUEUE_FULL` and a 503 rather than being accepted into an unbounded wait. A queue bounded in pages is what turns
  "come back later" into a promise with a number attached.
- Cancelling actually stops the work. A queued job is removed from the queue. A running job's worker is replaced by
  the path reclamation already uses, so the compute stops within the replacement rather than at the end of the
  current page.
- One queue, strict submission order, no priority classes, and no way to reach the worker except through it.

The ascend-ai-agent migrates in the same change. `AscendOcrClient` keeps its signature and its return type and
becomes submit, poll, fetch, delete, so `DocumentRouter` and the ingestion pipeline above it are untouched. Its
`parseResponse` and the two helpers under it are deleted rather than adapted, because the Markdown already is the
flattened text they used to build. The detail is in [design.md](design.md)'s Decision 12, which also corrects an
arithmetic the earlier version of this change used and the model upgrade has since falsified.

Error surface: `QUEUE_FULL` (503), `JOB_NOT_FOUND` (404) and `ENDPOINT_REMOVED` (410) join the catalogue, plus three
record-level reasons that are never HTTP statuses, `SERVICE_RESTARTED`, `LIFETIME_EXCEEDED` and
`RESULT_STORE_UNAVAILABLE`. `ReadinessResponse` gains `jobs_queued` and `jobs_running`, additively, with `/ready`
keeping its 200 in both states as
[ADR-004](../../../apps/ascend-ocr/docs/architecture/decisions/ADR-004-liveness-readiness-split.md) specifies.

This change is BREAKING on both surfaces, and it says so rather than hiding it. Under
[ADR-003](../../../apps/ascend-ocr/docs/architecture/decisions/ADR-003-versioning-strategy.md)'s own table, removing
an endpoint, removing a tool and changing what a submission's answer means are each breaking on their own. The owner
accepted that knowingly, and the cost lands on every caller: the agent's `AscendOcrClient`, the fifteen Bruno
requests that drive `POST /v1/ocr` or `ocr_process` under `docs/api/request/AscendAI/`, and eleven of the twelve e2e
specs under `apps/ascend-ocr/e2e/testing/`. A deprecation window of the kind ADR-003 imagines buys less here than
usual, because what changed is what a submission's answer means, so a caller that keeps calling the old name still
has to be rewritten.

## Capabilities

### New Capabilities

- `ocr-job-lifecycle`: submitting a document, the states a caller can observe, what each state returns on each
  surface, progress, the hint for when to ask again, the result as a Markdown file in object storage and the
  address the status answer carries, listing work in flight, cancellation, the removal of the synchronous request,
  and the requirement that both surfaces behave identically.
- `ocr-job-admission`: what the service accepts, the page ceiling and what now sets it, the two queue bounds and
  the refusal beyond them, and the rule that nothing reaches the worker except through the queue.
- `ocr-job-retention`: how long a result lives in the bucket, who deletes it, what a restart does to work in flight
  and to a finished result, the maximum lifetime that stops a wedged record being polled forever, and the storage
  the whole arrangement is allowed to hold.

### Modified Capabilities

None under `openspec/specs/`. No capability there covers the ascend-ocr module yet: the four this module needs
(`ocr-request-deadlines`, `ocr-service-readiness`, `ocr-input-limits`, `ocr-memory-bounds`) are still deltas inside
`stop-ocr-getting-stuck-on-large-jobs`, which is implemented but not archived, and a fifth
(`ocr-model-selection`) is a delta inside `upgrade-ocr-to-ppocrv6`, which is in the same state. Two of the four are
superseded by this change and eight requirements still hold, requirement by requirement, in [design.md](design.md).
`ocr-model-selection` is untouched here. Task 12.1 owns the reconciliation, and whichever change archives first
carries it.

## Impact

Code, under `apps/ascend-ocr/`:

- `src/service/job_store.py`: new. Job records on disk, atomic write and read, the identifier, the state
  transitions, the retention sweep, the maximum-lifetime sweep and the startup recovery pass.
- `src/service/job_runner.py`: new. The single consumer that takes the next job, dispatches it through the existing
  `dispatch_ocr_request`, renders and uploads the result, writes the outcome, and sweeps on its idle tick.
- `src/service/result_store.py`: new. The S3-compatible client, the Markdown rendering, the upload with bounded
  retries, the presigned URL, the delete, and the startup head-or-create of the bucket.
- `src/service/job_service.py`: new. The one service layer beneath both surfaces, holding the four operations, every
  input guard at submission, the poll hint and the result address, plus the composition root that wires the store,
  the runner and the result store together.
- `src/service/ocr_service.py`: the worker records per-page progress for the job it is serving, the scratch sweep
  horizon moves from the deleted synchronous ceiling to the longest document the service accepts, and the pool
  replacement path gains cancellation as a third trigger beside reclamation and a broken pool.
- `src/api/rest/rest_endpoints.py` and `src/api/mcp/mcp_server.py`: four operations each, sharing one service
  layer so the two surfaces cannot drift, and the removal of `POST /v1/ocr` and of `ocr_process`.
- `src/api/limits.py`: `enforce_page_limit` reads `OCR_JOB_MAX_PAGES`, the only page ceiling left.
- `src/api/exception_handlers.py`: `QUEUE_FULL`, `JOB_NOT_FOUND` and `ENDPOINT_REMOVED` with their statuses and
  handlers.
- `src/model/ocr_models.py`: the job record, the job response models, the result reference, the list entry, and
  `jobs_queued` and `jobs_running` on `ReadinessResponse`.
- `src/main.py`: the job runner starts and stops with the lifespan, and startup recovery and the bucket check run
  before it does.
- `src/config/config.py`: the eleven new settings and the two settings-level derived quantities, the settled
  per-page allowance, and the deletion of `OCR_REQUEST_TIMEOUT`, of the derived `OCR_MAX_PAGES` and of the
  validator that compared the two deleted values.
- `src/config/startup_banner.py`: it prints both deleted values today, so it reports the allowance, the page
  ceiling, the derived reading ceiling and the result store instead.
- `src/observability/metrics.py`: job outcomes, queue depth in jobs and in pages, queue wait, job duration,
  retained record count and result upload outcomes.

Code and configuration, under `apps/ascend-agent/`:

- `src/main/java/com/lukk/ascend/ai/agent/service/ingestion/client/AscendOcrClient.java`: submit, poll, fetch,
  delete, behind the unchanged `process(byte[], String, String)` signature, reusing the existing `S3Client` bean for
  the fetch and deleting `parseResponse` and its two helpers.
- `src/main/resources/application.yaml`: `app.ascend-ocr.api-path` moves from `/v1/ocr` to `/v1/ocr/jobs`, and the
  polling and submission-retry properties arrive beside it. `application-docker.yaml` needs no change, because it
  overrides `base-url` only.
- Tests: `AscendOcrClientTest`, `AscendOcrClientResponseParsingTest`, `AscendOcrClientLiveContractTest`,
  `DocumentRouterTest`, `DocumentRouterFileTypeRoutingTest` and `DocumentRouterPdfExceptionTest`.

Tests under `apps/ascend-ocr/tests/`. The gate is `--cov-fail-under=100` with `--cov-branch`, so every branch added
needs a test. Detail in [tasks.md](tasks.md).

Configuration: `compose.yaml` drops `OCR_REQUEST_TIMEOUT` and the `OCR_PAGE_TIMEOUT_SECONDS` override, and adds the
result store endpoint, bucket and credentials. A jobs directory that must outlive a container recreate needs a
volume, which the deployment page documents rather than the compose file assuming. Lowering the 12 G memory limit
toward the recommended 3 G is a separate, later edit gated on the end-to-end run.

Dependencies: one added, `boto3` for the S3-compatible client, plus `boto3-stubs[s3]` in the dev extra so mypy has
types rather than an ignore. The job store itself is still files and JSON. The earlier version of this change said
no dependency is added and that this module keeps its property of having no external service dependency of its own,
and the object storage decision reverses both.

Docs: the environment table in `apps/ascend-ocr/AGENTS.md`, `apps/ascend-ocr/README.md` and
`apps/ascend-ocr/docs/CONFIGURATION.md`, the arc42 pages under `apps/ascend-ocr/docs/architecture/arc42/`, an
amendment to ADR-002 for the three new codes and the three record-level reasons, an amendment to ADR-003 recording a
breaking change on both surfaces and what each did in place of a version bump, an amendment to ADR-004 for the two
new readiness fields, a new ADR recording why every request became a job, and a second new ADR recording why the
result lives in object storage and what external dependency that buys and costs.
`apps/ascend-ocr/e2e/README.md` says the service holds no persisted state, which stops being true twice over, so it
changes in the same commit as the store and the bucket that make it false.

Test surfaces beyond the unit suite: the fifteen Bruno requests that drive the removed surface, under
`docs/api/request/AscendAI/ocr/`, `docs/api/request/AscendAI/ocr/testing/`, `docs/api/request/AscendAI/mcp/ocr/`
and `docs/api/request/AscendAI/3rd-party/ocr/`, and eleven of the twelve specs plus their run templates under
`apps/ascend-ocr/e2e/testing/`, with three new specs: one for a document longer than a single-request ceiling ever
allowed, one for the list operation, and one for the timings and peaks on real scanned documents that the number
table is waiting on.

Spec sequencing: `stop-ocr-getting-stuck-on-large-jobs` is implemented but not archived, and two of its
requirements are superseded here. The two changes cannot be archived independently without leaving
`openspec/specs/` self-contradictory, so task 12.1 reconciles them and whichever archives first carries the
reconciliation. `upgrade-ocr-to-ppocrv6` is a prerequisite rather than a conflict: its `ocr-model-selection`
capability is untouched, and this change's numbers are only true against the model pair it installed.

## Relevant Skills

Load before implementing:

- `/python-patterns`, `/tdd-workflow`
- `/backend-patterns` for the queue, the bounded retries on the upload, the poll contract and graceful shutdown
- `/springboot-patterns`, `/java-coding-standards` for the agent client's polling loop and its tests
- `/api-design` for the job resource, its status codes, its polling contract, the list operation and the removal of
  an endpoint
- `/docker-patterns`, `/deployment-patterns` for the jobs directory, its volume, the bucket and its lifecycle rule
- `/security-review` for the job id, the path and key handling, the bucket's access policy, and the disclosure the
  list operation makes on a service with no authentication
- `/build-dependency-management` for the boto3 addition and its stubs
- `/observability-and-logging` for the job metrics, the readiness fields and the startup banner
- `/coding-standards`, `/code-reviewer`
- `/architecture-decision-records` for the two new ADRs and the three amendments
- `/e2e-runbooks` for rewriting the suite onto the job surface, the long document spec and the real-scan measurement
  spec
