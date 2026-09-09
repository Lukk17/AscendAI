# Semantic memory: run tasks template

Spec: [../4-semantic-memory-test.md](../4-semantic-memory-test.md)

Copy this file to `runs/<UTC-timestamp>_4-semantic-memory-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version) - 3.4.0
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] AscendMemory `/health` returns HTTP 200 with `{"status":"ok"}`
- [x] Qdrant `/healthz` returns HTTP 200 (`healthz check passed`)
- [x] Redis responds to `PING` with `PONG`
- [x] Postgres responds to `SELECT 1` with a row

### Reset state

- [x] Cleared Redis `chat:frostySemanticMemoryTest` key
- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostySemanticMemoryTest'` (found 2 leftover rows from a prior run)
- [x] Wiped Qdrant `ascend_memory_*` points where `user_id = 'frostySemanticMemoryTest'`

### Run

- [x] Step 1: sent `memory-test-save.yml` and waited for HTTP 200
- [x] Step 2: re-cleared Redis `chat:frostySemanticMemoryTest` and Postgres `chat_history` for frostySemanticMemoryTest
- [x] Step 3: sent `memory-test-retrieve.yml` and waited for HTTP 200

### Expected

- [x] After step 1: HTTP 200
- [x] After step 1: Qdrant scroll filtered by `user_id=frostySemanticMemoryTest` returns >= 1 point (returned 2 points)
- [x] After step 1: at least one Qdrant point's payload contains both `Luke` and `software engineer` (one point payload.data = "User's name is Luke", another = "User is a software engineer"; together both facts are covered, and the retrieval turn's response combined them correctly)
- [x] After step 3: HTTP 200
- [x] After step 3: Response `content` contains `Luke`
- [x] After step 3: Response `content` contains `software engineer`
- [x] After step 3: Response `content` is NOT a refusal like "I don't know your name"

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostySemanticMemoryTest` returned `{"status":"success","message":"All memories wiped for user frostySemanticMemoryTest"}`
- [x] Qdrant scroll on `ascend_memory_1536` filtered by `user_id=frostySemanticMemoryTest` returned an empty `points` array
- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostySemanticMemoryTest'`
- [x] Deleted Redis key `chat:frostySemanticMemoryTest`
- [x] Deleted Redis key `user:frostySemanticMemoryTest:instructions`

### Verdict

- [x] Verdict: PASS

## Result summary

Both Bruno steps passed all assertions. After step 1 (`memory-test-save.yml`, HTTP 200), waiting 5 seconds and scrolling Qdrant's `ascend_memory_1536` collection filtered by `user_id=frostySemanticMemoryTest` returned exactly 2 points, one with `payload.data = "User's name is Luke"` and one with `payload.data = "User is a software engineer"`, confirming the background extractor wrote both facts asynchronously. Chat history and the Redis chat cache were cleared again between save and recall so nothing could leak from short-term memory. After step 3 (`memory-test-retrieve.yml`, HTTP 200), the response body's `content` field read "Your name is **Luke**, and you're a **software engineer**.", containing both facts and no refusal phrase, proving the recall came from semantic memory via AscendMemory/Qdrant rather than chat history. Post-run cleanup wiped the memory points (confirmed via a follow-up empty scroll) and dropped the Postgres and Redis state.

Provider: minimax. Model: MiniMax-M2.7 for both calls.

Token usage, call 1 (`memory-test-save.yml`, from `metadata.usage`):
Input (prompt) tokens: 198
Output (completion) tokens: 60
Total tokens: 258
`nativeUsage.cache_read_input_tokens`: 3131, `nativeUsage.cache_creation_input_tokens`: 0 (provider-side cache read on the system-prompt prefix, incidental to this test, not asserted).

Token usage, call 2 (`memory-test-retrieve.yml`, from `metadata.usage`):
Input (prompt) tokens: 3347
Output (completion) tokens: 77
Total tokens: 3424
No `cache_read_input_tokens` / `cache_creation_input_tokens` fields present in this call's `nativeUsage`.

Input tokens: 198 (call 1) + 3347 (call 2) = 3545 total

Output tokens: 60 (call 1) + 77 (call 2) = 137 total

Start (UTC): 2026-09-03T19:21:44Z

End (UTC): 2026-09-03T19:22:44Z

Duration: 00:01:00

---

## Additional tasks I did

Wrote both Bruno run outputs to scratch JSON files (`test4-save.json`, `test4-retrieve.json`) to inspect the full response bodies, including `metadata.usage` and `metadata.usage.nativeUsage`, for token accounting on both paid calls. Outside the spec's own assertions but needed for the sweep's per-call token-accounting requirement.
