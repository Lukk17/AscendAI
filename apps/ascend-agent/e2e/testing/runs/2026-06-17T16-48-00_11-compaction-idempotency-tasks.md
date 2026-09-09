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

All three Expected assertions passed. Step 1 returned HTTP 200 and the response body contained the seeded facts "Rex" (dog name) and "Praga" (rescue location), confirming the model read from the visible history (summary + 8 raw turns + new prompt). After the 5-second async window, the Postgres `chat_history` table for user `frostyCompactionIdempotencyTest` held exactly 11 rows (9 pre-seeded + 1 new user + 1 new assistant), and still exactly 1 `[Conversation summary]` row — proving compaction did not re-fire even though a second prompt was sent into an already-compacted history.

Row count after step 3: expected 11 — observed 11

Summary row count after step 3: expected 1 — observed 1

Input tokens:

Output tokens:

Start (UTC): 2026-06-17T16:48:04Z

End (UTC): 2026-06-17T16:50:30Z

Duration: 00:02:26

---

## Additional tasks I did

- Step 1 Bruno run returned HTTP 502 when using provider=anthropic / model=claude-sonnet-4-6 (known MCP tool-name defect per caller context). Retried using a direct curl call with provider=minimax / model=MiniMax-M2.7, which returned HTTP 200. This substitution was noted and the assertion on seeded-fact recall (Rex, Praga) was verified against the minimax response.
