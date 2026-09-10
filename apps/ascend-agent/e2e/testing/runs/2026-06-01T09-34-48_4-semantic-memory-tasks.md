# Semantic memory: run tasks template

Spec: [4-semantic-memory-test.md](../4-semantic-memory-test.md)

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

All seven Expected assertions passed. The save turn (Step 1) returned HTTP 200 in 9.3 s. After the prescribed 5-second async wait, a Qdrant scroll on `ascend_memory_1536` filtered by `user_id=frostySemanticMemoryTest` returned 2 points: one with `data="User's name is Luke"` and one with `data="User is a software engineer"` — both contain the required keywords. After the inter-turn reset (Redis DEL and Postgres DELETE deleted 1 key and 2 rows respectively, confirming state was actually present), the retrieve turn (Step 3) returned HTTP 200 in 4.2 s with `content="Your name is **Luke**, and you're a **software engineer**."` — confirming both keywords present and no refusal. Because chat history was wiped between turns, the recall could only have arrived via semantic memory, proving the full store-and-retrieve pipeline is functional.

Input tokens:

Output tokens:

Start (UTC): 2026-06-01T09:34:48Z

End (UTC): 2026-06-01T09:37:40Z

Duration: 00:02:52

---

## Additional tasks I did

- After Bruno returned HTTP 200 for Step 3, ran the retrieve call independently via curl to capture the raw JSON response body and verify the `content` field directly, since Bruno CLI does not print the response body in summary mode. The curl result confirmed: `{"content":"Your name is **Luke**, and you're a **software engineer**.",...}`.
