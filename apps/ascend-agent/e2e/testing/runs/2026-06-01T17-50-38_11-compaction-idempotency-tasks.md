# Chat-history compaction: idempotency: run tasks template

Spec: [11-compaction-idempotency-test.md](../11-compaction-idempotency-test.md)

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

After seeding the DB and Redis to the post-compaction state (9 rows: 1 summary + 8 raw turns, for user `frostyCompactionIdempotencyTest`), a single prompt was sent via `compaction-idempotency-prompt.yml`. The agent responded HTTP 200 and the response body referenced seeded facts: "Your dog is Rex, a beagle rescued from a shelter in Praga (a district of Warsaw)" confirming the in-context summary was read. After a 5-second wait, Postgres shows exactly **11** total rows (9 + 2 new user/assistant pair) and exactly **1** `[Conversation summary]` row — the same one seeded. No second compaction was triggered. The idempotency constraint holds: turns-past-summary = 10 < trigger threshold 20.

Row count after step 3: expected 11 — **observed 11**

Summary row count after step 3: expected 1 — **observed 1**

Input tokens:

Output tokens:

Start (UTC): 2026-06-01T17:50:46 UTC

End (UTC): 2026-06-01T17:55:10 UTC

Duration: 00:04:24

---

## Additional tasks I did

- First Bruno run was executed twice by mistake (once without flags, once with `--output json`), producing 13 rows instead of 11. Detected the cause from `SELECT ... ORDER BY created_at` — duplicate user/assistant rows from the second invocation at 17:52:53. Re-seeded DB and Redis and ran the clean single-call pass which produced the correct 11 rows.
- Checked the startup readiness banner via `docker logs ascend-agent`; all external dependencies show `[Connected]` — Postgres, Redis, Qdrant, MinIO, AscendMemory, and all 12 MCP tools.
- Cleaned up the `json` output file left by Bruno in `docs/api/request/AscendAI/json`.
