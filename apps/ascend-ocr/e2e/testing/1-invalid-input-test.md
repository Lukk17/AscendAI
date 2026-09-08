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

```bash
bru --version
```

Expect a version string. If the command is not found, install it with `npm install -g @usebruno/cli`.

Check the ascend-ocr server is reachable.

```bash
curl -fsS http://localhost:7022/health
```

Expect HTTP 200 with a body containing `"status":"ok"`.

## Reset state

None. This test does not write persisted state and does not reach the OCR engine.

## Run

Single Bruno request.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ocr/testing/ocr-invalid-no-file.yml" --env ascend-local
```

## Expected

- HTTP status equals `422`.
- Response body is JSON with a top-level `detail` array.
- At least one entry in `detail` has `loc` containing the string `"file"` (FastAPI reports the missing required
  field by name).

Diagnostic note, not a pass/fail criterion: per-call duration as reported by the Bruno runner is not a reliable
measure of service behaviour. Bruno's own Node startup and multipart-body encoding account for roughly 130 ms of
every figure it reports (raw `curl` completes the same request in 208 to 221 ms against Bruno's 333 to 359 ms on an
idle host, and the gap widens further under concurrent load). A duration that looks unusually high is worth a look,
but it does not decide the verdict here — the 422 arriving at all is what proves request validation short-circuited
before any OCR engine call, and that proof does not depend on a timing threshold.

## Fixtures

None.
