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
- [x] Default compaction config in effect (`enabled=true`, `turn-trigger=20`, `keep-recent-turns=8`) — actuator configprops not exposed, trusting `application.yaml` defaults per spec

### Reset state

- [x] Applied `seed-compaction-fires.sql` to Postgres
- [x] Applied `seed-compaction-fires.redis` to Redis
- [x] Verified Postgres has 21 rows for `frostyCompactionFiresTest`
- [x] Verified Redis list `chat:frostyCompactionFiresTest` has 21 entries
- [x] Deleted Redis key `user:frostyCompactionFiresTest:instructions` (seeds don't touch it)

### Run

- [x] Step 1: sent `compaction-fires-prompt.yml`, HTTP 200
- [x] Step 2: waited 5 seconds for async compaction
- [x] Step 3: queried Postgres for post-compaction row counts

### Expected

- [x] Step 1: HTTP 200, response is a normal chat completion
- [x] Step 3: `chat_history` row count for `frostyCompactionFiresTest` equals exactly 9
- [x] Step 3: exactly 1 row has `role='system'` and content begins with `[Conversation summary]`
- [x] Step 3: exactly 8 rows have `role IN ('user', 'assistant')`
- [x] (Manual spot-check) summary content references Rex / Warsaw / TechCorp / Spring Boot

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyCompactionFiresTest'`
- [x] Deleted Redis key `chat:frostyCompactionFiresTest`
- [x] Deleted Redis key `user:frostyCompactionFiresTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyCompactionFiresTest` returned `{"status":"success", ...}`

### Verdict

- [x] Verdict: PASS

## Result summary

Step 1 sent one prompt as `frostyCompactionFiresTest` and returned HTTP 200 with a normal chat completion, adding 2 rows to bring the seeded 21-row history to 23. After a 5-second wait, Step 3's Postgres queries confirmed the async compaction had fired and replaced the prefix exactly as specified: total row count is 9, exactly 1 row has `role='system'` with content beginning `[Conversation summary]`, and exactly 8 rows have `role IN ('user','assistant')`. The summary content (manually inspected, not asserted programmatically) mentions Rex the beagle, Warsaw, TechCorp, and Spring Boot as expected. All Expected assertions hold.

Pre-compaction row count (after step 1): expected 23 (not directly queried; inferred from seeded 21 + 2 new rows from the prompt exchange, consistent with the async trigger firing after this `add(...)`)

Post-compaction row count (after step 3): 9 (matches expected)

Summary row content (paste here for manual review):

```
[Conversation summary]
The user is a backend engineer at TechCorp based in Warsaw who works daily with Spring Boot and has been considering migrating one of their services to Quarkus. They experienced a deployment failure last Tuesday caused by a bad Liquibase change. Outside of work, the user has a beagle named Rex who loves chasing squirrels in the backyard; Rex recently slipped on a wet floor but is fine, and needs vaccinations updated next month at a Warsaw clinic.
```

Input tokens: not available (Bruno CLI output does not surface LLM token usage; the agent's chat-completion response body wasn't captured for this metric)

Output tokens: not available (same reason as above)

Start (UTC): 2026-09-09T17:50:18Z

End (UTC): 2026-09-09T17:52:07Z

Duration: 00:01:49

---

## Additional tasks I did

- Queried the full summary row content (`SELECT content ...` unbounded, rather than the spec's `left(content, 60)`) to record the complete text in this run file for the manual spot-check field. Read-only, no state change.
