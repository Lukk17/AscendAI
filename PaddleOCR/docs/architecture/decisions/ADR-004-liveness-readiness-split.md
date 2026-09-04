# ADR-004: Liveness (`/health`) and readiness (`/ready`) endpoints serve different audiences

## Status

Accepted — 2026-05-31

## Context

A single `/health` endpoint that returns "I'm alive" satisfies Docker's healthcheck — the container reports up, the orchestrator stops sending kill signals. It does *not* satisfy a load balancer that wants to know whether the process can handle real traffic, because PaddleOCR's first OCR call after a cold start has a 5–15 s warm-up latency while PaddlePaddle materialises the model. During warm-up, the process is alive but useless to the caller.

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

## Consequences

### Why this shape

- **No traffic during cold start.** The load balancer waits for `engine_warm`. Cold-start latency is moved from the caller to the lifecycle layer where it belongs.
- **Clear escalation path.** If `/health` fails, the process is broken — restart. If `/ready` fails, the process is healthy but not yet useful — wait. Different signals, different responses.
- **Cheap probes.** Both endpoints are O(1) lookups; both can be probed at high frequency without measurable cost.

### Trade-offs

- **Two endpoints to document.** Operators reading the runbook see two probes instead of one. The startup banner now prints both URLs so it's hard to miss.
- **Readiness signal is binary.** If the default language warms up but `pl` does not (because PaddleOCR's model server is flaky for that specific lang), `/ready` is `ready` but a `lang=pl` request still has to do a lazy warm-up. Acceptable; the cold-start window is rare and the alternative (per-language readiness) is significant configuration burden for low value.
- **No Kubernetes startup probe yet.** For long cold starts (>30 s), Kubernetes' `startupProbe` is the better fit than fighting `readinessProbe`'s `initialDelaySeconds`. Defer until we deploy to k8s.

### Alternatives considered

- **Single `/health` that also probes the engine.** Rejected — conflates "restart me" with "send traffic later." Causes spurious container restarts during cold start.
- **`/health?check=engine` query parameter.** Rejected — same logical endpoint with two behaviours is harder to reason about than two endpoints with one behaviour each.
- **Synthetic OCR probe.** Rejected — cost without signal, see above.

## Related

- `PaddleOCR/src/main.py` — `health_check`, `readiness_check`.
- `PaddleOCR/src/model/ocr_models.py` — `HealthResponse`, `ReadinessResponse`.
- `PaddleOCR/src/observability/metrics.py` — `is_engine_warm`, the multiprocess-file readiness check.
- `PaddleOCR/src/service/ocr_service.py` — `start_worker_pool`, `_warm_worker_engine`, the `BrokenProcessPool` handling.
- `PaddleOCR/src/config/startup_banner.py` — emits both URLs at startup.
- `PaddleOCR/tests/api/rest/test_rest_endpoints.py` — `TestReadyEndpoint`, `test_broken_worker_pool_returns_500_not_a_crash`.
- `PaddleOCR/tests/observability/test_metrics.py` — `TestIsEngineWarm`.
- `PaddleOCR/Dockerfile` — `HEALTHCHECK` points at `/health`, not `/ready`.
