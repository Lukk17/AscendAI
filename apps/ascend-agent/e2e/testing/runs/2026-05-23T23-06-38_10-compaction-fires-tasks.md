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
- [x] Step 3: `chat_history` row count for `frostyCompactionFiresTest` equals exactly 9 — observed 9
- [x] Step 3: exactly 1 row has `role='system'` and content begins with `[Conversation summary]` — confirmed
- [x] Step 3: exactly 8 rows have `role IN ('user', 'assistant')` — observed 8
- [x] (Manual spot-check) summary content references Rex / Warsaw / TechCorp / Spring Boot — confirmed

### Verdict

- [x] Verdict: PASS

## Result summary

Seed applied: 21 rows Postgres + 21 Redis. Prompt sent (HTTP 200), response correctly summarised seeded facts (Rex, Warsaw, TechCorp, Spring Boot, Quarkus, Liquibase deploy incident). After 5s async compaction: total=9, summary=1, raw=8.

Pre-compaction row count (after step 1): 23 (21 seeded + 2 new user+assistant)

Post-compaction row count (after step 3): 9

Summary row content (paste here for manual review):

```
[Conversation summary] The user is a backend engineer at TechCorp in Warsaw who works primarily with Spring Boot and uses...
```

Input tokens: 618

Output tokens: 179

Start (UTC): 2026-05-23T23:14:08Z

End (UTC): 2026-05-23T23:16:39Z

Duration: 00:02:31

---

## Additional tasks I did
