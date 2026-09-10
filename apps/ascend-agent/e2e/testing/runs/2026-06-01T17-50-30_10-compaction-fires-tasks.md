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

All four programmatic assertions passed. Step 1 (Bruno `compaction-fires-prompt.yml`) returned HTTP 200 in 7161 ms — the prompt went through normally without waiting for async compaction. After the 5-second wait, the Postgres `chat_history` table for `frostyCompactionFiresTest` held exactly 9 rows: 1 `system` row whose content begins with `[Conversation summary]` (verified via `LIKE '[Conversation summary]%'`), and 8 `user`/`assistant` rows. The manual spot-check confirms the summary row mentions TechCorp, Warsaw, Spring Boot, and Rex the beagle — all four canary subjects from the seed data. Compaction fired and completed well within the 5-second budget (the async task ran during the Bruno HTTP round-trip of ~7 s total, so the summary was already present when the sleep finished).

Pre-compaction row count (after step 1): expected 23 — not directly queried mid-flight; seed had 21 + 2 new turns = 23 before compaction.

Post-compaction row count (after step 3): 9 (observed)

Summary row content (paste here for manual review):

```
[Conversation summary]
The user is a backend engineer at TechCorp in Warsaw who works daily with Spring Boot; they experienced a deployment failure last Tuesday due to a bad Liquibase change and are currently considering migrating one of their services from Spring Boot to Quarkus. Outside of work, they have a beagle named Rex who loves chasing squirrels in the backyard; Rex recently slipped on a wet floor but is fine, and needs vaccinations updated next month at a Warsaw clinic.
```

Input tokens: ~3200

Output tokens: ~650

Start (UTC): 2026-06-01T17:50:30Z

End (UTC): 2026-06-01T17:53:33Z

Duration: 00:03:03

---

## Additional tasks I did

- Read `application.yaml` directly to confirm compaction defaults (`enabled=true`, `turn-trigger=20`, `keep-recent-turns=8`) because `/actuator/configprops` returned empty (not exposed in this environment).
- Queried oldest 3 rows (ORDER BY created_at ASC) to confirm the summary row is correctly positioned at the head of history, not at the tail.
- Retrieved full summary content for the manual spot-check canary verification.

