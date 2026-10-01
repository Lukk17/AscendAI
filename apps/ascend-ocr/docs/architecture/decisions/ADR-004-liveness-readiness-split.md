# ADR-004: Liveness (`/health`) and readiness (`/ready`) endpoints serve different audiences

## Status

Accepted - 2026-05-31. Amended - 2026-09-07: readiness gains a second condition (see "Amendment" below). Amended
again - 2026-09-07: the overrun signal behind that condition is fixed for more than one worker (see "Amendment
(2026-09-07): the overrun signal at more than one worker" below). Amended again - 2026-09-24: two additive fields
report the job queue, and the bucket is deliberately not wired to readiness (see "Amendment (2026-09-24)" below).
Amended again 2026-09-25: `queue_depth` and its gauge are removed, and a cancel's worker replacement is reported
without the cancel waiting for it, while the next document does wait for it (see "Amendment (2026-09-25)" below).

## Context

A single `/health` endpoint that returns "I'm alive" satisfies Docker's healthcheck - the container reports up, the orchestrator stops sending kill signals. It does *not* satisfy a load balancer that wants to know whether the process can handle real traffic, because ascend-ocr's first OCR call after a cold start has a 5-15 s warm-up latency while PaddlePaddle materialises the model. During warm-up, the process is alive but useless to the caller.

The previous `/health` endpoint returned `{"status": "ok", "version": "..."}` unconditionally - before the engine was warm, before lifespan even ran. The Docker healthcheck would mark the container healthy, and the load balancer would route traffic in, only for the first request to hang for 10 seconds while the engine loaded.

## Decision

Split the concern into two endpoints with different semantics:

### `/health` - liveness

Always returns 200 OK as long as the FastAPI process is running. Returns `{"status": "ok", "version": "..."}`. No dependency probes, no engine checks. This is what Docker's `HEALTHCHECK` and Kubernetes' `livenessProbe` should hit.

The only failure mode is "the process is wedged so badly it can't respond at all" - at that point the orchestrator should restart the container, and `/health` is the signal for that.

### `/ready` - readiness

Returns `{"status": "ready" | "not-ready", "version": "...", "engine_warm": bool}`. The `engine_warm` flag is `true` iff `is_engine_warm(settings.DEFAULT_LANGUAGE)` (`src/observability/metrics.py`) finds a recorded `ENGINE_WARMUP_DURATION_SECONDS` observation for that language. Returns 200 OK in both cases; consumers decide whether to route traffic based on `status`.

This is what a Kubernetes `readinessProbe` should hit. While `engine_warm=false`, the load balancer removes the pod from the rotation. Once the warm-up completes, the next probe sees `ready` and the pod gets traffic.

The engine actually warms inside the OCR worker process (a separate `ProcessPoolExecutor` process, see `start_worker_pool` in `src/service/ocr_service.py`), not in the main process that answers `/ready`. `/ready` cannot read that worker's in-memory state directly, so it crosses the process boundary the same way the engine-cache eviction counter already does: the worker's `warm_up_engine` call observes `ENGINE_WARMUP_DURATION_SECONDS` into its own file under `PROMETHEUS_MULTIPROC_DIR`, and `is_engine_warm` reads that file back via `MultiProcessCollector` instead of polling the worker or triggering a warm-up itself. `observe()` only runs after the engine builds successfully, so a warm-up that is still pending or that failed both read back as `engine_warm=false`, with no separate failure flag needed.

### Why not a synthetic OCR probe in `/ready`

The first considered option was to do a tiny synthetic OCR run on a 1×1 bundled PNG in `/ready`. Rejected because:

- It costs ~50-100 ms per probe. Kubernetes default probe interval is 10 s; that's a real CPU hit for a probe.
- It doesn't add signal beyond `engine_warm`. The engine either loaded successfully (predict will work) or it didn't.
- It introduces a subtle race: `/ready` could pass while a different language's engine is mid-load. The flag-based check avoids that.

A warm-up failure inside the worker's pool initializer surfaces to the main process as `concurrent.futures.process.BrokenProcessPool` when `start_worker_pool` waits on the initializing task's result. The main process catches that specific exception, logs it, and continues starting instead of letting it propagate out of the FastAPI lifespan, which would otherwise kill the container before `/health` or `/ready` ever answered. `/ready` then reports `not-ready` forever for that process (no observation was ever recorded), and a real OCR request against the now-broken pool surfaces as a handled `500 INTERNAL_ERROR` through the existing global exception handler rather than an unhandled crash.

## Amendment (2026-09-07): readiness gains a second condition

`stop-ocr-getting-stuck-on-large-jobs` gave the service ways to be alive but genuinely unable to take work that did
not exist when this ADR was first accepted: a worker that has not stopped within its reclamation grace, a worker pool
found broken, and a rebuild of either in progress. `engine_warm` alone cannot express any of those, so
`ReadinessResponse` gains two additive fields, `accepting_work: bool` and `queue_depth: int`, and `status` is now
`ready` only when **both** `engine_warm` and `accepting_work` are true.

`accepting_work` is `false` in exactly four cases, all in `src/service/ocr_service.py`: the engine has never warmed
(unchanged from the original decision above), the worker pool has failed consecutive rebuilds past
`OCR_POOL_REBUILD_MAX_CONSECUTIVE` and stays unusable, a worker replacement or pool rebuild is in progress, or the
in-flight job is past its own budget and has not yet been reclaimed. `queue_depth` reports how many requests are
waiting on the admission gate, so an operator can tell a busy service (queue depth rising, `status=ready`) from a
stuck one (`status=not-ready`) without inferring it from other signals.

**Liveness is deliberately untouched.** None of the four conditions above make `/health` fail. A worker replacement
or pool rebuild fixes the exact problem a container restart would fix, at the cost of an engine warm-up (5-15 s)
instead of the whole container's, and without dropping every other request queued behind it. Making `/health`
depend on worker state was already rejected once in this ADR's original decision (see "Why not a synthetic OCR
probe"), and the same reasoning applies here with more force: `/health` would now flap during ordinary self-healing.

**The endpoint's contract is unchanged.** `/ready` keeps answering 200 in both states, with the condition carried in
the body, exactly as the original decision specifies - busy-but-in-budget stays `ready`, because a queued request
will still be served, and consumers reading `status` are unaffected by the two new fields.

## Amendment (2026-09-07): the overrun signal at more than one worker

The four-condition amendment above was written and tested against `OCR_WORKER_COUNT=1`, where at most one job is
ever in flight. Making `OCR_WORKER_COUNT` a genuine runtime setting rather than a fixed constant exposed that the
"in-flight job past its own budget" condition had been implemented as a single module-level variable holding one
deadline. With more than one worker, more than one job can be in flight at once, and a shared variable cannot hold
more than one job's deadline: a second job starting overwrites the first job's entry, and either job's own `finally`
clears whichever value is currently stored, regardless of which job it belonged to. The practical failure is
`is_job_overrunning()` (and therefore `accepting_work`) silently going blind to a genuinely stuck job whenever a
second, unrelated job starts or finishes around it - the exact readiness signal this ADR exists to keep honest.

Fixed by keying the tracked deadlines by a private per-call token in a dict (`_active_deadlines` in
`src/service/ocr_service.py`) rather than a single scalar, so `is_job_overrunning()` reports `True` if *any*
currently in-flight job has passed its own deadline. Regression test:
`tests/service/test_ocr_service.py::TestPoolHealthSignals::test_is_job_overrunning_true_when_one_of_several_jobs_is_past_budget`
and `TestDispatchOcrRequest::test_concurrent_jobs_track_independent_overrun_deadlines`, the latter driving two real
concurrent calls through `dispatch_ocr_request` and asserting the still-running job's own tracked deadline survives
the other job's own completion.

A second, related defect surfaced in the same review: `_rebuild_pool` called `stop_worker_pool()` directly, with no
`await`, unlike its own `start_worker_pool()` call two lines below. `ProcessPoolExecutor.shutdown(wait=True)` blocks
until *every* currently in-flight work item across *every* worker finishes, not only the one that triggered the
rebuild - proven against the real stdlib: a two-worker pool with one fast job and one 8-second job took 7.94 s to
shut down, not the fast job's own time, and a synchronous call to that shutdown from inside a coroutine blocks the
coroutine's own event loop thread for the whole span (also proven directly: an unrelated concurrent coroutine's own
0.05 s heartbeat produced zero ticks until a blocking call inside the same rebuild path returned). At
`OCR_WORKER_COUNT=1` this bound is roughly one page's own remaining inference time, since there is never a second job
to wait on. At more than one worker it is bounded by nothing shorter than another worker's own full budget, so one
stuck job could freeze the *entire* service - not only OCR dispatch, every coroutine on the same event loop, including
unrelated admission waits and MCP request handling - for as long as an entirely healthy, unrelated job on a different
worker takes to finish. Fixed by offloading `stop_worker_pool()` through `loop.run_in_executor`, matching
`start_worker_pool()`. Regression test:
`TestRebuildPool::test_stop_worker_pool_does_not_block_the_event_loop`.

That fix opens a window it did not have before: a concurrent request can now reach `get_process_pool()` in the gap
between the old pool being torn down and the replacement being stood up, where it previously could not, because the
event loop was frozen for that whole gap. `get_process_pool()` raises `RuntimeError` in that state; the call site
moved inside the same `try` that already converts a broken pool to `OcrProcessingError`, so this new, narrow window
gets the same clean, handled failure rather than an unhandled exception. Regression test:
`TestDispatchOcrRequest::test_pool_torn_down_mid_rebuild_fails_cleanly`.

**More than one worker is safe today for these three reasons, not by assumption.** The admission gate's permit count
and the pool's own `max_workers` were already read from the same `OCR_WORKER_COUNT` setting before this amendment
(task 2.4/4.1 of `stop-ocr-getting-stuck-on-large-jobs`), so those two were never at risk of drifting apart. A fourth
issue was found and fixed alongside these three but does not touch readiness: `start_worker_pool()` used to submit
exactly one warm-up task regardless of `OCR_WORKER_COUNT`, so only the first worker was ever proactively spawned and
warmed at startup - `ProcessPoolExecutor` spawns the rest lazily, only once real concurrent traffic needs them, each
paying its own warm-up cost (seconds) inside that caller's own request. Fixed by submitting one warm-up task per
configured worker before collecting any result, forcing one OS process per worker up front. Proven live, not only in
the test suite: starting the pool with `OCR_WORKER_COUNT=1` spawned exactly 1 live worker process; with
`OCR_WORKER_COUNT=2`, exactly 2, and the startup banner's own arithmetic scaled from `~14201 MiB` to `~28402 MiB`
accordingly.

## Consequences

### Why this shape

- **No traffic during cold start.** The load balancer waits for `engine_warm`. Cold-start latency is moved from the caller to the lifecycle layer where it belongs.
- **Clear escalation path.** If `/health` fails, the process is broken - restart. If `/ready` fails, the process is healthy but not yet useful - wait. Different signals, different responses.
- **Cheap probes.** Both endpoints are O(1) lookups; both can be probed at high frequency without measurable cost.

### Trade-offs

- **Two endpoints to document.** Operators reading the runbook see two probes instead of one. The startup banner now prints both URLs so it's hard to miss.
- **Readiness signal is binary.** If the default language warms up but `pl` does not (because ascend-ocr's model server is flaky for that specific lang), `/ready` is `ready` but a `lang=pl` request still has to do a lazy warm-up. Acceptable; the cold-start window is rare and the alternative (per-language readiness) is significant configuration burden for low value.
- **No Kubernetes startup probe yet.** For long cold starts (>30 s), Kubernetes' `startupProbe` is the better fit than fighting `readinessProbe`'s `initialDelaySeconds`. Defer until we deploy to k8s.

### Alternatives considered

- **Single `/health` that also probes the engine.** Rejected - conflates "restart me" with "send traffic later." Causes spurious container restarts during cold start.
- **`/health?check=engine` query parameter.** Rejected - same logical endpoint with two behaviours is harder to reason about than two endpoints with one behaviour each.
- **Synthetic OCR probe.** Rejected - cost without signal, see above.

## Related

- `apps/ascend-ocr/src/main.py` - `health_check`, `readiness_check`.
- `apps/ascend-ocr/src/model/ocr_models.py` - `HealthResponse`, `ReadinessResponse` (`accepting_work`, `queue_depth`).
- `apps/ascend-ocr/src/observability/metrics.py` - `is_engine_warm`, the multiprocess-file readiness check.
- `apps/ascend-ocr/src/service/ocr_service.py` - `start_worker_pool`, `_warm_worker_engine`, `is_accepting_work`,
  `is_pool_usable`, `is_rebuild_in_progress`, `is_job_overrunning`, `_active_deadlines`, `_rebuild_pool`, the
  `BrokenProcessPool` handling.
- `apps/ascend-ocr/src/config/startup_banner.py` - emits both URLs and the per-worker memory arithmetic at startup.
- `apps/ascend-ocr/tests/api/rest/test_rest_endpoints.py` - `TestReadyEndpoint`, `test_unexpected_dispatch_exception_returns_500_not_a_crash`.
- `apps/ascend-ocr/tests/service/test_ocr_service.py` - `TestPoolHealthSignals`, `TestRebuildPool`,
  `TestWorkerPoolLifecycle::test_start_worker_pool_warms_every_configured_worker`,
  `TestDispatchOcrRequest::test_concurrent_jobs_track_independent_overrun_deadlines`.
- `apps/ascend-ocr/tests/observability/test_metrics.py` - `TestIsEngineWarm`.
- `apps/ascend-ocr/Dockerfile` - `HEALTHCHECK` points at `/health`, not `/ready`.
- `openspec/changes/stop-ocr-getting-stuck-on-large-jobs/` - the change that added the second readiness condition and
  made `OCR_WORKER_COUNT` a real runtime setting, which is what exposed the defects the second amendment above fixes.


## Amendment (2026-09-24): the job queue is reported, and the result store is not

[ADR-008](ADR-008-every-request-is-a-job.md) gave the service a queue, and an operator needs to tell a busy service
from a stuck one without reading logs. `ReadinessResponse` gains two additive fields, `jobs_queued` and
`jobs_running`, alongside the `queue_depth` the previous amendment added. `queue_depth` keeps its own meaning
unchanged: it counts requests waiting on the admission gate, which after ADR-008 has exactly one client.

Neither new field changes `status`. A long document with work queued behind it is **busy**, and busy stays `ready`,
because the waiting work will be served and a load balancer that pulled the service out of rotation would only make
the queue longer. `status` is still `ready` exactly when `engine_warm` and `accepting_work` are both true, and
`accepting_work` is still false in exactly the four cases the previous amendment lists.

**The result store is deliberately not part of readiness.** [ADR-009](ADR-009-results-in-object-storage.md) gives this
module an external service dependency, and the tempting move is to probe it here. A bucket blip would then flap
`/ready` for a queue that is perfectly able to keep accepting, reading and recording, which contradicts this ADR's own
rule that not-ready means the service cannot take work. A bucket problem shows in three other places instead: the
startup banner reports whether it answered at boot, the job metrics count upload attempts and failures, and any job
that cannot deliver finishes with the `RESULT_STORE_UNAVAILABLE` reason.

## Amendment (2026-09-25): `queue_depth` is removed, and a cancel does not wait for the replacement

**`queue_depth` is gone from the body.** It counted requests waiting on the admission gate. After
[ADR-008](ADR-008-every-request-is-a-job.md) the job runner is that gate's only client and takes a permit only when
the previous document has returned it, so the count was zero except for the instant the runner passed through the
gate. The 2026-09-25 end-to-end
run saw `/ready` report `queue_depth` 0 beside `jobs_queued` 2, and later 8. `jobs_queued` and `jobs_running`, added
by the previous amendment, are what measure the waiting work, so the field was removed rather than redefined as a
copy of `jobs_queued`. The body is now `status`, `version`, `engine_warm`, `accepting_work`, `jobs_queued` and
`jobs_running`. [ADR-003](ADR-003-versioning-strategy.md)'s table lists renaming a response field as breaking, and
removing one is no less so. No new version was minted, on the precedent of that ADR's 2026-09-24 amendment: nothing
in this repository reads the field. The captured OpenAPI copy the ascend-ai-agent kept at the time,
`src/test/resources/ascend-ocr/openapi-contract.json`, was deleted on 2026-09-25 and replaced by the Pact contract
[contracts/pacts/ascend-agent-ascend-ocr.json](../../../../../contracts/README.md), which pins only the fields the
agent reads and does not cover `/ready` at all.

**A cancel answers before the worker is replaced.** The same run measured `DELETE` on a running job at 11.9 s and
8.3 s, because the handler awaited the whole replacement: killing the worker, starting a new pool and warming its
engine. The event loop itself was not held, because `_rebuild_pool` already runs both halves through
`run_in_executor`. The `Date` header looked 12 s stale only because Uvicorn stamps it when the request arrives. The
cancel now calls `request_worker_replacement_for_cancel`, which starts the replacement as a background task and
returns. The record reads `cancelled` before the answer is sent, as before. `is_rebuild_in_progress` counts a
requested replacement from the moment it is requested, so `accepting_work` is false and `/ready` reports `not-ready`
from the instant `DELETE` answers until the new worker is warm, which is the condition the 2026-09-07 amendment
already lists. The lifespan waits for any replacement still running before it stops the pool, so a shutdown never
races one.

**The next document waits for the replacement.** A cancelled document can finish on its own between the `DELETE` and
the kill. The runner then used to take the next document straight away and hand it to the worker being killed, and
that document failed with `OCR_FAILED` through no fault of its own. The runner now starts every turn with
`wait_for_worker_replacements`, so the next document stays queued, reads `waiting`, and goes to the replaced, warm
worker. The `DELETE` still answers at once, because the wait is in the runner and not in the handler.
`wait_for_worker_replacements` uses `asyncio.wait` rather than `asyncio.gather`, so a runner stopped while it waits
leaves the replacement running for the lifespan to wait on.

**A permit goes back to the gate it came from.** `start_worker_pool` replaces the admission gate on every rebuild, and
`dispatch_ocr_request` used to release whichever gate was current, so a document read across a rebuild added a
permit to the new gate and more than `OCR_WORKER_COUNT` documents could then be admitted at once.
`_await_admission` now returns the gate it acquired and the dispatch releases that one.

**The `ascendocr_ocr_queue_depth` gauge is removed** for the reason `queue_depth` left the body: it counted waiters
on the admission gate and read zero whatever was queued. `ascendocr_job_queue_documents` and
`ascendocr_job_queue_pages` already measure the waiting work, so the gauge was removed rather than made a copy of
the first. No dashboard or alert in this repository queried it. The `ascendocr_ocr_queue_wait_seconds` histogram is
removed for the same reason: it timed the wait on that gate, which the runner never waits on, and
`ascendocr_job_queue_wait_seconds` already times the real wait, from submission to the start of reading.

**A cancel that lands before dispatch is kept.** The runner used to await a document's submitted bytes after taking
it from the queue and then write `running` over the record it had read before that await. A cancel arriving during
the read was overwritten: the document was read to `succeeded`, or failed as `INTERNAL_ERROR` when the cancel had
already removed the bytes, and the cancel also killed a worker that was not reading it. `JobStore.start` now
moves a record to `running` only if it still reads `waiting`, with no await between the check and the write, so it
is a compare-and-set on the single event loop. The runner skips a document `start` refuses, records a missing
input only on a record that is still unfinished, and asks for a worker replacement only when the cancelled document
was dispatched. `running` is written with no await before the dispatch, so a record reads `running` exactly while
the worker may be reading it.

The related code: `request_worker_replacement_for_cancel`, `wait_for_worker_replacements` and
`is_rebuild_in_progress`, `_await_admission` and `dispatch_ocr_request` in
`apps/ascend-ocr/src/service/ocr_service.py`, `JobRunner.cancel`, `JobRunner._take_one_turn` and
`JobRunner._read_document` in `apps/ascend-ocr/src/service/job_runner.py`, `JobStore.start` in
`apps/ascend-ocr/src/service/job_store.py`, the job queue gauges in
`apps/ascend-ocr/src/observability/metrics.py`, and the lifespan in `apps/ascend-ocr/src/main.py`. The tests:
`TestReadyEndpoint::test_ready_reports_the_queue_only_through_the_job_counters` and
`test_a_cancel_answers_without_waiting_for_the_worker_to_be_replaced` in `tests/api/rest/test_rest_endpoints.py`,
`TestCancellationReplacesTheWorker` in `tests/service/test_ocr_service.py`,
`test_shutdown_waits_for_a_worker_replacement_before_stopping_the_pool` in `tests/test_main.py`,
`TestCancellation::test_the_next_document_waits_for_the_worker_a_cancel_is_replacing` in
`tests/service/test_job_runner.py`,
`TestDispatchOcrRequest::test_a_dispatch_across_a_pool_rebuild_releases_the_gate_it_acquired` in
`tests/service/test_ocr_service.py`,
`TestJobMetrics::test_waiting_work_is_reported_only_by_the_job_queue_gauges` and
`TestJobMetrics::test_the_wait_is_measured_only_in_the_job_queue` in `tests/observability/test_metrics.py`,
`TestCancellation::test_a_cancel_while_the_submitted_bytes_are_read_is_kept` in `tests/service/test_job_runner.py`,
and the three `test_starting_*` tests in `TestTerminalWriters` in `tests/service/test_job_store.py`.
