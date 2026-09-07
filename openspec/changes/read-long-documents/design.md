## Context

See [proposal.md](proposal.md) for the motivation. This change builds directly on
[stop-ocr-getting-stuck-on-large-jobs](../stop-ocr-getting-stuck-on-large-jobs/design.md), whose deadline,
reclamation, admission gate and memory model are reused rather than replaced, so the constraints below were read
from the code and the configuration as they stand after that change, not assumed.

- The page limit is derived, not configured. `Settings.OCR_MAX_PAGES` is
  `floor(OCR_REQUEST_TIMEOUT / OCR_PAGE_TIMEOUT_SECONDS)` in
  [config.py](../../../ascend-ocr/src/config/config.py). Deployed values are `OCR_REQUEST_TIMEOUT=300` in
  `docker-compose.yaml` and `OCR_PAGE_TIMEOUT_SECONDS=120` by default, so the limit is two, and
  `enforce_page_limit` in [limits.py](../../../ascend-ocr/src/api/limits.py) refuses anything above it with
  `FILE_TOO_LARGE`.
- One worker, and it is a memory constraint. `OCR_WORKER_COUNT` governs both the `ProcessPoolExecutor` size and the
  admission gate's permit count in [ocr_service.py](../../../ascend-ocr/src/service/ocr_service.py). One A4 page's
  peak is already most of the container's 12,288 MiB.
- The stop is cooperative and already page-granular. `_predict_pages` consumes `predict_iter()` and checks a
  deadline before pulling each page. The parent passes a remaining duration, never a wall clock time.
- The reclamation and rebuild path exists. `_rebuild_pool(observed_generation, reason)` replaces the pool, is
  guarded by a lock and a generation counter, counts consecutive failures, and is already reached from two triggers.
- Both surfaces already share one dispatch function. `dispatch_ocr_request(...)` in `ocr_service.py` is called from
  [rest_endpoints.py](../../../ascend-ocr/src/api/rest/rest_endpoints.py) and
  [mcp_server.py](../../../ascend-ocr/src/api/mcp/mcp_server.py), and both compute
  `min(pages x OCR_PAGE_TIMEOUT_SECONDS, OCR_REQUEST_TIMEOUT)` identically.
- The service holds no persisted state today. `ascend-ocr/e2e/README.md` says so in as many words, there is no
  database, no cache and no volume in `docker-compose.yaml`, and the only cross-process state is the Prometheus
  multiprocess directory that `is_engine_warm` reads.
- The service has no authentication of its own. `SecurityHeadersMiddleware`, `CorrelationIdMiddleware` and the
  slowapi rate limiter are the whole of the request-level protection, and `RATE_LIMIT_DEFAULT` is 60 per minute with
  `RATE_LIMIT_OCR` at 20 per minute.
- The error catalogue is fixed and mapped in one place. `exception_handlers.py` maps `OCR_FAILED` to 422,
  `FILE_TOO_LARGE` and `UNSUPPORTED_FILE_TYPE` and `UNSAFE_URI` to 400, `DOWNLOAD_FAILED` to 502 and
  `INTERNAL_ERROR` to 500. Adding a code is non-breaking under ADR-003, renaming or restatusing one is not.
- The scratch sweep horizon is the synchronous ceiling. `sweep_scratch_dir` removes anything older than
  `OCR_REQUEST_TIMEOUT + OCR_DISPATCH_MARGIN_SECONDS`.
- The in-platform callers time out at 300 s. `app.ingestion.read-timeout` is 300000 ms in the agent's
  `application.yaml`, used by the `ingestionRestClient` that `AscendOcrClient` holds, and
  `spring.ai.mcp.client.request-timeout` is 300 s. ascend-ocr's MCP server is not in the agent's connection list
  today, so the agent reaches this module over REST only.
- The agent never sends a long document as one request. `DocumentRouter.routePdfPerPage` slices a PDF into
  single-page PDFs and dispatches them with `pdf-parallel-pages: 4`. Images go whole, and an image is one page.

## Goals / Non-Goals

Goals:

- A twenty five page document is read, and the caller is never asked to hold a connection for the length of the
  reading.
- The protection the previous change installed survives intact. Nothing here lets the service compute pages for a
  caller who has gone, and nothing here removes a page ceiling.
- Every number is derived, and the ones that are a product trade rather than a derivation say so.
- One mechanism for reading a document, reached two ways. A job is a different way to wait, not a different way to
  infer.
- Everything a long-running job drags in is settled here rather than discovered later: where state lives, what a
  restart does to it, how long a result survives, what the queue promises, and whether cancel actually cancels.

Non-Goals:

- Making OCR faster, or reading pages in parallel. The worker count stays one and the reason stays memory.
- Changing the synchronous request in any way a caller can observe.
- Pointing the AscendAgent at the job API, or changing its per-page fan-out. Both are the agent's decisions and are
  discussed under Decision 12 only so the consequence is on the record.
- Authentication. Possession of an unguessable identifier is the whole access control, which is the same posture the
  service already has for its OCR endpoints, and raising it is a platform-wide decision rather than this change's.
- Persisting results across a container recreate by default. Decision 4 states what survives what, and a volume is
  documented rather than assumed.

## The numbers, and where each comes from

| Value | Setting | Default | Where it comes from | Kind |
|---|---|---|---|---|
| Per-page allowance | `OCR_PAGE_TIMEOUT_SECONDS` | 120 s, unchanged | The measured band is 47 to 100 s per page on the 4.0 CPU allocation, the owner's working figure is about 90 s, and the twenty page incident implies at least 105 s per page. 120 s is the first round value above the top of that band, and the headroom is deliberate: the previous change's own last-page trade means a budget sized exactly to the observed cost discards completed work. | Derived |
| Synchronous ceiling | `OCR_REQUEST_TIMEOUT` | 240 s, from 300 s | Two per-page allowances, so the ceiling and the derived two-page limit agree exactly. At 120 s per page the deployed 300 s was unreachable: a two page document is already capped at 240 s by the per-page term. It also stays clear of the 300 s at which both in-platform callers give up, so the service fails first with its own error instead of being abandoned mid-request. | Derived |
| Synchronous page limit | derived | 2, unchanged | `floor(240 / 120)`, the same property as today. | Derived |
| Job page ceiling | `OCR_JOB_MAX_PAGES` | 40 | The fitted memory model below, taken as the smaller of A4 at a 90 percent resident budget (41 pages) and US Letter at the full container limit (82 pages), rounded down. | Derived |
| Job reading ceiling | derived | 4800 s | `OCR_JOB_MAX_PAGES x OCR_PAGE_TIMEOUT_SECONDS`. Not configurable, for the same reason `OCR_MAX_PAGES` is not: two numbers that must agree should be one number and a formula. | Derived |
| Queue page bound | `OCR_JOB_QUEUE_MAX_PAGES` | 80 | Two documents at the page ceiling may wait while one is read. The bound is what makes the wait a number: the longest a newly accepted submission waits is 80 x 120 s, which is 2 h 40 min at the allowance and about 2 h at the measured 90 s per page. | Derived from a stated promise |
| Queue document bound | `OCR_JOB_QUEUE_MAX_DOCUMENTS` | 8 | A chosen 400 MB storage budget for waiting submissions divided by the existing `MAX_FILE_SIZE_MB` of 50. The storage budget is a choice, not a measurement, because the module declares no volume and no disk quota to derive one from. | Chosen, stated |
| Result retention | `OCR_JOB_RETENTION_SECONDS` | 14,400 s | Three job reading ceilings, so a caller whose polling died has a working session to notice and collect. It is a product trade against how long a document's own text sits on the service, not a measurement, and lowering it costs only late collection. | Chosen, stated |
| Retained record cap | `OCR_JOB_MAX_RETAINED` | 100 | The window alone bounds nothing, because what fits inside it depends entirely on how fast the work is: about 160 documents if each is one A4 page at 90 s, and thousands if they are small images finishing in seconds. The count is what turns that into a stated number. 100 records at an estimated 100 KB for a twenty five page result is about 10 MB, and that per-result size is unmeasured, so task 1.3 measures it. | Derived from an unmeasured size |
| Jobs directory | `OCR_JOBS_DIR` | an `ascend-ocr-jobs` directory beside the existing scratch directory | Matches `OCR_SCRATCH_DIR`'s own default shape. Kept separate from scratch because the two have different lifetimes and different sweep horizons. | Convention |
| Scratch sweep horizon | derived | job reading ceiling + dispatch margin | Replaces `OCR_REQUEST_TIMEOUT + OCR_DISPATCH_MARGIN_SECONDS`. A legitimate 80 minute job must never have its own working file swept out from under it. | Derived |

Two values stay exactly as the previous change deployed them and are not reopened here: `OCR_DETECTOR_MAX_SIDE` at
1536 and `OCR_MAX_INFERENCE_PIXELS` at 2,500,000, the owner's measured pair recorded in
[ADR-006](../../../ascend-ocr/docs/architecture/decisions/ADR-006-detector-input-bound.md). Every memory figure below
assumes them.

### The job page ceiling, derived

The model, from the previous change, with the detector bound applied to the detection term only:

```text
peak_MiB = 635 + 143 x (cached_languages - 1) + 4984 x MP_seen_by_detection + 318 x MP_of_the_page + 11.5 x pages
```

Detection sees the page scaled so its long side is at most `OCR_DETECTOR_MAX_SIDE`, which is 1536. Page count enters
only through the 11.5 MiB each page's retained result costs, so the page ceiling is exactly the headroom a single
page leaves, divided by 11.5.

Worked for the three standard page sizes at the library's fixed 144 dpi, on a worker that has cached all eight
languages, which is the worst case:

| Page | Rendered | Detection sees after the 1536 bound | Fixed plus one page's transient | Pages at R = 12,288 MiB | Pages at R = 11,059 MiB (90 percent) |
|---|---|---|---|---|---|
| A4 | 1190 x 1684, 2.004 MP | 1.667 MP | 10,583 MiB | 148 | 41 |
| US Letter | 1224 x 1584, 1.939 MP | 1.823 MP | 11,339 MiB | 82 | none, the page alone is over |
| US Legal | 1224 x 2016, 2.467 MP | 1.432 MP | 9560 MiB | 237 | 130 |

Three things to read off it.

US Letter is the expensive one, which is not the intuition. It is smaller than Legal in area, but its long side is
closest to the bound, so the 1536 downscale barely fires and detection sees the most pixels of the three. Page area
is the wrong thing to reason about once a long-side bound is deployed.

One page of US Letter does not fit a 90 percent resident budget on a fully warmed engine cache. That is a
pre-existing property of the shipped pair rather than something this change introduces: the previous change's own
ceiling table gives 1.72 MP as the safe input at 90 percent with a 1536 bound, and Letter is 1.94 MP and A4 is
2.00 MP, both above it. It ships that way because refusing A4 was judged worse than running with less headroom, and
the pixel ceiling of 2.5 MP is what accepts them. Nothing here changes that trade. It is restated because a page
ceiling derived from the same model has to be honest about which page sizes the model says are already tight.

The ceiling is therefore the smaller of the two defensible readings, 41 pages from A4 at 90 percent and 82 from
Letter at the container limit, rounded down to 40. That is 60 percent more than the twenty five pages the request
asked for, and 3.7 times under the A4 figure at the full container limit.

A second memory term exists and is not binding. Forty pages of results is 460 MiB accumulated inside the worker, and
returning it costs the API process roughly two copies of the serialised result while it is unpickled. That lands
after the last page's transient has been released, when the worker holds its 1636 MiB of process and cache plus the
460 MiB of results, so the container total at that moment is a few gigabytes rather than the eleven the inference
peak reaches. This is reasoning from the model rather than a measurement, and task 1.2 measures the container's peak
on a forty page document before the ceiling is ever raised further.

The extrapolation is named. The 11.5 MiB per page slope was fitted against documents of up to about twenty pages, so
forty is roughly twice the fitted range. It is the gentlest term in the model and the one least likely to surprise,
but task 1.2 confirms it rather than assuming it.

### What the caller experiences, end to end

At the defaults, for a twenty five page A4 scan submitted with nothing else in the queue:

1. The submission is answered in the time it takes to read the file and its page headers, with an identifier.
2. The document is read for about 37 minutes at the measured 90 s per page, with a hard stop at 3000 s, which is
   twenty five allowances.
3. Polling every 10 s costs about 225 status reads, each a small file read, well inside the 60 per minute default
   rate limit.
4. The result is collected, and it is byte-identical in shape to what `POST /v1/ocr` would have returned had it been
   able to wait.
5. The result stays collectable for four hours, or until the caller deletes it.

If another document is being read when the submission arrives, everything above shifts by that document's remaining
time, and the submission is told how many pages are ahead of it so the shift is a number rather than a mystery.

## Decisions

### Decision 1: the shape is submit and collect, and the three cheaper shapes each fail for a stated reason

Raising the absolute ceiling and keeping one synchronous request is the smallest possible change, and it is the one
to beat. It fails on the thing that made the original incident an incident. A twenty five page document needs about
2250 s. Both in-platform callers abandon the request at 300 s, and FastAPI does not notice that a client has gone
for an ordinary request handler, so the service would keep inferring pages for another 32 minutes for nobody. That
is precisely the behaviour the previous change was written to end, arriving through the front door with the
service's own blessing. Everything else about it is also worse: a dropped connection at minute 35 discards 35
minutes of work with no way to ask for it back, and a second caller waiting behind the job fails on its own budget
long before the job finishes. Rejected.

Streaming the result page by page over the one connection is the middle path, and it does return value early. It
does not fix the problem, because the connection is still held for the whole reading and a disconnect still loses
the rest. It also costs more than it looks: the response shape changes, so it is a new endpoint under ADR-003 rather
than an evolution of `/v1/ocr`, MCP has no equivalent for a tool result that arrives in pieces, so the two surfaces
would stop agreeing, and it contradicts the existing requirement that an expired request returns nothing partial,
which exists because a caller cannot tell a truncated document from a short one. Rejected.

Splitting the document on the caller's side is the cheapest of all, because it needs no change here. It is also
already what the platform's own caller does, and watching it is instructive: `DocumentRouter` slices a PDF into
single page PDFs and dispatches four at a time, against one worker and a per-request budget that counts queue time.
Decision 12 works the arithmetic through. Splitting also pushes page ordering and reassembly onto every caller, does
nothing for a raw image, and does nothing for an MCP client holding one PDF. Rejected as a general answer, and its
in-platform instance is Decision 12.

Delivering the result by callback instead of by polling is the fourth shape. It requires the caller to run a
listener, and it requires this service to make an outbound request to a caller-supplied URL, which is exactly the
capability its SSRF guard exists to deny. It also brings retries, delivery failure states and a shared secret with
it. Polling costs the caller a small GET and costs the service a file read. Rejected.

So: submit, poll, collect. The previous change named this as the eventual answer and deliberately left it for a
separate change, and the measured per-page cost is what makes it due now.

### Decision 2: the synchronous request is untouched, and the job path is additive

`POST /v1/ocr` and `ocr_process` keep their shape, their parameters, their error codes and their two page limit. The
job path is new endpoints and new tools beside them. Under ADR-003 that is a non-breaking change requiring no
version bump on either surface, and it means the AscendAgent's `AscendOcrClient`, the Bruno collection, the contract
stub and every existing e2e spec keep passing untouched.

The alternative, replacing the synchronous request with the job path, was rejected twice over: it is breaking, so it
costs a `/v2/ocr` and an `ocr_process_v2` with a deprecation window under ADR-003, and it is worse for the common
case, which is one image or one page that finishes in 90 s and wants one round trip rather than three.

The consequence to accept is two paths through the same machinery. It is bounded by making them share everything
below the boundary: the same input guards, the same admission gate, the same dispatch function, the same worker, the
same deadline. What differs is only who waits.

### Decision 3: job state lives in files, and the files are the source of truth

One record per job as JSON under `OCR_JOBS_DIR`, written by temporary file and atomic replace, plus the submitted
bytes beside it until the job reaches a terminal state, plus a small progress file while it runs. The API process
keeps only the pending queue in memory, and the queue starts empty on every boot because Decision 4 fails
everything that was in flight.

Files rather than memory, because a completed result that a restart destroys is 37 minutes of compute lost to an
event that has nothing to do with the caller.

Files rather than Redis, even though the platform runs one. This module has no external service dependency today,
which is what lets it be deployed and tested on its own, and a job store is not a good enough reason to give that
up. Redis would also add a failure mode with no answer: a job store that is unreachable makes the whole job path
fail while the OCR engine itself is perfectly healthy.

Files rather than SQLite, because there is exactly one writer, no query beyond fetch by identifier, and at most a
few hundred records inside a retention window. SQLite would buy transactions this design has no use for and add a
schema to migrate.

The single-writer property is what makes files safe here. The API process runs one event loop, so record writes are
serialised by construction, and the only thing the worker process writes is its own job's progress file. Every write
is temp plus `os.replace`, so a reader never sees half a record. Writing the submitted bytes and reading the result
back are done off the event loop, because 50 MB of file I/O inside a request handler would block every other request
including `/health`.

### Decision 4: a restart fails work in flight rather than resuming it

At startup, before the runner starts, every record found waiting or running becomes failed with a distinct
`SERVICE_RESTARTED` reason, and its submitted bytes are removed. Finished records are left alone and keep their
original expiry.

Resuming a running job is wrong for the reason Decision 12 of the previous change already established: the service
cannot know whether the document it was reading is what brought it down, and a resume feeds the killer its input
again. Re-queueing work that was merely waiting is safer and was still rejected, because the service cannot
distinguish a deliberate restart from a crash loop, and a queue that replays itself on every boot is a crash loop
with a longer period. The caller still holds the bytes and a resubmission is one call.

What the distinct reason buys is the thing a caller actually needs: `OCR_FAILED` means the service tried and could
not read this document, and resubmitting it will fail again, while `SERVICE_RESTARTED` means nothing was learned
about the document and resubmitting is exactly right.

The honest limit of the durability, which the deployment page states rather than implies: the records survive the
process restarting and the container restarting, because they are on the container's filesystem. They do not
survive the container being recreated, which is what `docker compose up --build` does. An operator who needs that
mounts a volume at `OCR_JOBS_DIR`, and that is a documented option rather than a default, because the default
deployment of this module has no volumes and adding one silently would surprise.

### Decision 5: one retention window, a count bound, and an expired identifier is a plain not-found

A finished record and its result live for `OCR_JOB_RETENTION_SECONDS` from the moment they finished, and the sweep
that removes them runs at startup and on the runner's idle tick, so removal never waits for a caller to arrive. The
count bound evicts the oldest finished record when there are more than `OCR_JOB_MAX_RETAINED`, because the time
bound alone does not bound storage when work is fast.

An expired identifier answers `JOB_NOT_FOUND` with a 404, the same as an identifier that never existed, and the
message says unknown or expired. The alternative was a tombstone, keeping the identifier and its expiry after the
result is dropped so that expiry can answer 410 Gone and be distinguished from a typo. It is rejected as machinery
that buys a distinction nobody acts on: identifiers are 128 bit random tokens, so an identifier that reaches the
service and is not held is an expired one in practice, and a tombstone needs its own lifetime and its own bound,
which is a second retention policy to reason about.

### Decision 6: the queue is bounded twice, and a full queue is a 503 with its own code

Two bounds, because they bound different resources. Pages bound the wait, which is the only reason a caller cares:
the promise is that a newly accepted submission starts within the pages ahead of it multiplied by the per-page
allowance. Documents bound the storage, because every waiting submission's bytes sit on disk until it runs, and a
queue bounded only in pages admits eighty single page submissions at 50 MB each.

The previous change rejected a count bound on its own admission gate, and that rejection still stands for that gate,
for the reason it gave: a synchronous request is already bounded by its own deadline, so time is the honest bound
and a count bound would need an overflow response it did not have. Neither half applies here. A queued job has no
deadline running against it, so time bounds nothing, and the overflow response is a new code, which ADR-003 permits
outright.

`QUEUE_FULL` with a 503 rather than the rate limiter's 429, because the two mean different things to a client. 429
says this caller is asking too often and the fix is for it to slow down. 503 says the service is temporarily out of
capacity and the fix is to come back, which is true regardless of who is asking, and it carries `Retry-After`
naturally. Overloading 429 would also make the rate limiter's own metrics lie.

### Decision 7: the wait is not charged to the reading budget, and that does not contradict the deadline capability

A job's reading budget starts when the worker starts reading it. Time spent waiting in the queue is not deducted.

The existing requirement that a queued request counts its wait against its own budget exists for a stated purpose:
no inference is ever started for a caller who has already been told the request failed. That purpose is preserved
exactly. A synchronous caller holds a connection with a timeout running, so time spent waiting really is time gone
from the answer's usefulness. A job's caller has been told nothing except that the work was accepted, and it is
still true when the reading starts.

Mechanically the job runner acquires the same admission gate before it starts the job's clock, so a job never
consumes a permit and a budget at the same time, and a job cannot start reading while a synchronous request is
being served.

What replaces the deadline as the bound on waiting is the queue bound of Decision 6. That is why the bound is
expressed in pages: it converts directly into the longest possible wait.

### Decision 8: cancelling a running job replaces the worker

Cancelling work that has not started is a list removal and needs nothing. Cancelling work that is running has two
possible mechanisms.

The cooperative one mirrors the deadline: signal the worker, and it stops at the next page boundary. It costs a new
cross-process signal, and it costs up to one page of continued inference, which is 90 s of a worker nobody wants.

The chosen one reuses `_rebuild_pool` with a third reason. The worker is replaced, the inference stops with the
process, and the next queued job starts as soon as the new worker has warmed, which ADR-004 measures at 5 to 15 s.

Replacement wins on both axes that matter. It stops the work in the time a warm-up takes rather than in the time a
page takes, and it needs no new machinery at all, where the cooperative path needs a signal that has to survive a
pool rebuild and be cleared correctly between jobs. The empty pool queue that Decision 4 of the previous change
established is what makes replacement cheap: there is never anything queued inside the pool to lose.

The trade to state: a cancel costs the next job a warm-up. Cancels are rare, a human changing their mind, and 15 s
against the 40 minutes being reclaimed is not a trade worth optimising.

### Decision 9: progress is a file the worker writes between pages

The worker already has a per-page seam and already writes to the service's own directories. After each page it
writes the completed page count to a small file named for the job, by temp plus replace, and the API process reads
it when a status poll arrives.

A shared `multiprocessing.Value` passed through the pool's initargs was the alternative. It is faster, and it is
worse here: it depends on synchronisation primitives surviving pickling into initargs under the spawn context on
both Linux and Windows, which is exactly the kind of platform-dependent behaviour this module's Windows test runs
keep discovering, and one counter tied to a pool does not survive a pool rebuild. Reading progress out of the
Prometheus multiprocess files, the way `is_engine_warm` reads warm-up, was also rejected: those counters are not
attributed per job, so they cannot answer how far this document has got.

Forty writes of a few bytes across an hour of inference is not a cost worth measuring.

### Decision 10: one status resource that carries the result when there is one

`GET /v1/ocr/jobs/{job_id}` answers with the state, and when the state is success it carries the result inline. A
separate `/result` sub-resource was considered so that polls stay small, and rejected: while the job runs there is
no result to carry, so every poll but the last is already small, and the sub-resource costs a second endpoint, a
second MCP tool, and a state-conflict answer for reading a result that does not exist yet.

`DELETE /v1/ocr/jobs/{job_id}` means stop it if it is running and forget it, in one verb, because that is one
intention rather than two. A separate cancel action plus a delete was rejected as two operations, two tools and two
sets of state rules for the one thing a caller wants, which is for the work and its result to be gone.

Submission answers 202 rather than 201, because the interesting fact is that the work was accepted and is not
finished. The `Location` header points at the status resource, which is where a 201 would have pointed anyway.

### Decision 11: no priority for synchronous requests over queued jobs

Strict submission order across both paths, with no queue jumping.

Priority for synchronous requests was considered, since they are the interactive path and they are bounded at 240 s.
It buys almost nothing, because what a synchronous caller waits behind is the job that is already running, and
priority cannot preempt that. It would only skip the queued jobs, which are not what is blocking. It also introduces
starvation: at 20 submissions per minute allowed by the rate limiter, a stream of synchronous requests could hold a
job out of the worker indefinitely.

The consequence is stated in the spec rather than hidden: while a long document is being read, a synchronous request
waits on the gate and fails on its own budget. The honest answer to that is the job path, which is what this change
adds.

### Decision 12: what the AscendAgent does is left alone, and recorded

The agent slices every PDF page by page and dispatches four at a time. Each of those four is one page, so each gets
an effective budget of `min(1 x 120, 240)`, which is 120 s. Against one worker at about 90 s per page the first is
served, the second is admitted at about 90 s with 30 s of budget left and fails after paying for a whole page
because its deadline expired while that page was being read, and the third and fourth expire on the admission gate
at 120 s without ever being dispatched. One page in four succeeds. That arithmetic is from the code and the measured
per-page cost rather than from an observed run, and task 9.3 is what confirms it.

Two fixes exist and both belong to the agent, not here: lower `pdf-parallel-pages` to 1, or stop slicing and submit
the whole PDF as a job. Changing this module's behaviour to accommodate a caller's fan-out would mean either more
workers, which the memory model forbids, or a queue that does not charge synchronous callers for their wait, which
is the thing that stops abandoned work.

One more observation from reading that path, recorded because it is load-bearing for anyone testing the agent
against this module and is not fixed here: `AscendOcrClient` posts its multipart part as `files`, while
`/v1/ocr` declares `file`. That mismatch is the agent's to confirm and fix.

### Decision 13: the identifier is the credential, so it is random and it is never a path

The service has no authentication. Anyone who can reach it can submit, and under this change anyone holding an
identifier can read a document's extracted text. So the identifier is 128 bits from a cryptographic random source,
URL-safe, and never derived from the filename, the content or a counter.

The identifier also becomes part of a filename in the job store, which makes it an injection surface. Every
identifier arriving from a caller is validated against a strict character and length pattern before it is used to
build any path, and rejected as `JOB_NOT_FOUND` if it does not match, so a traversal attempt is indistinguishable
from a typo and never reaches the filesystem. The `/security-review` skill is listed for exactly this and for the
fact that results hold document text at rest.

### Decision 14: two new codes, and the existing catalogue is untouched

`QUEUE_FULL` at 503 and `JOB_NOT_FOUND` at 404 join the catalogue in `exception_handlers.py` and in ADR-002.
`SERVICE_RESTARTED` is different in kind: it is a failure reason inside a job record and never an HTTP status,
because the request that reads a failed job succeeded.

That last point is the one place where the shape of a failure changes, and it deserves saying plainly rather than
being discovered. On the synchronous path a failure is an HTTP status with a code. On the job path a failure of the
reading is a successful read of a record that says it failed, carrying the same code. `OCR_FAILED` means the same
thing in both places.

The input-limits requirement that refusals introduce no new error code is not contradicted. It governs refusals of
oversized input, and those still answer `FILE_TOO_LARGE` on both paths, including the job page ceiling. The two new
codes are not refusals of oversized input.

### Decision 15: the MCP surface mirrors the three operations as three tools

`ocr_submit`, `ocr_job_status` and `ocr_cancel_job`, taking the same arguments the REST operations take, returning
the same records, raising the same codes with the surface's existing `CODE: detail` convention. `ocr_process` is
untouched, so no tool is renamed and ADR-003's tool-name versioning is not engaged.

The alternative of leaving MCP synchronous-only was rejected against the existing requirement that both surfaces
behave identically, and against the practical point that an MCP client is the caller least able to hold a connection
for 40 minutes.

Both surfaces call one service layer that owns the store, the queue and the runner, so a behaviour can only be added
in one place. The existing cross-surface test module is where that agreement is asserted.

### Decision 16: no idempotency key in this version

The `/api-design` skill asks for an `Idempotency-Key` on non-idempotent POSTs, and this change does not build one.
The submission returns in the time of a file read, so a client-side retry storm is unlikely, the queue bound already
converts duplicate submission from unbounded waste into a refusal, and a key store brings its own lifetime, its own
bound and its own body-mismatch answer. What would change the decision is one observation of a caller, most likely
an MCP client, submitting the same document twice. At that point the key maps to the existing job identifier and
inherits the retention window, which is a small addition to a store that already exists.

## Why the four pending capabilities still read true

`stop-ocr-getting-stuck-on-large-jobs` is not archived, so its four capabilities are still deltas. This change adds
to them rather than altering them, and each of its requirements was checked against the job path:

- A request budget derived per page and capped overall. Holds. A job uses the same per-page allowance under its own
  ceiling, and both remain configurable.
- An expired request stops computing, from a duration, checked between pages. Holds unchanged. Jobs go through the
  same worker and the same `_predict_pages` loop.
- An expired request fails with the existing OCR failure code and returns nothing partial. Holds. A failed job
  carries `OCR_FAILED` and no page content. Decision 14 records that on the job path the code arrives inside a
  successfully read record.
- Requests waiting for the worker hold their own deadline. Holds for synchronous requests, unchanged. Decision 7
  explains why a job is not one of them and why the requirement's stated purpose is preserved.
- One job at a time, and the limit is explicit. Holds and is reinforced: the job runner acquires the same gate, and
  the job page ceiling is derived from the same memory model that the worker cap rests on.
- A worker that will not stop is replaced, a broken pool is rebuilt, a killed worker's files are reclaimed. Holds,
  with cancellation added as a third trigger for the existing replacement path and the sweep horizon lengthened to
  the longest legitimate job.
- The pixel ceiling, the bomb guard, and refusals reusing the existing error model. Holds. All of them run at job
  submission exactly as they run on the synchronous path, with the same codes.
- A document with too many pages to finish is refused up front, derived from the per-page allowance and the ceiling.
  Holds identically, because the job reading ceiling is derived as page ceiling multiplied by allowance, so the
  invariant is true by construction on both paths.
- Readiness reports not-ready exactly when the service cannot take work, and busy stays ready. Holds. A long job is
  busy and in budget, so the status is unchanged, and the two new fields are additive in the way ADR-004's amendment
  already established for `queue_depth`.
- The memory bounds capability. Untouched. The detector bound and the pixel ceiling keep their deployed values, and
  the job page ceiling is a new consumer of the same fitted model.

## Risks / Trade-offs

A long job makes the synchronous path unusable for its duration, and this change makes long jobs possible.
Mitigation: it is the physics of one worker rather than a regression, the queue and the running job are visible on
`/ready` and in metrics, a synchronous caller gets a definitive failure rather than a hang, and the job path is
available to any caller that would rather wait properly.

The worst-case wait a full queue promises is 2 h 40 min. Mitigation: it is a number rather than an unknown, it is
reported to the caller as pages ahead at submission time, and it is one setting to lower.

A result is a document's extracted text sitting on the service's storage for up to four hours, on a service with no
authentication, readable by anyone holding a 128 bit identifier. Mitigation: the identifier is the credential and is
random, callers can delete early, the retention window is one setting, and the exposure is recorded in the ADR so
that adding authentication is a visible decision rather than an assumed one.

Records do not survive a container recreate unless a volume is mounted. Mitigation: stated in the deployment page
and in the ADR, a volume is a one line addition for an operator who needs it, and the failure mode is a caller
resubmitting rather than a caller misled.

The forty page ceiling rests on the 11.5 MiB per page slope extrapolated about twice beyond its fitted range, and on
a reading of the largest-page transient that assumes the shipped detector bound and pixel ceiling. Mitigation: task
1.2 measures a forty page document's container peak before anything relies on it, the ceiling is far below the same
model's own figure at the container limit, and the number is one setting.

Reading US Letter at the deployed pair leaves no margin under a 90 percent resident budget. Mitigation: this is
disclosed, pre-existing and unchanged by this design, and the page ceiling was deliberately taken from the tighter
of the two readings so that it does not compound.

Two new surfaces on two protocols is more to keep in agreement. Mitigation: one service layer beneath both, the
existing cross-surface test module extended, and a spec requirement that says agreement in observable terms.

A caller that submits the same forty minute document twice occupies the worker twice. Mitigation is the queue bound,
which turns unbounded duplication into a refusal, and Decision 16 records why an idempotency key was not built and
what would change that.

## Migration Plan

An image rebuild plus two compose edits. There is no schema, no data migration and no persisted state to convert,
because there is none today.

Ordered, because one of the settings is not a default:

1. Deploy the image. Every new setting has a default that is safe on its own, and the job path is available
   immediately.
2. Set `OCR_REQUEST_TIMEOUT=240` in `docker-compose.yaml`, replacing 300. Nothing a caller can observe changes, for
   the reason in the numbers table. Leaving it at 300 is also harmless, and only leaves the ceiling unreachable
   again.
3. Optionally mount a volume at `OCR_JOBS_DIR` if finished results must survive a container recreate. Without it,
   they survive restarts but not recreates.

Rollback is reverting the image and the compose edit. A caller loses the job endpoints and gets the old synchronous
behaviour back, and no caller has to change anything, because nothing about the synchronous path moved. Job records
left on disk by the rolled-back version are inert files that nothing reads.

## Open Questions

1. What is the p95 per-page inference time on the deployment's 4.0 CPU allocation? Inherited from the previous
   change's task 1.2 and still open. It would tighten `OCR_PAGE_TIMEOUT_SECONDS`, which would move the job reading
   ceiling with it. Nothing here depends on the exact value, because every derivation is expressed in allowances.
2. What does a forty page A4 document actually peak at, and what does its serialised result weigh? Task 1.2 and task
   1.3 measure them. The first bounds the page ceiling, the second bounds the retained record cap. Both are
   confirmations of numbers already derived rather than inputs to the design.
3. Should the retention window be shorter than four hours on a service with no authentication? It is an owner trade
   between collecting late and holding document text, one setting either way, and it changes no interface.
