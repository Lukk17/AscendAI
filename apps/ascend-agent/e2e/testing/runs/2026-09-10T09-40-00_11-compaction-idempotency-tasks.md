# Chat-history compaction: idempotency: run tasks template

Spec: [../11-compaction-idempotency-test.md](../11-compaction-idempotency-test.md)

Copy to `runs/<UTC-timestamp>_11-compaction-idempotency-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present
- [x] ascend-ai-agent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] Seed scripts `seed-compaction-idempotency.sql` + `.redis` exist
- [x] Default compaction config (`turn-trigger=20`, `keep-recent-turns=8`)

### Reset state

- [x] Applied `seed-compaction-idempotency.sql` to Postgres
- [x] Applied `seed-compaction-idempotency.redis` to Redis
- [x] Verified Postgres has 9 rows (1 summary + 8 raw) for `frostyCompactionIdempotencyTest`
- [x] Verified the summary row exists with `[Conversation summary]` prefix
- [x] Deleted Redis key `user:frostyCompactionIdempotencyTest:instructions` (seeds don't touch it)

### Run

- [x] Step 1: sent `compaction-idempotency-prompt.yml`, HTTP 200
- [x] Step 2: waited 5 seconds
- [x] Step 3: queried Postgres for post-step state

### Expected

- [x] Step 1: HTTP 200, response references seeded facts (Rex / Warsaw / TechCorp)
- [x] Step 3: `chat_history` row count equals exactly 11 (9 pre-seeded + 2 new)
- [x] Step 3: exactly 1 `[Conversation summary]` row exists (NO second summary written)

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyCompactionIdempotencyTest'`
- [x] Deleted Redis key `chat:frostyCompactionIdempotencyTest`
- [x] Deleted Redis key `user:frostyCompactionIdempotencyTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyCompactionIdempotencyTest` returned `{"status":"success", ...}`

### Verdict

- [x] Verdict: PASS

## Result summary

Step 1 returned HTTP 200 with a normal chat completion referencing the seeded fact (Rex the beagle rescued from a Praga shelter), confirming the pre-compaction history stayed visible to the model. After a 5-second settle, Step 3 confirmed `chat_history` for `frostyCompactionIdempotencyTest` grew from the seeded 9 rows to exactly 11 (the new user+assistant pair), and the `[Conversation summary]` row count stayed at exactly 1, confirming compaction did not re-fire. Bruno request duration was 6501ms, consistent with a single normal chat call and no additional async compaction LLM call inflating the window.

Row count after step 3: 11 (expected 11) — PASS

Summary row count after step 3: 1 (expected 1) — PASS

Input tokens:

Output tokens:

Start (UTC): 2026-09-10T08:07:11Z

End (UTC): 2026-09-10T08:08:53Z

Duration: 00:01:42

---

## Additional tasks I did
