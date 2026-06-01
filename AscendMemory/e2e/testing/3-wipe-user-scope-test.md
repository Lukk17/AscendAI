# Wipe user-scope isolation: e2e test

## What this verifies

- Wiping `user_id=frostyMemoryWipeAlpha` removes Alpha's memories but leaves
  `user_id=frostyMemoryWipeBeta`'s memories intact.
- After the wipe, `GET /api/v1/memory/search` for Alpha returns an empty array (or an array with no entries whose
  `memory` contains the seed phrase).
- After the wipe, `GET /api/v1/memory/search` for Beta still returns at least one entry whose `memory` field
  contains Beta's seed phrase (`"Madrid"`).
- Confirms `POST /api/v1/memory/wipe?user_id=X` is strictly scoped to the supplied partition and never bleeds
  across users.

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

Wipe both test users so the run starts from a known-empty state for both partitions.

```powershell
curl -fsS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyMemoryWipeAlpha"
```

```powershell
curl -fsS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyMemoryWipeBeta"
```

Each returns HTTP 200 with `{"status":"success", ...}`.

## Run

Four Bruno requests in sequence. Each must complete before the next begins.

```powershell
cd docs/api/request/AscendAI
```

**Step 1.** Seed Alpha with a distinctive memory.

```powershell
bru run "memory/testing/insert-alpha.yml" --env ascend-local
```

**Step 2.** Seed Beta with a different distinctive memory.

```powershell
bru run "memory/testing/insert-beta.yml" --env ascend-local
```

**Step 3.** Wipe Alpha only.

```powershell
bru run "memory/testing/wipe-alpha.yml" --env ascend-local
```

**Step 4.** Search both users and inspect the results.

```powershell
bru run "memory/testing/search-alpha.yml" --env ascend-local
```

```powershell
bru run "memory/testing/search-beta.yml" --env ascend-local
```

## Expected

All five calls return HTTP 200.

`insert-alpha.yml` and `insert-beta.yml` each return a non-empty JSON array (≥ 1 entry with a string `id`).

`wipe-alpha.yml` returns a JSON object with `status="success"` and a `message` referencing
`"frostyMemoryWipeAlpha"`.

`search-alpha.yml` returns a JSON array containing no entry whose `memory` field contains the substring
`"Lisbon"` (case-insensitive). An empty array `[]` satisfies this; a non-empty array also satisfies as long as
none of the entries reference Lisbon. (mem0's semantic search may surface low-score neighbours even from other
users, but per its user-scope filter no Alpha-owned Lisbon memory may appear.)

`search-beta.yml` returns a non-empty JSON array. At least one entry has:

- `memory` field containing `"Madrid"` (case-insensitive).
- `user_id` equal to `"frostyMemoryWipeBeta"`.
- `score` a finite number > 0.

## Fixtures

None.
