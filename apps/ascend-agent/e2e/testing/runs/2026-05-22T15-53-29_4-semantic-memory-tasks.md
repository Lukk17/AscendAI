# Semantic memory: run tasks template

Spec: [4-semantic-memory-test.md](4-semantic-memory-test.md)

Copy this file to `runs/<UTC-timestamp>_4-semantic-memory-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version)
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] AscendMemory `/health` returns HTTP 200 with `{"status":"ok"}`
- [x] Qdrant `/healthz` returns HTTP 200
- [x] Redis responds to `PING` with `PONG`
- [x] Postgres responds to `SELECT 1` with a row

### Reset state

- [x] Cleared Redis `chat:frosty` key
- [x] Deleted Postgres `chat_history` rows where `user_id = 'frosty'`
- [x] Wiped Qdrant `ascend_memory_*` points where `user_id = 'frosty'`

### Run

- [x] Step 1: sent `memory-test-save.yml` and waited for HTTP 200
- [x] Step 2: re-cleared Redis `chat:frosty` and Postgres `chat_history` for frosty
- [x] Step 3: sent `memory-test-retrieve.yml` and waited for HTTP 200

### Expected

- [x] After step 1: HTTP 200
- [x] After step 1: Qdrant scroll filtered by `user_id=frosty` returns ≥ 1 point
- [ ] After step 1: at least one Qdrant point's payload contains both `Luke` and `software engineer`
- [x] After step 3: HTTP 200
- [x] After step 3: Response `content` contains `Luke`
- [ ] After step 3: Response `content` contains `software engineer`
- [x] After step 3: Response `content` is NOT a refusal like "I don't know your name"

### Verdict

- [ ] Verdict: FAIL

## Result summary

mem0 extracted only `"Luke"` from the save prompt "Hello, my name is Luke. I am a software engineer." — the occupation fact was not stored. Qdrant scroll returned 1 point with `data: "Luke"` only. Retrieve response: "Your name is Luke. I don't have any details about what you do stored in your memory." — confirms Luke is recalled but occupation is absent.

Failing assertions:
1. Qdrant payload does not contain "software engineer" (only `"Luke"` stored by mem0)
2. Retrieve response does not contain "software engineer"

Input tokens: 89

Output tokens: 83

Start (UTC): 2026-05-22T15:56:11Z

End (UTC): 2026-05-22T16:00:00Z

Duration: 00:03:49

---

## Additional tasks I did

- Re-ran retrieve step via direct curl to capture full response body for assertion verification.
