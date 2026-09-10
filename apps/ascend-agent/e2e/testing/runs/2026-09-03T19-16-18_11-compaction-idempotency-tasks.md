# Chat-history compaction: idempotency: run tasks template

Spec: [../11-compaction-idempotency-test.md](../11-compaction-idempotency-test.md)

Copy to `runs/<UTC-timestamp>_11-compaction-idempotency-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present (3.4.0)
- [x] AscendAgent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] Seed scripts `seed-compaction-idempotency.sql` + `.redis` exist
- [x] Default compaction config (`turn-trigger=20`, `keep-recent-turns=8`) (trusted per spec's own note, not independently queried)

### Reset state

- [x] Applied `seed-compaction-idempotency.sql` to Postgres (deleted 11 leftover rows from a prior run, then inserted 1 summary + 8 raw)
- [x] Applied `seed-compaction-idempotency.redis` to Redis
- [x] Verified Postgres has 9 rows (1 summary + 8 raw) for `frostyCompactionIdempotencyTest`
- [x] Verified the summary row exists with `[Conversation summary]` prefix
- [x] Deleted Redis key `user:frostyCompactionIdempotencyTest:instructions` (seeds don't touch it)

### Run

- [x] Step 1: sent `compaction-idempotency-prompt.yml`, HTTP 200
- [x] Step 2: waited 5 seconds
- [x] Step 3: queried Postgres for post-step state

### Expected

- [x] Step 1: HTTP 200, response references seeded facts (Rex / Warsaw / TechCorp) (response: "Your dog is Rex, a beagle rescued from a shelter in Praga (a district of Warsaw).")
- [x] Step 3: `chat_history` row count equals exactly 11 (9 pre-seeded + 2 new)
- [x] Step 3: exactly 1 `[Conversation summary]` row exists (NO second summary written)

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyCompactionIdempotencyTest'`
- [x] Deleted Redis key `chat:frostyCompactionIdempotencyTest`
- [x] Deleted Redis key `user:frostyCompactionIdempotencyTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyCompactionIdempotencyTest` returned `{"status":"success","message":"All memories wiped for user frostyCompactionIdempotencyTest"}`

### Verdict

- [x] Verdict: PASS

## Result summary

Both Bruno test assertions passed (status 200, non-empty content). The response referenced the seeded facts correctly ("Your dog is Rex, a beagle rescued from a shelter in Praga (a district of Warsaw)."), proving the 1-summary + 8-raw-turn seeded history was visible to the model. After the 5-second wait, the Postgres row count for `frostyCompactionIdempotencyTest` was exactly 11 (9 seeded + 1 new user + 1 new assistant turn), and exactly 1 row still carried the `[Conversation summary]` prefix, confirming compaction did not re-fire: turns past the existing summary reached only 10 (well under the turn-trigger of 20), so `ChatHistoryCompactionService` correctly stayed dormant. Post-run cleanup dropped all 11 rows, both Redis keys and wiped AscendMemory points for this user.

Provider: anthropic. Model: claude-sonnet-4-6 for the single call. No compaction call fired this time, so there is no second paid call to account for in this spec (unlike test 10).

Token usage (single call, from `metadata.usage` and `nativeUsage` in the response body):
Input (prompt) tokens: 531
Output (completion) tokens: 26
Total tokens: 557
Cache creation tokens: 4
Cache read tokens: 3744 (the same long-lived ephemeral cache entry seen across tests 9 and 10 in this sweep, keyed on the identical static system-prompt prefix)

Input tokens: 531

Output tokens: 26

Row count after step 3: 11

Summary row count after step 3: 1

Start (UTC): 2026-09-03T19:28:26Z

End (UTC): 2026-09-03T19:29:27Z

Duration: 00:01:01

---

## Additional tasks I did

Wrote the Bruno run output to a scratch JSON file (`test11-run.json`) to inspect `metadata.usage.nativeUsage` for token accounting.

Reproduced the same Git Bash path-mangling defect already reported under test 10's run record: `docker exec redis rm /tmp/seed-compaction-idempotency.redis` failed with `rm: can't remove 'C:/Users/Lukk/AppData/Local/Temp/seed-compaction-idempotency.redis': No such file or directory`. Same root cause (my shell auto-converts the bare `/tmp/...` argument to a Windows path before it reaches `docker exec`), reported rather than worked around, and harmless to the assertions this spec actually checks.
