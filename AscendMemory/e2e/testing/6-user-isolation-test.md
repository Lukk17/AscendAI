# Cross-user memory isolation: e2e test

## What this verifies

- `POST /api/v1/memory/insert` for `user_id="frostyMemoryIsolationUserA"` with the canary text
  `"My secret favourite city is Tromsø"` returns HTTP 200 and stores the memory under user A's
  partition in Qdrant.
- `GET /api/v1/memory/search` issued for a **different** `user_id="frostyMemoryIsolationUserB"`
  with a semantically related query returns HTTP 200 and a response body that contains **no entry**
  whose `user_id` is `"frostyMemoryIsolationUserA"` and **no entry** whose `memory` field contains
  the canary substring `"Tromsø"` (case-insensitive).
- Proves that mem0's user-scope filter prevents memories written by user A from appearing in user
  B's search results — cross-user memory leakage does not occur.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string.

Check the AscendMemory server is reachable and ready.

```powershell
curl -fsS http://localhost:7020/health
```

Expect HTTP 200 with `{"status":"ok"}`.

Check Qdrant is reachable.

```powershell
curl -fsS http://localhost:6333/readyz
```

Expect HTTP 200.

## Reset state

Wipe user A so the test is not contaminated by canary data from a previous run. User B is never
written to by this test and needs no wipe.

```powershell
curl -fsS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyMemoryIsolationUserA"
```

Expect HTTP 200 with `{"status":"success", ...}`.

## Run

Two Bruno requests in sequence. Step 2 must not start until step 1 has returned HTTP 200.

```powershell
cd docs/api/request/AscendAI
```

**Step 1.** Insert the canary memory for user A.

```powershell
bru run "memory/testing/insert-isolation-user-a.yml" --env ascend-local
```

**Step 2.** Search for related content as a completely different user B.

```powershell
bru run "memory/testing/search-isolation-user-b.yml" --env ascend-local
```

## Post-run cleanup

Wipe user A so its canary memory does not survive into the next run. User B is never written to by this test, so
it needs no wipe. The section sits next to `Run` because that is where the state it names is created, but the
runner executes it last, after the `Expected` assertions below have been checked against the live state.

```powershell
curl -fsS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyMemoryIsolationUserA"
```

Expect HTTP 200 with `{"status":"success", ...}`.

## Expected

`insert-isolation-user-a.yml` returns HTTP 200. The response body is a JSON array (mem0's `add`
return shape). The array is non-empty — at least one entry has a string `id` field.

`search-isolation-user-b.yml` returns HTTP 200. The response body is a JSON array (possibly empty).
The isolation invariant holds when **all** of the following are true:

- No entry has `user_id` equal to `"frostyMemoryIsolationUserA"`.
- No entry has a `memory` field (string) containing the substring `"Tromsø"` (case-insensitive).

An empty array `[]` satisfies the invariant and is the most common result because user B has no
memories seeded; mem0 simply returns nothing for an unknown user rather than falling back to a
global search.

A non-empty array is acceptable only if every entry belongs to `"frostyMemoryIsolationUserB"` and
contains none of user A's canary text.

## Fixtures

None.
