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

- [x] Applied `seed-compaction-fires.sql` to Postgres (DELETE 9, INSERT 21)
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
- [x] (Manual spot-check) summary content references Rex / Warsaw / TechCorp / Spring Boot — confirmed (content: "[Conversation summary] The user is a backend engineer at TechCorp based in Warsaw who works daily with Spring Boot...")

### Verdict

- [x] Verdict: PASS

## Result summary

Step 1 (HTTP 200): model correctly summarised seeded facts. Async compaction fired within 5 seconds, reducing history from 23 → 9 rows (1 summary + 8 raw turns).

Pre-compaction row count (after step 1): 23 (21 seeded + 2 from this prompt)

Post-compaction row count (after step 3): 9

Summary row content (paste here for manual review):

```
[Conversation summary] The user is a backend engineer at TechCorp based in Warsaw who works daily with Spring Boot; they experienced a deployment failure last Tuesday caused by a bad Liquibase change and are currently considering migrating one of their services from Spring Boot to Quarkus. Outside of work, the user has a beagle named Rex who enjoys chasing squirrels in the backyard; Rex recently s[lipped on wet floor]...
```

Input tokens: 618

Output tokens: 178

Start (UTC): 2026-05-24T01:54:10Z

End (UTC): 2026-05-24T01:56:49Z

Duration: 00:02:39

---

## Additional tasks I did
