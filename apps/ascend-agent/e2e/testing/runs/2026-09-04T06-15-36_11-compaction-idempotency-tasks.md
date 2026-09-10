# Chat-history compaction: idempotency: run tasks template

Spec: [../11-compaction-idempotency-test.md](../11-compaction-idempotency-test.md)

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

Step 1 returned HTTP 200 with a normal chat completion in 3152 ms, well under step 1's duration in the fires test, consistent with no compaction-call window on this path. Step 3 assertions all matched exactly, chat_history for frostyCompactionIdempotencyTest grew from the seeded 9 rows to exactly 11 rows, and exactly 1 row still had role system with content beginning with the literal string Conversation summary in brackets, confirming no second compaction fired. The persisted assistant response referenced Rex the beagle and Warsaw, matching the seeded facts, which is only possible if the model retrieved the visible chat history rather than starting cold. Post-run cleanup removed all Postgres rows, both Redis keys, and wiped semantic memory for the user, and a follow-up check confirmed zero rows and zero keys remain for frostyCompactionIdempotencyTest.

Row count after step 3: 11 (confirmed)

Summary row count after step 3: 1 (confirmed, unchanged from the seeded state)

Input tokens: not available (Bruno CLI's summary output does not surface the response body or its usage metadata, and the spec does not instruct capturing the raw response with -o; no second paid call was made to avoid double-billing this run)

Output tokens: not available (same reason as Input tokens)

Start (UTC): 2026-09-04T06:18:48Z

End (UTC): 2026-09-04T06:20:27Z

Duration: 00:01:39

---

## Additional tasks I did

Ran `SELECT role, content FROM chat_history WHERE user_id = 'frostyCompactionIdempotencyTest' AND role = 'assistant' ORDER BY created_at DESC LIMIT 1;` to make the "response references seeded facts" Expected item an observable check against persisted state rather than an unverifiable assumption from the Bruno test-pass summary. Not itself prescribed by the spec's Run/Expected steps as written, but same command shape (docker exec postgres psql -c) as the prescribed assertion queries.

Ran two extra confirmation queries after Post-run cleanup (`SELECT count(*) ...` on Postgres and `EXISTS` on the two Redis keys) to verify nothing was left behind for the user id, per the caller's explicit instruction to confirm at the end that nothing is left. Not itself prescribed by the spec's Post-run cleanup section, but same command shapes as steps already in the spec.

Did not capture LLM token usage from response metadata as instructed by the caller, for the same reason recorded in the 10-compaction-fires run: Bruno CLI's console summary reporter does not print the response body or usage fields, and the spec's Run step does not direct output to a file. Left blank per the contract's "leave blank if exact numbers aren't available, do not invent" rule.
