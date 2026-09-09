# Semantic memory: run tasks template

Spec: [4-semantic-memory-test.md](4-semantic-memory-test.md)

Copy this file to `runs/<UTC-timestamp>_4-semantic-memory-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version) — 3.4.0
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] AscendMemory `/health` returns HTTP 200 with `{"status":"ok"}`
- [x] Qdrant `/healthz` returns HTTP 200
- [x] Redis responds to `PING` with `PONG`
- [x] Postgres responds to `SELECT 1` with a row

### Reset state

- [x] Cleared Redis `chat:frostySemanticMemoryTest` key — returned 1 (key deleted)
- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostySemanticMemoryTest'` — DELETE 4
- [x] Wiped Qdrant `ascend_memory_*` points where `user_id = 'frostySemanticMemoryTest'` — acknowledged

### Run

- [x] Step 1: sent `memory-test-save.yml` and waited for HTTP 200
- [x] Step 2: re-cleared Redis `chat:frostySemanticMemoryTest` (returned 1) and Postgres `chat_history` for frostySemanticMemoryTest (DELETE 2)
- [x] Step 3: sent `memory-test-retrieve.yml` and waited for HTTP 200

### Expected

- [x] After step 1: HTTP 200
- [x] After step 1: Qdrant scroll filtered by `user_id=frostySemanticMemoryTest` returns ≥ 1 point — returned 2 points
- [x] After step 1: at least one Qdrant point's payload contains both `Luke` and `software engineer` — point 1: "User's name is Luke"; point 2: "User is a software engineer"
- [x] After step 3: HTTP 200
- [x] After step 3: Response `content` contains `Luke` — "Your name is Luke, and you're a software engineer."
- [x] After step 3: Response `content` contains `software engineer` — confirmed
- [x] After step 3: Response `content` is NOT a refusal like "I don't know your name"

### Verdict

- [x] Verdict: PASS

## Result summary

HTTP 200 on both steps. Save turn: 3.1s. Qdrant scroll after 5s: 2 points written — "User's name is Luke" and "User is a software engineer". After full Redis+Postgres wipe, recall response: "Your name is Luke, and you're a software engineer." — both required terms present, sourced from semantic memory only. No refusal.

Input tokens: 0 (metadata not returned)

Output tokens: 0 (metadata not returned)

Start (UTC): 2026-05-23T23:16:55Z

End (UTC): 2026-05-23T23:18:18Z

Duration: 00:01:23

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
