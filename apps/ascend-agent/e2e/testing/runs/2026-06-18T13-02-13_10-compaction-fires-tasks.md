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

All Expected assertions passed. The Bruno request to `compaction-fires-prompt.yml` returned HTTP 200 with a normal chat completion (5758 ms). After the 5-second async wait, Postgres `chat_history` for `frostyCompactionFiresTest` held exactly 9 rows: 1 `system` row whose content begins with `[Conversation summary]` and 8 `user`/`assistant` rows. The compaction service correctly stripped the oldest turns and replaced them with a single summary. The summary text explicitly references Rex (beagle), Warsaw, TechCorp, and Spring Boot — satisfying the manual spot-check.

Pre-compaction row count (after step 1): 23 (21 seed + 2 from the prompt turn — observed indirectly; seed verified at 21 before the run)

Post-compaction row count (after step 3): 9 (confirmed)

Summary row content (paste here for manual review):

```
[Conversation summary]
The user is a backend engineer at TechCorp based in Warsaw who works daily with Spring Boot. Recently, a deployment failed due to a bad Liquibase change. The user is currently considering migrating one of their services from Spring Boot to Quarkus. Outside of work, the user has a beagle named Rex who enjoys chasing squirrels in the backyard; Rex recently slipped on a wet floor but is fine, and needs vaccinations updated next month at a Warsaw clinic.
```

Input tokens:

Output tokens:

Start (UTC): 2026-06-18T13:02:13Z

End (UTC): 2026-06-18T13:05:15Z

Duration: 00:03:02

---

## Additional tasks I did

- Confirmed compaction config directly from `application.yaml` since the actuator `/configprops` endpoint returned no output for the `chatHistoryCompaction` key (as the spec anticipated).
- The `docker exec redis rm /tmp/seed-compaction-fires.redis` command produced a spurious error about a Windows temp path on first attempt (shell quoting artifact on Windows/Git Bash); corrected by using single-quoted path inside the container's `sh -c` invocation. The file was successfully removed on the second attempt.
- Verified full summary text retrieved from Postgres — all four canary terms (Rex, Warsaw, TechCorp, Spring Boot) present.
