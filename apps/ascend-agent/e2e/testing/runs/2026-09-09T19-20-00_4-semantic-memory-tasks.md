# Semantic memory: run tasks template

Spec: [../4-semantic-memory-test.md](../4-semantic-memory-test.md)

Copy this file to `runs/<UTC-timestamp>_4-semantic-memory-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version) — 3.4.0
- [x] ascend-ai-agent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] AscendMemory `/health` returns HTTP 200 with `{"status":"ok"}`
- [x] Qdrant `/healthz` returns HTTP 200
- [x] Redis responds to `PING` with `PONG`
- [x] Postgres responds to `SELECT 1` with a row

### Reset state

- [x] Cleared Redis `chat:frostySemanticMemoryTest` key
- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostySemanticMemoryTest'`
- [x] Wiped Qdrant `ascend_memory_*` points where `user_id = 'frostySemanticMemoryTest'`

### Run

- [x] Step 1: sent `memory-test-save.yml` and waited for HTTP 200
- [x] Step 2: re-cleared Redis `chat:frostySemanticMemoryTest` and Postgres `chat_history` for frostySemanticMemoryTest
- [x] Step 3: sent `memory-test-retrieve.yml` and waited for HTTP 200

### Expected

- [x] After step 1: HTTP 200
- [x] After step 1: Qdrant scroll filtered by `user_id=frostySemanticMemoryTest` returns ≥ 1 point
- [ ] After step 1: at least one Qdrant point's payload contains both `Luke` and `software engineer`
- [x] After step 3: HTTP 200
- [x] After step 3: Response `content` contains `Luke`
- [x] After step 3: Response `content` contains `software engineer`
- [x] After step 3: Response `content` is NOT a refusal like "I don't know your name"

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostySemanticMemoryTest` returned `{"status":"success", ...}`
- [x] Qdrant scroll on `ascend_memory_1536` filtered by `user_id=frostySemanticMemoryTest` returned an empty `points` array
- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostySemanticMemoryTest'`
- [x] Deleted Redis key `chat:frostySemanticMemoryTest`
- [x] Deleted Redis key `user:frostySemanticMemoryTest:instructions`

### Verdict

- [x] Verdict: FAIL

## Result summary

Steps 1-3 all returned HTTP 200 and the recall turn (step 3) fully satisfied its three assertions: the response
content was `"Your name is Luke, and you're a software engineer."`, containing both `Luke` and `software engineer`
and no refusal phrase, proven only from semantic memory since chat history was wiped between save and recall. The
step-1 Qdrant scroll returned 2 points (≥ 1, satisfied) but the spec's stricter assertion — that at least one single
point's payload contains BOTH `Luke` AND `software engineer` — did not hold: mem0 extracted the two facts as two
separate atomic points (`"My name is Luke"` and `"I am a software engineer"`), and neither point's `data` field
contains both terms. Because that Expected assertion is literal and unmet, the run is FAIL despite the end-to-end
recall capability itself working correctly.

Input tokens:

Output tokens:

Start (UTC): 2026-09-09T17:43:57Z

End (UTC): 2026-09-09T17:47:08Z

Duration: 00:03:11

---

## Additional tasks I did

- Inspected `docs/api/request/AscendAI/ascend-agent/testing/memory-test-save.yml`'s embedded test script after it
  failed. Its own test "endpoint returns response body with data" asserts `expect(res.getBody()).to.be.a("string")`,
  but Bruno's `getBody()` returns the already-parsed JSON object for a `application/json` response, so the assertion
  fails on every run regardless of the actual response content. This is a defect in the Bruno request's own script,
  not a product regression: the spec's own Expected assertion for step 1 (HTTP 200) held.
- Re-ran `memory-test-retrieve.yml` twice more after the spec's own step 3 (once plain, once with `--output` to
  scratchpad) purely to pull the raw response JSON as concrete evidence for this report. These are read-style
  recall calls against a user whose semantic memory hadn't changed, so they didn't affect the Expected assertions,
  but they did write 4 extra `chat_history` rows and inflate token usage for `frostySemanticMemoryTest`, which
  Post-run cleanup's blanket `DELETE FROM chat_history WHERE user_id = 'frostySemanticMemoryTest'` already covers
  (confirmed: cleanup deleted 6 rows total, consistent with 1 spec turn + 2 extra turns × 2 rows each).
- Deleted the scratchpad file (`retrieve-out.json`) written during the extra verification call.
