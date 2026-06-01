# Invalid input rejection: e2e test

## What this verifies

- `POST /api/v1/memory/insert` with a JSON body that omits the required `user_id` field returns HTTP 422 (FastAPI's
  default request-validation status) before any mem0 / Qdrant call.
- The response body is a FastAPI validation envelope: a JSON object with a `detail` array whose entries reference the
  missing field by location and name (`loc` contains `"user_id"`).
- **No Qdrant write occurs.** The collection state for any `user_id` is unchanged by this test.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string. If the command is not found, install it with `npm install -g @usebruno/cli`.

Check the AscendMemory server is reachable and ready.

```powershell
curl -fsS http://localhost:7020/health
```

Expect HTTP 200 with `{"status":"ok"}`. HTTP 503 with `{"status":"starting"}` means the warmup is still running —
wait and retry.

## Reset state

None. This test does not reach mem0; no `user_id` is touched in Qdrant.

## Run

One Bruno request.

```powershell
cd docs/api/request/AscendAI
```

**Step 1.** Send the malformed insert request.

```powershell
bru run "memory/testing/invalid-missing-user.yml" --env ascend-local
```

## Expected

The call returns HTTP 422.

The response body matches:

- The body is a JSON object containing a `detail` array.
- At least one element of `detail` references `"user_id"` in its `loc` array (FastAPI / Pydantic v2 missing-field
  envelope).
- The element's `type` is `"missing"` (Pydantic v2 missing-field code).

A response latency over ~200 ms suggests the request actually reached mem0 / Qdrant; investigate before declaring
PASS.

## Fixtures

None.
