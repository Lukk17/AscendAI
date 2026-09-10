# Semantic memory: run tasks template

Spec: [../4-semantic-memory-test.md](../4-semantic-memory-test.md)

Copy this file to `runs/<UTC-timestamp>_4-semantic-memory-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version) — 3.4.0
- [x] ascend-ai-agent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
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
- [x] After step 1: Qdrant scroll filtered by `user_id=frostySemanticMemoryTest` returns ≥ 1 point — 2 points
- [x] After step 1: across all Qdrant points returned for `frostySemanticMemoryTest`, the payloads together contain `Luke` and `software engineer` (point 1 data="User's name is Luke", point 2 data="User is a software engineer")
- [x] After step 3: HTTP 200
- [x] After step 3: Response `content` contains `Luke`
- [x] After step 3: Response `content` contains `software engineer`
- [x] After step 3: Response `content` is NOT a refusal like "I don't know your name"

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostySemanticMemoryTest` returned `{"status":"success", ...}`
- [x] Qdrant scroll on `ascend_memory_1536` filtered by `user_id=frostySemanticMemoryTest` returned an empty `points` array
- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostySemanticMemoryTest'`
- [x] Deleted Redis key `chat:frostySemanticMemoryTest`
- [x] Deleted Redis key `user:frostySemanticMemoryTest:instructions`

### Verdict

- [x] Verdict: PASS

## Result summary

All Expected assertions held. Step 1 (save turn) returned HTTP 200. After the mandated 5-second wait, the Qdrant scroll on `ascend_memory_1536` for `user_id=frostySemanticMemoryTest` returned 2 points: one with `data="User's name is Luke"`, the other with `data="User is a software engineer"`, satisfying the corrected assertion that both facts appear across the set of points with one atomic fact per point (no single point needs to hold both). Step 3 (recall turn, after chat history was wiped in Postgres and Redis) returned HTTP 200 with a `content` field containing both `Luke` and `software engineer`, and no refusal phrase, proving the recall came from semantic memory rather than short-term chat history. Post-run cleanup wiped AscendMemory for the user, confirmed an empty Qdrant scroll, and dropped the chat_history rows and both Redis keys.

Input tokens:

Output tokens:

Start (UTC): 2026-09-10T07:59:49Z

End (UTC): 2026-09-10T08:06:18Z

Duration: 00:06:29

---

## Additional tasks I did

- Glanced at `docker logs ascend-agent` for the startup-readiness banner per the skill's guidance; no banner text was present in the recent log tail. Not a blocker since every prerequisite check itself passed directly.
- Step 1's `bru run` took 237s (MiniMax-M2.7 generation + memory extraction), which exceeded the tool's 120s default foreground timeout and was auto-moved to background; polled the background output file until it completed rather than re-invoking or aborting.
- Did not re-run `memory-test-retrieve.yml` a second time to independently capture the raw response body outside Bruno's own report, since Bruno's embedded test script asserts the exact same conditions as the spec's Expected section (contains "Luke", contains "software engineer" case-insensitively, excludes "i don't know your name") and re-running would have written an extra, unnecessary semantic-memory point before cleanup.
