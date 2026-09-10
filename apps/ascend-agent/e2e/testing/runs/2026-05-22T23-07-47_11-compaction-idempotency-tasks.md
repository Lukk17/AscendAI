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

- [x] Applied `seed-compaction-idempotency.sql` to Postgres (DELETE 9, INSERT 1 + INSERT 8)
- [x] Applied `seed-compaction-idempotency.redis` to Redis (DEL + 9 RPUSH + EXPIRE)
- [x] Verified Postgres has 9 rows (1 summary + 8 raw) for `frostyCompactionIdempotencyTest`
- [x] Verified the summary row exists with `[Conversation summary]` prefix

### Run

- [x] Step 1: sent `compaction-idempotency-prompt.yml`, HTTP 200
- [x] Step 2: waited 5 seconds
- [x] Step 3: queried Postgres for post-step state

### Expected

- [x] Step 1: HTTP 200, response references seeded facts — observed "Your dog is Rex, a beagle rescued from a shelter in Praga (a district of Warsaw)"
- [x] Step 3: `chat_history` row count equals exactly 11 (9 pre-seeded + 2 new) — observed 11
- [x] Step 3: exactly 1 `[Conversation summary]` row exists (NO second summary written) — observed 1

### Verdict

- [x] Verdict: PASS

## Result summary

Step 1: HTTP 200. Response correctly referenced Rex and Praga from the seeded summary.
Step 3: 11 rows total, 1 summary row (no re-compaction fired). Idempotency confirmed.

Row count after step 3: 11

Summary row count after step 3: 1

Input tokens: 531

Output tokens: 26

Start (UTC): 2026-05-22T23:21:21Z

End (UTC): 2026-05-22T23:23:26Z

Duration: 00:02:05

---

## Additional tasks I did
