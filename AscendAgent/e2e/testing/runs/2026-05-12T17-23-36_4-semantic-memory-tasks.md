# Semantic memory — run tasks template

Spec: [4-semantic-memory-test.md](../4-semantic-memory-test.md)

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

- [x] Step 1 — sent `memory-test-save.yml` and waited for HTTP 200
- [x] Step 2 — re-cleared Redis `chat:frosty` and Postgres `chat_history` for frosty
- [x] Step 3 — sent `memory-test-retrieve.yml` and waited for HTTP 200

### Expected

- [x] After step 1: HTTP 200
- [x] After step 1: Qdrant scroll filtered by `user_id=frosty` returns ≥ 1 point
- [x] After step 1: at least one Qdrant point's payload contains both `Luke` and `software engineer`
- [x] After step 3: HTTP 200
- [x] After step 3: Response `content` contains `Luke`
- [x] After step 3: Response `content` contains `software engineer`
- [x] After step 3: Response `content` is NOT a refusal like "I don't know your name"

### Verdict

- [x] Verdict: PASS

## Result summary

End-to-end semantic memory roundtrip succeeded. Save call returned 200 in ~4.3s. After the 5s wait the Qdrant scroll on `ascend_memory_1536` returned 2 points for `user_id=frosty`: one payload `"User's name is Luke"`, another `"User is a software engineer"`. Chat history (Redis + Postgres) was wiped between save and recall, then the retrieve call returned 200 with `content`: "Your name is **Luke**, and you're a **software engineer**." Recall is provably from semantic memory, not chat history.

Input tokens: ~800

Output tokens: ~30

Start (UTC): 2026-05-12T17:30:20Z

End (UTC): 2026-05-12T17:32:36Z

Duration: 00:02:16

---

## Additional tasks I did

None.
