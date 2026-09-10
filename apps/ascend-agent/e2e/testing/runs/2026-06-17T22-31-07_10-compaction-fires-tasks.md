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

Step 1 returned HTTP 200 in 4997 ms — a normal chat completion for `frostyCompactionFiresTest` adding 2 rows (1 user + 1 assistant), bringing the total to 23. After the 5-second async compaction window, Postgres `chat_history` for `frostyCompactionFiresTest` contains exactly 9 rows: 1 `system` row whose content begins `[Conversation summary]`, and 8 `user`/`assistant` rows. The summary text references Rex the beagle, Warsaw, TechCorp, and Spring Boot — all four canary terms from the seeded conversation — confirming that the compaction model read and condensed the seeded turns correctly. All four programmatic assertions passed.

Pre-compaction row count (after step 1): 23 (21 seeded + 2 new turns)

Post-compaction row count (after step 3): 9

Summary row content (paste here for manual review):

```
[Conversation summary] The user is a backend engineer at TechCorp based in Warsaw who works daily with Spring Boot; they experienced a deployment failure last Tuesday caused by a bad Liquibase change and are currently considering migrating one of their services from Spring Boot to Quarkus. Outside of work, the user has a beagle named Rex who enjoys chasing squirrels in the backyard; Rex recently slipped on a wet floor but is fine, and needs vaccinations updated next month at a Warsaw clinic.
```

Input tokens:

Output tokens:

Start (UTC): 2026-06-17T22:31:07Z

End (UTC): 2026-06-17T22:33:15Z

Duration: 00:02:08

---

## Additional tasks I did

- Read `AscendAgent/src/main/resources/application.yaml` to confirm compaction defaults (`enabled=true`, `turn-trigger=20`, `keep-recent-turns=8`) since `/actuator/configprops` returned no useful output.
- Fetched full summary row content from Postgres to verify all four canary terms (Rex, Warsaw, TechCorp, Spring Boot) appear — confirmed present.
- The `docker exec redis rm` invocation without `sh -c` failed on the first attempt (Docker Desktop on Windows resolved the path against the host temp dir instead of the container filesystem). Retried with `sh -c "rm ..."` which succeeded. No impact on seed validity.
