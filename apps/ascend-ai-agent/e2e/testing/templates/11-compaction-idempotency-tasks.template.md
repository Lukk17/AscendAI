# Chat-history compaction: idempotency: run tasks template

Spec: [../11-compaction-idempotency-test.md](../11-compaction-idempotency-test.md)

Copy to `runs/<UTC-timestamp>_11-compaction-idempotency-tasks.md` before starting.

## Tasks

### Prerequisites

- [ ] Bruno CLI present
- [ ] ascend-ai-agent `/actuator/health` returns 200
- [ ] Postgres responds to `SELECT 1`
- [ ] Redis `PING` returns `PONG`
- [ ] Seed scripts `seed-compaction-idempotency.sql` + `.redis` exist
- [ ] Default compaction config (`turn-trigger=20`, `keep-recent-turns=8`)

### Reset state

- [ ] Applied `seed-compaction-idempotency.sql` to Postgres
- [ ] Applied `seed-compaction-idempotency.redis` to Redis
- [ ] Verified Postgres has 9 rows (1 summary + 8 raw) for `frostyCompactionIdempotencyTest`
- [ ] Verified the summary row exists with `[Conversation summary]` prefix
- [ ] Deleted Redis key `user:frostyCompactionIdempotencyTest:instructions` (seeds don't touch it)

### Run

- [ ] Step 1: sent `compaction-idempotency-prompt.yml`, HTTP 200
- [ ] Step 2: waited 5 seconds
- [ ] Step 3: queried Postgres for post-step state

### Expected

- [ ] Step 1: HTTP 200, response references seeded facts (Rex / Warsaw / TechCorp)
- [ ] Step 3: `chat_history` row count equals exactly 11 (9 pre-seeded + 2 new)
- [ ] Step 3: exactly 1 `[Conversation summary]` row exists (NO second summary written)

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [ ] Deleted Postgres `chat_history` rows where `user_id = 'frostyCompactionIdempotencyTest'`
- [ ] Deleted Redis key `chat:frostyCompactionIdempotencyTest`
- [ ] Deleted Redis key `user:frostyCompactionIdempotencyTest:instructions`
- [ ] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyCompactionIdempotencyTest` returned `{"status":"success", ...}`

### Verdict

- [ ] Verdict: PASS / FAIL

## Result summary



Row count after step 3: expected 11

Summary row count after step 3: expected 1

Input tokens:

Output tokens:

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did
