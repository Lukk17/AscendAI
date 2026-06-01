# Readiness endpoint: e2e test

## What this verifies

- `GET /ready` returns HTTP 200 with `{"status":"ready","engine_warm":true,"version":"..."}` once the lifespan
  warm-up has completed.
- `/ready` is distinct from `/health` per ADR-004: liveness vs readiness.

## Prerequisites

Bruno CLI installed; PaddleOCR `/health` returns HTTP 200.

```powershell
bru --version
```

```powershell
curl -fsS http://localhost:7022/health
```

## Reset state

None.

## Run

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "paddle-ocr/testing/ready.yml" --env ascend-local
```

## Expected

- HTTP 200.
- Body `status` equals `"ready"`.
- Body `engine_warm` equals `true`.
- Body `version` is a non-empty string.
