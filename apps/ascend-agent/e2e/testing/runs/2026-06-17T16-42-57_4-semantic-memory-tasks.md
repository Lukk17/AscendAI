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
- [x] After step 1: Qdrant scroll filtered by `user_id=frostySemanticMemoryTest` returns ≥ 1 point
- [x] After step 1: at least one Qdrant point's payload contains both `Luke` and `software engineer`
- [x] After step 3: HTTP 200
- [x] After step 3: Response `content` contains `Luke`
- [x] After step 3: Response `content` contains `software engineer`
- [x] After step 3: Response `content` is NOT a refusal like "I don't know your name"

### Verdict

- [x] Verdict: PASS

## Result summary

All seven assertions passed. Step 1 (save turn) returned HTTP 200; the agent responded acknowledging Luke by name. After the 5-second async write delay, a Qdrant scroll on `ascend_memory_1536` filtered by `user_id=frostySemanticMemoryTest` returned 4 points — two with `"data": "User's name is Luke"` and two with `"data": "User is a software engineer"`, satisfying the ≥ 1 point and Luke+software-engineer payload assertions. After clearing both Redis and Postgres chat history (Step 2), the recall turn (Step 3) returned HTTP 200 with `content`: "Your name is Luke, and you're a software engineer." — containing both `Luke` and `software engineer` and constituting no refusal. Because all chat history was wiped before the recall, the response can only have derived the facts from semantic memory via AscendMemory + Qdrant.

Input tokens:

Output tokens:

Start (UTC): 2026-06-17T16:42:57Z

End (UTC): 2026-06-17T16:45:23Z

Duration: 00:02:26

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
