# Semantic memory: run tasks template

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

- [ ] Cleared Redis `chat:frostySemanticMemoryTest` key
- [ ] Deleted Postgres `chat_history` rows where `user_id = 'frostySemanticMemoryTest'`
- [ ] Wiped Qdrant `ascend_memory_*` points where `user_id = 'frostySemanticMemoryTest'`

### Run

- [ ] Step 1: sent `memory-test-save.yml` and waited for HTTP 200
- [ ] Step 2: re-cleared Redis `chat:frostySemanticMemoryTest` and Postgres `chat_history` for frostySemanticMemoryTest
- [ ] Step 3: sent `memory-test-retrieve.yml` and waited for HTTP 200

### Expected

- [ ] After step 1: HTTP 200
- [ ] After step 1: Qdrant scroll filtered by `user_id=frostySemanticMemoryTest` returns ≥ 1 point
- [ ] After step 1: at least one Qdrant point's payload contains both `Luke` and `software engineer`
- [ ] After step 3: HTTP 200
- [ ] After step 3: Response `content` contains `Luke`
- [ ] After step 3: Response `content` contains `software engineer`
- [ ] After step 3: Response `content` is NOT a refusal like "I don't know your name"

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary



Input tokens:

Output tokens:

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
