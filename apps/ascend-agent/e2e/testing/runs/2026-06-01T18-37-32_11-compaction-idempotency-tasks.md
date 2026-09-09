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

Step 1 returned HTTP 200 in 3.5 s. The response body `content` field read "Your dog is Rex, a beagle rescued from a shelter in Praga (a district of Warsaw)." — correctly citing Rex and Warsaw from the seeded chat history. Step 3 Postgres queries confirmed: total row count = 11 (9 pre-seeded + 1 user + 1 assistant from the new prompt), and exactly 1 `[Conversation summary]` row remains (no second compaction fired). Both assertions match the Expected section exactly. The compaction idempotency guard functioned correctly: 10 turns past the existing summary is less than the trigger of 20, so no re-compaction occurred.

Row count after step 3: 11 (expected 11) ✓

Summary row count after step 3: 1 (expected 1) ✓

Input tokens:

Output tokens:

Start (UTC): 2026-06-01T18:37:32Z

End (UTC): 2026-06-01T18:43:14Z

Duration: 00:05:42

---

## Additional tasks I did

- Redis seed file piped via PowerShell failed silently (BOM-artifact issue with `docker exec -i ... | redis-cli` in PowerShell): the `DEL` command was rejected with `ERR unknown command '﻿DEL'`. Diagnosed by inspecting first bytes of the seed file (no actual BOM). Root cause: PowerShell `|` pipe adds a UTF-8 BOM preamble when encoding strings to stdin for docker. Worked around by using Git Bash `cat file | docker exec -i redis redis-cli` which piped the file correctly.
- Re-ran the Bruno request once accidentally (with `--output json`) before noticing the row count was 13. Re-applied both seed scripts and performed a single clean run to produce the authoritative 9→11 row-count evidence. The two intermediate runs from before the final reset do not affect the verdict: state was fully reset to 9 rows / 9 Redis items before the authoritative run.
- Noted that the `runs/json` output file retains the response from the second (pre-reset) run; the final run did not use `--output json`. The authoritative evidence is the Postgres row count (11) and summary count (1), confirmed directly via `docker exec postgres psql`.

