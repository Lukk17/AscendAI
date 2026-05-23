# Chat-history compaction: fires + replaces prefix: run tasks template

Spec: [10-compaction-fires-test.md](10-compaction-fires-test.md)

Copy to `runs/<UTC-timestamp>_10-compaction-fires-tasks.md` before starting.

## Tasks

### Prerequisites

- [ ] Bruno CLI present
- [ ] AscendAgent `/actuator/health` returns 200
- [ ] Postgres responds to `SELECT 1`
- [ ] Redis `PING` returns `PONG`
- [ ] Seed scripts `seed-compaction-fires.sql` + `seed-compaction-fires.redis` exist
- [ ] Default compaction config in effect (`enabled=true`, `turn-trigger=20`, `keep-recent-turns=8`)

### Reset state

- [ ] Applied `seed-compaction-fires.sql` to Postgres
- [ ] Applied `seed-compaction-fires.redis` to Redis
- [ ] Verified Postgres has 21 rows for `frostyCompactionFiresTest`
- [ ] Verified Redis list `chat:frostyCompactionFiresTest` has 21 entries

### Run

- [ ] Step 1: sent `compaction-fires-prompt.yml`, HTTP 200
- [ ] Step 2: waited 5 seconds for async compaction
- [ ] Step 3: queried Postgres for post-compaction row counts

### Expected

- [ ] Step 1: HTTP 200, response is a normal chat completion
- [ ] Step 3: `chat_history` row count for `frostyCompactionFiresTest` equals exactly 9
- [ ] Step 3: exactly 1 row has `role='system'` and content begins with `[Conversation summary]`
- [ ] Step 3: exactly 8 rows have `role IN ('user', 'assistant')`
- [ ] (Manual spot-check) summary content references Rex / Warsaw / TechCorp / Spring Boot

### Verdict

- [ ] Verdict: PASS / FAIL

## Result summary



Pre-compaction row count (after step 1): expected 23

Post-compaction row count (after step 3): expected 9

Summary row content (paste here for manual review):

```
[Conversation summary] ...
```

Input tokens:

Output tokens:

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did
