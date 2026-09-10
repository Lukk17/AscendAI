# Chat-history compaction: fires + replaces prefix: run tasks template

Spec: [../10-compaction-fires-test.md](../10-compaction-fires-test.md)

Copy to `runs/<UTC-timestamp>_10-compaction-fires-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present
- [x] AscendAgent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] Seed scripts `seed-compaction-fires.sql` + `seed-compaction-fires.redis` exist
- [x] Default compaction config in effect (`enabled=true`, `turn-trigger=20`, `keep-recent-turns=8`)

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

Step 1 returned HTTP 200 with a normal chat completion, and the async compaction fired and completed well within the 5 second budget. Step 3 assertions all matched exactly, chat_history for frostyCompactionFiresTest held exactly 9 rows, exactly 1 system row whose content began with the literal string Conversation summary in brackets, and exactly 8 rows split between user and assistant roles. The summary content was manually inspected and references Rex the beagle, Warsaw, TechCorp and Spring Boot as expected. Post-run cleanup removed all Postgres rows, both Redis keys, and wiped semantic memory for the user, and a follow-up check confirmed zero rows and zero keys remain for frostyCompactionFiresTest.

Pre-compaction row count (after step 1): 23 (not queried directly, inferred from 21 seeded plus 1 user plus 1 assistant per spec description; not independently verified since the spec only prescribes verifying the post-compaction count in step 3)

Post-compaction row count (after step 3): 9 (confirmed)

Summary row content (paste here for manual review):

```
[Conversation summary] The user is a backend engineer at TechCorp based in Warsaw who works daily with Spring Boot. They experienced a failed deployment last Tuesday due to a bad Liquibase change and are currently considering migrating one of their services from Spring Boot to Quarkus. Outside of work, the user has a beagle named Rex who enjoys chasing squirrels in the backyard, Rex recently slipped on a wet floor but recovered fine, and needs vaccinations updated next month at a Warsaw clinic.
```

Input tokens: not available (Bruno CLI's summary output does not surface the response body or its usage metadata, and the spec does not instruct capturing the raw response with -o; no second paid call was made to avoid double-billing this run)

Output tokens: not available (same reason as Input tokens)

Start (UTC): 2026-09-04T06:15:54Z

End (UTC): 2026-09-04T06:18:13Z

Duration: 00:02:19

---

## Additional tasks I did

Ran `docker exec redis sh -c "ls -la /tmp/"` after the seed file removal to visually confirm the container tmp directory was empty. Not prescribed by the spec, but uses the same allowlisted command shape (docker exec redis sh -c) as the reset step it followed.

Ran a full, untruncated `SELECT content FROM chat_history ...` query for the summary row to paste into this run record for manual spot-check, instead of the spec's truncated `left(content, 60)` version used for the programmatic assertion. Same command shape as the prescribed assertion query, just a different column list.

Ran two extra confirmation queries after Post-run cleanup (`SELECT count(*) ...` on Postgres and `EXISTS` on the two Redis keys) to verify nothing was left behind for the user id, per the caller's explicit instruction to confirm at the end that nothing is left. Not itself prescribed by the spec's Post-run cleanup section, but same command shapes as steps already in the spec.

Did not capture LLM token usage from response metadata as instructed by the caller, because Bruno CLI's console summary reporter does not print the response body or usage fields, and the spec's Run step does not direct output to a file. Capturing it would have required either modifying the Bruno request/environment (out of scope, specs are immutable) or re-running the paid call a second time (would double the billed cost of a single-execution instruction). Left blank per the contract's "leave blank if exact numbers aren't available, do not invent" rule.
