# Invalid input rejection: e2e test

## What this verifies

- `POST /v1/ocr` without the required `file` multipart part is rejected by FastAPI's request-validation layer with
  HTTP 422 before any OCR engine call.
- The response body is the FastAPI validation envelope: a `detail` array with at least one entry whose `loc`
  references the missing `file` field.
- **No OCR engine invocation occurs.** The request short-circuits in FastAPI's dependency resolution; the steady-state
  duration is well under 100 ms.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string. If the command is not found, install it with `npm install -g @usebruno/cli`.

Check the PaddleOCR server is reachable.

```powershell
curl -fsS http://localhost:7022/health
```

Expect HTTP 200 with a body containing `"status":"ok"`.

## Reset state

None. This test does not write persisted state and does not reach the OCR engine.

## Run

Single Bruno request.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "paddle-ocr/testing/ocr-invalid-no-file.yml" --env ascend-local
```

## Expected

- HTTP status equals `422`.
- Response body is JSON with a top-level `detail` array.
- At least one entry in `detail` has `loc` containing the string `"file"` (FastAPI reports the missing required
  field by name).
- Per-call duration < 500 ms (proxy for "request validation short-circuited; no OCR engine call").

## Fixtures

None.
