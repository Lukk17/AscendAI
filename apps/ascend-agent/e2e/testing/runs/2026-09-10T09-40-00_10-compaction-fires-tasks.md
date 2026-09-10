# Chat-history compaction: fires + replaces prefix: run tasks template

Spec: [../10-compaction-fires-test.md](../10-compaction-fires-test.md)

Copy to `runs/<UTC-timestamp>_10-compaction-fires-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present
- [x] ascend-ai-agent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] Seed scripts `seed-compaction-fires.sql` + `seed-compaction-fires.redis` exist
- [x] Default compaction config in effect (`enabled=true`, `turn-trigger=20`, `keep-recent-turns=8`) — configprops not exposed, trusted defaults per spec instruction

### Reset state

- [x] Applied `seed-compaction-fires.sql` to Postgres (DELETE 0, INSERT 0 21)
- [x] Applied `seed-compaction-fires.redis` to Redis (DEL, 21x RPUSH, 1 more command)
- [x] Verified Postgres has 21 rows for `frostyCompactionFiresTest`
- [x] Verified Redis list `chat:frostyCompactionFiresTest` has 21 entries
- [x] Deleted Redis key `user:frostyCompactionFiresTest:instructions` (seeds don't touch it) — returned 0, key was absent

### Run

- [x] Step 1: sent `compaction-fires-prompt.yml`, HTTP 200 (2/2 embedded tests passed, 5840ms)
- [x] Step 2: waited 5 seconds for async compaction
- [x] Step 3: queried Postgres for post-compaction row counts

### Expected

- [x] Step 1: HTTP 200, response is a normal chat completion
- [x] Step 3: `chat_history` row count for `frostyCompactionFiresTest` equals exactly 9 (confirmed: 9)
- [x] Step 3: exactly 1 row has `role='system'` and content begins with `[Conversation summary]` (confirmed: 1, most-recent row by created_at is this row)
- [x] Step 3: exactly 8 rows have `role IN ('user', 'assistant')` (confirmed: 8)
- [x] (Manual spot-check) summary content references Rex / Warsaw / TechCorp / Spring Boot — all four present in the summary text

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyCompactionFiresTest'` (DELETE 9)
- [x] Deleted Redis key `chat:frostyCompactionFiresTest` (returned 1)
- [x] Deleted Redis key `user:frostyCompactionFiresTest:instructions` (returned 1)
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyCompactionFiresTest` returned `{"status":"success", ...}` (exact match)

### Verdict

- [x] Verdict: PASS

## Result summary

Sent one prompt as `frostyCompactionFiresTest` on top of the 21-row seed; step 1 returned HTTP 200 with a normal chat completion (both embedded Bruno tests passed). After a 5-second wait, `chat_history` for the user held exactly 9 rows: exactly 1 `role='system'` row whose content begins with `[Conversation summary]` and is the most-recent row by `created_at`, and exactly 8 rows with `role IN ('user','assistant')`. The summary text (manual spot-check only, not asserted programmatically) mentions Rex, Warsaw, TechCorp and Spring Boot as the spec expects. All four Expected assertions hold; Verdict PASS.

Pre-compaction row count (after step 1): expected 23 (not queried directly — spec's Run section doesn't call for a query between steps 1 and 3; async compaction had already reduced it to 9 by the time step 3 ran)

Post-compaction row count (after step 3): 9 (confirmed)

Summary row content (paste here for manual review):

```
[Conversation summary] The user is a backend engineer at TechCorp in Warsaw who works daily with Spring Boot; they experienced a deployment failure last Tuesday due to a bad Liquibase change and are now considering migrating one of their services from Spring Boot to Quarkus. Outside of work, the user has a beagle named Rex who enjoys chasing squirrels in the backyard; Rex recently slipped on a wet floor but is fine, and needs vaccinations updated next month at a Warsaw clinic.
```

Input tokens: not available (no LLM API metering surfaced to this runner; the compaction call happens server-side inside ascend-ai-agent's own provider call, not exposed on the Bruno response body)

Output tokens: not available (same reason)

Start (UTC): 2026-09-10T08:06:40Z

End (UTC): 2026-09-10T08:08:47Z

Duration: 00:02:07

---

## Additional tasks I did

- Fetched the full (untruncated) summary row content via an extra `SELECT content ...` query beyond the spec's `left(content, 60)` preview, purely to populate the Result summary's "Summary row content" field for manual review. No state was mutated by this query.
