# REST insert and search round-trip: e2e test

## What this verifies

- `POST /api/v1/memory/insert` for `user_id="frostyMemoryInsertSearchTest"` with text `"My favourite city is Reykjavik"`
  returns HTTP 200 and a list response (mem0 returns a list of memory operations performed; the list is non-empty
  when a memory was stored).
- `GET /api/v1/memory/search?user_id=frostyMemoryInsertSearchTest&query=Where+do+I+like+to+live%3F` returns HTTP 200
  and a non-empty JSON array.
- At least one entry in the search result has a `memory` field whose string value contains the substring
  `"Reykjavik"` (case-insensitive). This proves the round-trip — insert → embed → store → semantic search →
  retrieve — works against the configured embedding backend and Qdrant.
- The retrieved memory belongs to the test's `user_id` (mem0 returns `user_id="frostyMemoryInsertSearchTest"`
  alongside each memory; user-scope is observed at retrieval time).

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

Wipe the dedicated test user so the search at the end of the run reflects only what this test inserts.

```powershell
curl -fsS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyMemoryInsertSearchTest"
```

Expect HTTP 200 with `{"status":"success", ...}`.

## Run

Two Bruno requests in sequence.

```powershell
cd docs/api/request/AscendAI
```

**Step 1.** Insert the canary memory.

```powershell
bru run "memory/testing/insert-reykjavik.yml" --env ascend-local
```

**Step 2.** Search with a semantically related query.

```powershell
bru run "memory/testing/search-reykjavik.yml" --env ascend-local
```

## Expected

`insert-reykjavik.yml` returns HTTP 200. The response body is a JSON array (mem0's `add` return shape). The array
is non-empty — at least one entry has a string `id` field. (The exact size depends on whether `MEM0_INFER_MEMORY`
is enabled; either way, ≥ 1 entry is returned when the insert succeeds.)

`search-reykjavik.yml` returns HTTP 200. The response body is a JSON array. The array is non-empty, and:

- At least one entry has a `memory` field (string) whose value contains the substring `"Reykjavik"`
  (case-insensitive).
- That entry's `user_id` field equals `"frostyMemoryInsertSearchTest"` (mem0 echoes the partition).
- That entry's `score` field is a finite number > 0 (semantic-search similarity score).

## Fixtures

None.
