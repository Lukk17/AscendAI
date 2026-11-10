# Readiness endpoint: e2e test

## What this verifies

- `GET /ready` returns HTTP 200 with `{"status":"ready",...}` once the `engine`, `worker_pool` and `jobs`
  probes all report `ok`.
- The answer carries a `checks` object naming each probe: `checks.engine` reports `warm`, `checks.worker_pool`
  reports `accepting_work`, and `checks.jobs` reports the `queued` and `running` document counts, so an operator
  can tell a busy service from a stuck one without reading logs.
- On an idle service both job counts are zero. They are additive and never change `status`: a queue with work in it
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
- Body `service` equals `"ascend-ocr"` and body `version` is a non-empty string.
- `checks.engine.status` equals `"ok"` and `checks.engine` reports `warm` true.
- `checks.worker_pool.status` equals `"ok"` and `checks.worker_pool` reports `accepting_work` true.
- `checks.jobs.status` equals `"ok"`, and on an idle service it reports zero `queued` and zero `running`.

Spec 14 asserts the same two counters while work is actually in flight.
