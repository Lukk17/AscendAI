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

All three Expected assertions held. Step 1 returned HTTP 200 with a non-empty completion that correctly referenced the seeded facts: the assistant's new reply named "Rex, a beagle rescued from a shelter in Praga (a district of Warsaw)", read directly from `chat_history` row 1609 after the run. Step 3 found `chat_history` row count for `frostyCompactionIdempotencyTest` at exactly 11 (the pre-seeded 9 plus the new user+assistant pair), and exactly 1 `[Conversation summary]` row, confirming compaction did not re-fire since turns past the existing summary (10) stayed under the turn-trigger (20). The Bruno request completed in ~6.4s, consistent with a single LLM call and no additional async compaction dispatch.

Row count after step 3: expected 11, observed 11

Summary row count after step 3: expected 1, observed 1

Input tokens: not measured (Bruno CLI run, no LLM token accounting surfaced by this runner)

Output tokens: not measured (Bruno CLI run, no LLM token accounting surfaced by this runner)

Start (UTC): 2026-09-09T17:50:24Z

End (UTC): 2026-09-09T17:52:35Z

Duration: 00:02:11

---

## Additional tasks I did

None. All steps executed exactly as prescribed by the spec; no classifier-blocked commands and no off-spec diagnostics were needed.
