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
- [x] Verified Postgres has 21 rows for `compaction-fires-test`
- [x] Verified Redis list `chat:compaction-fires-test` has 21 entries

### Run

- [x] Step 1: sent `compaction-fires-prompt.yml`, HTTP 200
- [x] Step 2: waited 5 seconds for async compaction
- [x] Step 3: queried Postgres for post-compaction row counts

### Expected

- [x] Step 1: HTTP 200, response is a normal chat completion
- [x] Step 3: `chat_history` row count for `compaction-fires-test` equals exactly 9
- [x] Step 3: exactly 1 row has `role='system'` and content begins with `[Conversation summary]`
- [x] Step 3: exactly 8 rows have `role IN ('user', 'assistant')`
- [x] (Manual spot-check) summary content references Rex / Warsaw / TechCorp / Spring Boot

### Verdict

- [x] Verdict: PASS

## Result summary

Pre-compaction row count (after step 1): 23 (21 seeded + 2 from the prompt exchange)

Post-compaction row count (after step 3): 9

Summary row content (paste here for manual review):

```
[Conversation summary] The user is a backend engineer at TechCorp located in Warsaw who works daily with Spring Boot; they experienced a failed deployment last Tuesday due to a bad Liquibase change and are currently considering migrating one of their services from Spring Boot to Quarkus. Outside of work, the user has a beagle named Rex who enjoys chasing squirrels in the backyard; Rex recently slipped on a wet floor but is fine, and needs vaccinations updated next month at a Warsaw clinic.
```

Input tokens: (not captured)

Output tokens: (not captured)

Start (UTC): 2026-05-22T16:04:23Z

End (UTC): 2026-05-22T16:04:57Z

Duration: 00:00:34

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
