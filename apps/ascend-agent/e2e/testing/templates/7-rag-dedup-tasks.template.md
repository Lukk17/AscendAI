# RAG dedup: run tasks template

Spec: [../7-rag-dedup-test.md](../7-rag-dedup-test.md)

Copy this file to `runs/<UTC-timestamp>_7-rag-dedup-tasks.md` before starting a run. Tick boxes as you go.

## Tasks

### Prerequisites

- [ ] Bruno CLI present
- [ ] ascend-ai-agent `/actuator/health` returns 200
- [ ] Qdrant `/healthz` returns 200
- [ ] Object store `curl -fsS http://localhost:9070/_floci/health` returns 200 with `"s3":"running"`
- [ ] Postgres responds to `SELECT 1`
- [ ] Fixtures `dedup-pierogi-helena.md` and `dedup-pierogi-grandma.md` exist

### Reset state

- [ ] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/markdown/dedup-pierogi-helena.md"` returned HTTP 204
- [ ] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/markdown/dedup-pierogi-grandma.md"` returned HTTP 204
- [ ] Removed `int_metadata_store` rows for both fixtures
- [ ] Wiped Qdrant points for both fixtures
- [ ] Truncated `chat_history` rows for user `frostyRagDedupTest`
- [ ] Deleted Redis key `chat:frostyRagDedupTest`
- [ ] Deleted Redis key `user:frostyRagDedupTest:instructions`

### Run

- [ ] Step 1: sent `rag-dedup-upload.yml`, HTTP 200
- [ ] Step 2: sent `rag-ingestion-run.yml` with `--env-var "ragMinIndexed=2"`, HTTP 200 with `indexed >= 2`
- [ ] Step 3: sent `rag-dedup-prompt.yml`, HTTP 200

### Expected

- [ ] Step 1: response `uploaded` includes both dedup fixture keys
- [ ] Step 2: `indexed >= 2`, `failed == 0`
- [ ] Step 3: response `sources` array has exactly 2 entries
- [ ] Step 3: one entry's `downloadUrl` contains `markdown/dedup-pierogi-helena.md`; the other's contains `markdown/dedup-pierogi-grandma.md` (in either order)
- [ ] Step 3: each entry's `name` carries the document's H1 title per the `SourceFile.name` contract (H1 when extractable, filename basename otherwise)
- [ ] Step 3 (soft): response `content` references both recipes (Helena/Maria, or sauerkraut/potato fillings)

### Post-run cleanup

Run regardless of Run-step verdict (idempotent; honours Group A hermetic contract).

- [ ] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/markdown/dedup-pierogi-helena.md"` returned HTTP 204
- [ ] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/markdown/dedup-pierogi-grandma.md"` returned HTTP 204
- [ ] Deleted `int_metadata_store` rows for the two dedup keys
- [ ] Wiped Qdrant points for both `source` values in collection `ascendai-1536`
- [ ] Truncated `chat_history` rows for `frostyRagDedupTest` + deleted Redis key `chat:frostyRagDedupTest`
- [ ] Deleted Redis key `user:frostyRagDedupTest:instructions`
- [ ] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyRagDedupTest` returned `{"status":"success", ...}`

### Verdict

- [ ] Verdict: PASS / FAIL

## Result summary



Input tokens:

Output tokens:

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did
