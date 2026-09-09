# Chat-history compaction: idempotency: run tasks template

Spec: [11-compaction-idempotency-test.md](11-compaction-idempotency-test.md)

Copy to `runs/<UTC-timestamp>_11-compaction-idempotency-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present
- [x] AscendAgent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] Seed scripts `seed-compaction-idempotency.sql` + `.redis` exist
- [x] Default compaction config (`turn-trigger=20`, `keep-recent-turns=8`)

### Reset state

- [x] Applied `seed-compaction-idempotency.sql` to Postgres
- [x] Applied `seed-compaction-idempotency.redis` to Redis
- [x] Verified Postgres has 9 rows (1 summary + 8 raw) for `frostyCompactionIdempotencyTest`
- [x] Verified the summary row exists with `[Conversation summary]` prefix

### Run

- [x] Step 1: sent `compaction-idempotency-prompt.yml`, HTTP 200
- [x] Step 2: waited 5 seconds
- [x] Step 3: queried Postgres for post-step state

### Expected

- [x] Step 1: HTTP 200, response references seeded facts (Rex / Warsaw / TechCorp)
- [x] Step 3: `chat_history` row count equals exactly 11 (9 pre-seeded + 2 new)
- [x] Step 3: exactly 1 `[Conversation summary]` row exists (NO second summary written)

### Verdict

- [x] Verdict: PASS

## Result summary

After seeding the database to the post-compaction state (1 [Conversation summary] system row + 8 raw turns = 9 rows total), one prompt was sent as user `frostyCompactionIdempotencyTest`. The agent responded HTTP 200 with content "Your dog is Rex, a beagle rescued from a shelter in Praga (a district of Warsaw)." — directly referencing the seeded facts (Rex the beagle, Praga shelter, Warsaw). After waiting 5 seconds for any async compaction, Postgres showed exactly 11 rows (9 pre-seeded + 1 new user + 1 new assistant) and exactly 1 [Conversation summary] row. Compaction did not re-fire despite the pre-existing summary, confirming the idempotency guard is working correctly.

Row count after step 3: 11 (expected 11) — PASS

Summary row count after step 3: 1 (expected 1) — PASS

Input tokens: ~531 (Anthropic API, per response metadata)

Output tokens: ~26 (Anthropic API, per response metadata)

Start (UTC): 2026-06-17T22:31:11Z

End (UTC): 2026-06-17T22:39:00Z

Duration: 00:07:49

---

## Additional tasks I did

1. First Bruno run used `bru run` without `--output json` (HTTP 200 confirmed from stdout), then a second `bru run --output json` was used to capture the response body for assertion verification. The second run added 2 extra rows (13 total vs expected 11). The first bru invocation correctly produced 11 rows.
2. To resolve the contamination, the Reset state was re-applied (SQL + Redis seed re-run), restoring the clean 9-row state. The prompt was then re-run via equivalent curl call (same payload, same headers, same endpoint) rather than a third Bruno invocation. The curl response matched the Bruno response exactly. The final persisted state verified: 11 rows, 1 summary row.
3. In future runs, the spec's Run step should be executed exactly once via Bruno; response body can be verified from the Bruno stdout without a second invocation.
