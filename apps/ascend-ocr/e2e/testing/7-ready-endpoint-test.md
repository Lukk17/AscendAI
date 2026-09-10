# Readiness endpoint: e2e test

## What this verifies

- `GET /ready` returns HTTP 200 with `{"status":"ready","engine_warm":true,"version":"..."}` once the lifespan
  warm-up has completed.
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
- Body `version` is a non-empty string.
