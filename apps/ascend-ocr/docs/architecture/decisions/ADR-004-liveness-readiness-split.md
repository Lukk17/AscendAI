# ADR-004: Liveness (`/health`) and readiness (`/ready`) endpoints serve different audiences

## Status

Accepted — 2026-05-31. Amended — 2026-09-07: readiness gains a second condition (see "Amendment" below). Amended
again — 2026-09-07: the overrun signal behind that condition is fixed for more than one worker (see "Amendment
(2026-09-07): the overrun signal at more than one worker" below).

## Context

A single `/health` endpoint that returns "I'm alive" satisfies Docker's healthcheck — the container reports up, the orchestrator stops sending kill signals. It does *not* satisfy a load balancer that wants to know whether the process can handle real traffic, because ascend-ocr's first OCR call after a cold start has a 5–15 s warm-up latency while PaddlePaddle materialises the model. During warm-up, the process is alive but useless to the caller.

The previous `/health` endpoint returned `{"status": "ok", "version": "..."}` unconditionally — before the engine was warm, before lifespan even ran. The Docker healthcheck would mark the container healthy, and the load balancer would route traffic in, only for the first request to hang for 10 seconds while the engine loaded.

## Decision

Split the concern into two endpoints with different semantics:

### `/health` — liveness

Always returns 200 OK as long as the FastAPI process is running. Returns `{"status": "ok", "version": "..."}`. No dependency probes, no engine checks. This is what Docker's `HEALTHCHECK` and Kubernetes' `livenessProbe` should hit.

The only failure mode is "the process is wedged so badly it can't respond at all" — at that point the orchestrator should restart the container, and `/health` is the signal for that.

### `/ready` — readiness

Returns `{"status": "ready" | "not-ready", "version": "...", "engine_warm": bool}`. The `engine_warm` flag is `true` iff `is_engine_warm(settings.DEFAULT_LANGUAGE)` (`src/observability/metrics.py`) finds a recorded `ENGINE_WARMUP_DURATION_SECONDS` observation for that language. Returns 200 OK in both cases; consumers decide whether to route traffic based on `status`.

This is what a Kubernetes `readinessProbe` should hit. While `engine_warm=false`, the load balancer removes the pod from the rotation. Once the warm-up completes, the next probe sees `ready` and the pod gets traffic.

The engine actually warms inside the OCR worker process (a separate `ProcessPoolExecutor` process, see `start_worker_pool` in `src/service/ocr_service.py`), not in the main process that answers `/ready`. `/ready` cannot read that worker's in-memory state directly, so it crosses the process boundary the same way the engine-cache eviction counter already does: the worker's `warm_up_engine` call observes `ENGINE_WARMUP_DURATION_SECONDS` into its own file under `PROMETHEUS_MULTIPROC_DIR`, and `is_engine_warm` reads that file back via `MultiProcessCollector` instead of polling the worker or triggering a warm-up itself. `observe()` only runs after the engine builds successfully, so a warm-up that is still pending or that failed both read back as `engine_warm=false`, with no separate failure flag needed.

### Why not a synthetic OCR probe in `/ready`

The first considered option was to do a tiny synthetic OCR run on a 1×1 bundled PNG in `/ready`. Rejected because:

- It costs ~50–100 ms per probe. Kubernetes default probe interval is 10 s; that's a real CPU hit for a probe.
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
the body, exactly as the original decision specifies — busy-but-in-budget stays `ready`, because a queued request
will still be served, and consumers reading `status` are unaffected by the two new fields.

## Amendment (2026-09-07): the overrun signal at more than one worker

The four-condition amendment above was written and tested against `OCR_WORKER_COUNT=1`, where at most one job is
ever in flight. Making `OCR_WORKER_COUNT` a genuine runtime setting rather than a fixed constant exposed that the
"in-flight job past its own budget" condition had been implemented as a single module-level variable holding one
deadline. With more than one worker, more than one job can be in flight at once, and a shared variable cannot hold
more than one job's deadline: a second job starting overwrites the first job's entry, and either job's own `finally`
clears whichever value is currently stored, regardless of which job it belonged to. The practical failure is
`is_job_overrunning()` (and therefore `accepting_work`) silently going blind to a genuinely stuck job whenever a
second, unrelated job starts or finishes around it — the exact readiness signal this ADR exists to keep honest.

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
rebuild — proven against the real stdlib: a two-worker pool with one fast job and one 8-second job took 7.94 s to
shut down, not the fast job's own time, and a synchronous call to that shutdown from inside a coroutine blocks the
coroutine's own event loop thread for the whole span (also proven directly: an unrelated concurrent coroutine's own
0.05 s heartbeat produced zero ticks until a blocking call inside the same rebuild path returned). At
`OCR_WORKER_COUNT=1` this bound is roughly one page's own remaining inference time, since there is never a second job
to wait on. At more than one worker it is bounded by nothing shorter than another worker's own full budget, so one
stuck job could freeze the *entire* service — not only OCR dispatch, every coroutine on the same event loop, including
unrelated admission waits and MCP request handling — for as long as an entirely healthy, unrelated job on a different
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
warmed at startup — `ProcessPoolExecutor` spawns the rest lazily, only once real concurrent traffic needs them, each
paying its own warm-up cost (seconds) inside that caller's own request. Fixed by submitting one warm-up task per
configured worker before collecting any result, forcing one OS process per worker up front. Proven live, not only in
the test suite: starting the pool with `OCR_WORKER_COUNT=1` spawned exactly 1 live worker process; with
`OCR_WORKER_COUNT=2`, exactly 2, and the startup banner's own arithmetic scaled from `~14201 MiB` to `~28402 MiB`
accordingly.

## Consequences

### Why this shape

- **No traffic during cold start.** The load balancer waits for `engine_warm`. Cold-start latency is moved from the caller to the lifecycle layer where it belongs.
- **Clear escalation path.** If `/health` fails, the process is broken — restart. If `/ready` fails, the process is healthy but not yet useful — wait. Different signals, different responses.
- **Cheap probes.** Both endpoints are O(1) lookups; both can be probed at high frequency without measurable cost.

### Trade-offs

- **Two endpoints to document.** Operators reading the runbook see two probes instead of one. The startup banner now prints both URLs so it's hard to miss.
- **Readiness signal is binary.** If the default language warms up but `pl` does not (because ascend-ocr's model server is flaky for that specific lang), `/ready` is `ready` but a `lang=pl` request still has to do a lazy warm-up. Acceptable; the cold-start window is rare and the alternative (per-language readiness) is significant configuration burden for low value.
- **No Kubernetes startup probe yet.** For long cold starts (>30 s), Kubernetes' `startupProbe` is the better fit than fighting `readinessProbe`'s `initialDelaySeconds`. Defer until we deploy to k8s.

### Alternatives considered

- **Single `/health` that also probes the engine.** Rejected — conflates "restart me" with "send traffic later." Causes spurious container restarts during cold start.
- **`/health?check=engine` query parameter.** Rejected — same logical endpoint with two behaviours is harder to reason about than two endpoints with one behaviour each.
- **Synthetic OCR probe.** Rejected — cost without signal, see above.

## Related

- `apps/ascend-ocr/src/main.py` — `health_check`, `readiness_check`.
- `apps/ascend-ocr/src/model/ocr_models.py` — `HealthResponse`, `ReadinessResponse` (`accepting_work`, `queue_depth`).
- `apps/ascend-ocr/src/observability/metrics.py` — `is_engine_warm`, the multiprocess-file readiness check.
- `apps/ascend-ocr/src/service/ocr_service.py` — `start_worker_pool`, `_warm_worker_engine`, `is_accepting_work`,
  `is_pool_usable`, `is_rebuild_in_progress`, `is_job_overrunning`, `_active_deadlines`, `_rebuild_pool`, the
  `BrokenProcessPool` handling.
- `apps/ascend-ocr/src/config/startup_banner.py` — emits both URLs and the per-worker memory arithmetic at startup.
- `apps/ascend-ocr/tests/api/rest/test_rest_endpoints.py` — `TestReadyEndpoint`, `test_unexpected_dispatch_exception_returns_500_not_a_crash`.
- `apps/ascend-ocr/tests/service/test_ocr_service.py` — `TestPoolHealthSignals`, `TestRebuildPool`,
  `TestWorkerPoolLifecycle::test_start_worker_pool_warms_every_configured_worker`,
  `TestDispatchOcrRequest::test_concurrent_jobs_track_independent_overrun_deadlines`.
- `apps/ascend-ocr/tests/observability/test_metrics.py` — `TestIsEngineWarm`.
- `apps/ascend-ocr/Dockerfile` — `HEALTHCHECK` points at `/health`, not `/ready`.
- `openspec/changes/stop-ocr-getting-stuck-on-large-jobs/` — the change that added the second readiness condition and
  made `OCR_WORKER_COUNT` a real runtime setting, which is what exposed the defects the second amendment above fixes.
