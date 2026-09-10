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
- [x] After step 1: Qdrant scroll filtered by `user_id=frostySemanticMemoryTest` returns >= 1 point
- [ ] After step 1: at least one Qdrant point's payload contains both `Luke` and `software engineer`
- [x] After step 3: HTTP 200
- [x] After step 3: Response `content` contains `Luke`
- [ ] After step 3: Response `content` contains `software engineer`
- [x] After step 3: Response `content` is NOT a refusal like "I don't know your name"

### Verdict

- [ ] Verdict: FAIL

## Result summary

The save turn (Step 1) returned HTTP 200. After a 5-second wait, the Qdrant scroll on `ascend_memory_1536` filtered by `user_id=frostySemanticMemoryTest` returned exactly 1 point, satisfying the >= 1 requirement. However, that single point's `data` field contains only "User's name is Luke" and does not mention "software engineer". Mem0 extracted only the name fact and discarded the profession fact during memory consolidation. Consequently, the recall turn (Step 3) returned HTTP 200 and the response `content` correctly referenced "Luke" (observed value: "Your name is **Luke** — I know that from your user memory."), confirming that semantic memory retrieval of the stored name fact works. However, the response stated "I don't have that information stored" for the profession, and the word "software engineer" does not appear anywhere in the content. Two assertions failed: (1) the Qdrant point payload does not contain both `Luke` AND `software engineer` (only "Luke" is present), and (2) the recall response content does not contain `software engineer`.

Input tokens: ~1500

Output tokens: ~500

Start (UTC): 2026-06-18T12:38:55Z

End (UTC): 2026-06-18T12:41:59Z

Duration: 00:03:04

---

## Additional tasks I did

- Re-ran the recall request via curl directly to capture the full response body (Bruno CLI does not dump the body to stdout by default).
- Scrolled all ascend_memory_* Qdrant collections (ascend_memory_1536, ascend_memory, ascend_memory_768) to confirm the single point is the only one stored for this user.
- Scrolled the full ascend_memory_1536 collection without filter to confirm no second point with "software engineer" exists under any key for this user.
