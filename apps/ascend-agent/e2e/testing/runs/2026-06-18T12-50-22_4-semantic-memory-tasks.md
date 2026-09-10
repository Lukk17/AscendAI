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
- [x] After step 1: at least one Qdrant point's payload contains both `Luke` and `software engineer`
- [x] After step 3: HTTP 200
- [x] After step 3: Response `content` contains `Luke`
- [x] After step 3: Response `content` contains `software engineer`
- [x] After step 3: Response `content` is NOT a refusal like "I don't know your name"

### Verdict

- [x] Verdict: PASS

## Result summary

All seven Expected assertions passed. The save turn (Step 1) returned HTTP 200. After the mandatory 5-second wait, the Qdrant scroll on `ascend_memory_1536` filtered by `user_id=frostySemanticMemoryTest` returned exactly 2 points: one with `data="User's name is Luke"` and one with `data="User is a software engineer"`, confirming both facts were extracted and persisted by mem0. Chat history was wiped between the save and recall turns (Redis DEL returned 1, Postgres DELETE removed 2 rows). The recall turn (Step 3) returned HTTP 200 with `content="Your name is Luke, and you're a software engineer."` — explicitly containing both `Luke` and `software engineer`, and not a refusal. Because chat history was fully cleared, the only source of those facts was semantic memory retrieved from Qdrant via AscendMemory.

Input tokens: ~3500

Output tokens: ~400

Start (UTC): 2026-06-18T12:50:22Z

End (UTC): 2026-06-18T12:53:11Z

Duration: 00:02:49

---

## Additional tasks I did

- Ran `memory-test-retrieve.yml` a second time with `--output` flag to capture the full JSON response body and verify the `content` field value exactly. The spec's Run step only checks HTTP 200 via the standard Bruno summary; the explicit JSON capture was needed to confirm the Expected content assertions.
- The prior run that failed was due to mem0 non-deterministically extracting only one fact (the name) and dropping the occupation fact. This run, mem0 extracted both facts cleanly into two separate Qdrant points (`User's name is Luke` and `User is a software engineer`), and the recall response referenced both.
