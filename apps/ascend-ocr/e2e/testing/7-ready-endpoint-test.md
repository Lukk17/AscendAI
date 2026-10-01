# Readiness endpoint: e2e test

## What this verifies

- `GET /ready` returns HTTP 200 with `{"status":"ready","engine_warm":true,"version":"..."}` once the lifespan
  warm-up has completed.
- The answer also reports `accepting_work` and the two job counters `jobs_queued` and `jobs_running`, so an operator
  can tell a busy service from a stuck one without reading logs.
- The answer carries no `queue_depth` key. The two job counters replaced it, so its return would be a regression.
- On an idle service both job counters are zero. They are additive and never change `status`: a queue with work in it
  is busy, and busy stays ready (see the 2026-09-24 amendment to ADR-004).
- `/ready` is distinct from `/health` per ADR-004: liveness vs readiness.

## Prerequisites

Bruno CLI installed; ascend-ocr `/health` returns HTTP 200.

```bash
bru --version
```

```bash
curl -fsS http://localhost:7022/health
```

## Reset state

None.

## Run

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ocr/ready.yml" --env ascend-local
```

## Expected

- HTTP 200.
- Body `status` equals `"ready"`.
- Body `engine_warm` equals `true`.
- Body `accepting_work` equals `true`.
- Body `jobs_queued` equals `0` and `jobs_running` equals `0` on an idle service.
- Body has no `queue_depth` key.
- Body `version` is a non-empty string.

Spec 14 asserts the same two counters while work is actually in flight.
