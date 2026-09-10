# Invalid input rejection: e2e test

## What this verifies

- `POST /api/v1/memory/insert` with a JSON body that omits the required `user_id` field returns HTTP 422 (FastAPI's
  default request-validation status) before any mem0 / Qdrant call.
- The response body is a FastAPI validation envelope: a JSON object with a `detail` array whose entries reference the
  missing field by location and name (`loc` contains `"user_id"`).
- **No Qdrant write occurs.** The collection state for any `user_id` is unchanged by this test.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string. If the command is not found, install it with `npm install -g @usebruno/cli`.

Check the AscendMemory server is reachable and ready.

```bash
curl -fsS http://localhost:7020/health
```

Expect HTTP 200 with `{"status":"ok"}`. HTTP 503 with `{"status":"starting"}` means the warmup is still running —
wait and retry.

## Reset state

None. This test does not reach mem0; no `user_id` is touched in Qdrant.

## Run

Capture a Qdrant baseline, then send one Bruno request.

```bash
cd docs/api/request/AscendAI
```

**Step 1.** Record the current point count of the `ascend_memory_1536` collection (the collection the default
provider chain would eventually write to if this request ever reached mem0).

```bash
curl -fsS http://localhost:6333/collections/ascend_memory_1536
```

Note the `result.points_count` value as the baseline.

**Step 2.** Send the malformed insert request.

```bash
bru run "memory/testing/invalid-missing-user.yml" --env ascend-local
```

## Post-run cleanup

None. The request is rejected before it reaches mem0 / Qdrant, so no `user_id` is ever touched and there is nothing
to remove.

## Expected

The call returns HTTP 422.

The response body matches:

- The body is a JSON object containing a `detail` array.
- At least one element of `detail` references `"user_id"` in its `loc` array (FastAPI / Pydantic v2 missing-field
  envelope).
- The element's `type` is `"missing"` (Pydantic v2 missing-field code).

No backend call occurred. This is proven two ways, not by wall-clock latency. Container overhead on this stack sits
around 200-220 ms for any request, including a bodyless `/health` liveness probe. A latency threshold cannot
distinguish "validator short-circuited" from "reached mem0" and produces false alarms on every run:

- Structurally: `InsertRequest.user_id` in `src/api/rest/rest_endpoints.py` is a required Pydantic field with no
  default. FastAPI validates the request body against this model before the `insert_memory` handler function body
  ever executes, so a 422 response for a missing `user_id` is only reachable through a code path that never calls
  `get_memory_client` or `client.add`. mem0 and Qdrant cannot have been touched.
- Observably: `curl -fsS http://localhost:6333/collections/ascend_memory_1536` taken after the run reports the same
  `result.points_count` as the baseline captured in Run Step 1.

## Fixtures

None.
