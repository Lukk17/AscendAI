# Semantic memory — run tasks template

Spec: [4-semantic-memory-test.md](4-semantic-memory-test.md)

Copy this file to `runs/<UTC-timestamp>_4-semantic-memory-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [ ] AscendMemory `/health` returns HTTP 200 with `{"status":"ok"}`
- [ ] Qdrant `/healthz` returns HTTP 200
- [ ] Redis responds to `PING` with `PONG`
- [ ] Postgres responds to `SELECT 1` with a row

### Reset state

- [ ] Cleared Redis `chat:frosty` key
- [ ] Deleted Postgres `chat_history` rows where `user_id = 'frosty'`
- [ ] Wiped Qdrant `ascend_memory_*` points where `user_id = 'frosty'`

### Run

- [ ] Step 1 — sent `memory-test-save.yml` and waited for HTTP 200
- [ ] Step 2 — re-cleared Redis `chat:frosty` and Postgres `chat_history` for frosty
- [ ] Step 3 — sent `memory-test-retrieve.yml` and waited for HTTP 200

### Expected

- [ ] After step 1: AscendAgent log shows `Inserted N/N facts for user 'frosty'` with N ≥ 1
- [ ] After step 1: Qdrant scroll on the active `ascend_memory_*` collection filtered by `user_id=frosty` returns at least one point mentioning Luke / software engineer
- [ ] After step 3: AscendAgent log shows `SemanticMemory: YES (N items)` with N ≥ 1
- [ ] After step 3: Response `content` mentions `Luke` and `software engineer`

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary

<!-- One short paragraph: what happened, key evidence, anything noteworthy. -->

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
