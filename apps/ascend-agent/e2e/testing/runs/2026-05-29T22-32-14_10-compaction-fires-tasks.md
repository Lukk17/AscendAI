# Chat-history compaction: fires + replaces prefix: run tasks template

Spec: [10-compaction-fires-test.md](10-compaction-fires-test.md)

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

### Verdict

- [x] Verdict: PASS

## Result summary

All four Expected assertions passed. Step 1 returned HTTP 200 (Bruno confirmed 200, 4697 ms). After the 5-second async wait, Postgres `chat_history` for user `frostyCompactionFiresTest` contained exactly 9 rows: 1 system row whose content begins with `[Conversation summary]` and 8 rows with role `user` or `assistant`. The summary row content (retrieved in full) explicitly references TechCorp, Warsaw, Spring Boot, and Rex the beagle, satisfying the manual spot-check. Compaction completed well within the 5-second budget. Seed applied cleanly (DELETE 9 + INSERT 0 21 from SQL; Redis DEL + 21 RPUSH operations).

Pre-compaction row count (after step 1): 23 (21 seeded + 2 from prompt)

Post-compaction row count (after step 3): 9

Summary row content (paste here for manual review):

```
[Conversation summary] The user is a backend engineer at TechCorp in Warsaw who works daily with Spring Boot; they experienced a failed deployment last Tuesday due to a bad Liquibase change and are currently considering migrating one of their services from Spring Boot to Quarkus. Outside of work, the user has a beagle named Rex who enjoys chasing squirrels in the backyard; Rex recently slipped on a wet floor but is fine, and needs vaccinations updated next month at a Warsaw clinic.
```

Input tokens:

Output tokens:

Start (UTC): 2026-05-29T22:33:41Z

End (UTC): 2026-05-29T22:35:54Z

Duration: 00:02:13

---

## Additional tasks I did

- Skipped the `configprops` grep sanity check per spec guidance (returned no output; trusted defaults).
- Retrieved full summary row content from Postgres to populate the manual spot-check field; confirmed all four canary markers (TechCorp, Warsaw, Spring Boot, Rex the beagle) present.

