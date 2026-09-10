# Semantic memory: run tasks template

Spec: [4-semantic-memory-test.md](4-semantic-memory-test.md)

Copy this file to `runs/<UTC-timestamp>_4-semantic-memory-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version)
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] AscendMemory `/health` returns HTTP 200 with `{"status":"ok"}`
- [x] Qdrant `/healthz` returns HTTP 200
- [x] Redis responds to `PING` with `PONG`
- [x] Postgres responds to `SELECT 1` with a row

### Reset state

- [x] Cleared Redis `chat:frostySemanticMemoryTest` key
- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostySemanticMemoryTest'`
- [x] Wiped Qdrant `ascend_memory_*` points where `user_id = 'frostySemanticMemoryTest'`

### Run

- [x] Step 1: sent `memory-test-save.yml` and waited for HTTP 200
- [x] Step 2: re-cleared Redis `chat:frostySemanticMemoryTest` and Postgres `chat_history` for frostySemanticMemoryTest
- [x] Step 3: sent `memory-test-retrieve.yml` and waited for HTTP 200

### Expected

- [x] After step 1: HTTP 200
- [x] After step 1: Qdrant scroll filtered by `user_id=frostySemanticMemoryTest` returns >= 1 point
- [x] After step 1: at least one Qdrant point's payload contains both `Luke` and `software engineer`
- [x] After step 3: HTTP 200
- [x] After step 3: Response `content` contains `Luke`
- [x] After step 3: Response `content` contains `software engineer`
- [x] After step 3: Response `content` is NOT a refusal like "I don't know your name"

### Verdict

- [x] Verdict: PASS

## Result summary

All seven Expected assertions passed. Step 1 (memory-test-save.yml) returned HTTP 200 in 2502 ms. After the 5-second async wait, a Qdrant scroll on `ascend_memory_1536` filtered by `user_id=frostySemanticMemoryTest` returned 2 points: one with payload `data="User's name is Luke"` and one with `data="User is a software engineer"`, satisfying both the count (>=1) and content (Luke + software engineer) assertions. Chat history was then wiped from both Redis and Postgres. Step 3 (memory-test-retrieve.yml) returned HTTP 200 in 1888 ms with response body `content="Your name is Luke, and you're a software engineer."` — containing both `Luke` and `software engineer`, and constituting a confident recall rather than any refusal. The semantic memory pipeline successfully extracted, stored, and retrieved the user fact across an independent turn with no access to chat history.

Input tokens:

Output tokens:

Start (UTC): 2026-06-01T18:37:19

End (UTC): 2026-06-01T18:40:55

Duration: 00:03:36

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
