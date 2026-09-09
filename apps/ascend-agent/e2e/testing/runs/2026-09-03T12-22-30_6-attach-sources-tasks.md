# Attach-sources: run tasks template

Spec: [../6-attach-sources-test.md](../6-attach-sources-test.md)

Copy this file to `runs/<UTC-timestamp>_6-attach-sources-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version): 3.4.0
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] Qdrant `/healthz` returns HTTP 200
- [x] Object store `curl -fsS http://localhost:9070/_floci/health` returns HTTP 200 with `"s3":"running"`
- [x] Postgres responds to `SELECT 1` with a row
- [x] Fixture `pierogi-recipe.docx` exists under `AscendAgent/e2e/fixtures/`

### Reset state

- [x] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/pierogi-recipe.docx"` returned HTTP 204
- [x] Removed `int_metadata_store` rows for the pierogi fixture (0 rows, already clean from spec 5's post-run cleanup)
- [x] Wiped Qdrant points for `documents/pierogi-recipe.docx`
- [x] Truncated `chat_history` rows for user `frostyAttachSourcesTest` (0 rows)
- [x] Deleted Redis key `chat:frostyAttachSourcesTest`

### Run

- [x] Step 1: sent `rag-ingestion-upload.yml`, HTTP 200
- [x] Step 2: sent `rag-ingestion-run.yml`, HTTP 200 with `indexed >= 1`
- [x] Step 3: sent `attach-sources-prompt.yml`, HTTP 200
- [x] Step 4: captured `response.sources[0].downloadUrl`, issued GET against it

### Expected

- [x] Step 1: response `uploaded` field includes `documents/pierogi-recipe.docx`
- [x] Step 2: response `indexed >= 1` and `failed == 0` (indexed=3, failed=0)
- [x] Step 3: response body has a `sources` array with at least 1 entry (1 entry)
- [x] Step 3: first entry has non-empty `name`, `mimeType`, `downloadUrl`, `expiresAt` (`pierogi-recipe.docx`, `application/octet-stream`, presigned URL, `2026-09-03T12:46:50.437619864Z`)
- [x] Step 3: `downloadUrl` host portion equals `localhost:9070`, NOT `host.docker.internal:9070`
- [x] Step 4: HTTP 200, downloaded file non-empty (13563 bytes, identifies as Microsoft Word 2007+, matches source fixture size exactly)

### Post-run cleanup

Run regardless of Run-step verdict (idempotent; honours Group A hermetic contract).

- [x] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/pierogi-recipe.docx"` returned HTTP 204
- [x] Deleted `int_metadata_store` row for the pierogi key (1 row)
- [x] Wiped Qdrant points for `documents/pierogi-recipe.docx` in collection `ascendai-1536`
- [x] Truncated `chat_history` rows for `frostyAttachSourcesTest` (2 rows) + deleted Redis key `chat:frostyAttachSourcesTest`

### Verdict

- [x] Verdict: PASS

## Result summary

All Expected assertions held. Step 1 (re-using `rag-ingestion-upload.yml`, which uploads all three RAG-suite fixtures) returned HTTP 200 with `pierogi-recipe.docx` in the `uploaded` list. Step 2 ingestion returned HTTP 200 with `indexed=3`, `failed=0`. Step 3 sent the attach-sources prompt with `attachSources=true` and got HTTP 200 with a `sources` array of exactly one entry: `name="pierogi-recipe.docx"`, `mimeType="application/octet-stream"`, a non-empty `expiresAt`, and a `downloadUrl` whose host portion is exactly `http://localhost:9070` (not `host.docker.internal:9070`), confirming the `app.s3.public-endpoint` override is in effect under the docker profile. Step 4 followed that exact `downloadUrl` with a plain `curl -fsS` from the host network and got HTTP 200 with a 13563-byte payload that `file` identifies as "Microsoft Word 2007+", matching the original fixture's size byte for byte. This is the direct evidence closing task 1.3: a presigned URL produced by the live running agent resolves against the object store from the host network.

Input tokens: not available; the LLM-facing usage reported in the step 3 response body is `promptTokens=436`, `completionTokens=53` (model `claude-sonnet-4-6`, provider anthropic), but that is the tested system's own token accounting, not this runner's consumption, so it is left blank below.

Output tokens: not available (see note above).

Start (UTC): 2026-09-03T12:29:39Z

End (UTC): 2026-09-03T12:32:56Z

Duration: 00:03:17

---

## Additional tasks I did

- Reset state and Run step 1 reused the shared `rag-ingestion-upload.yml` Bruno request per the spec's own instructions, which uploads `markdown-canary.md` and `banana-price-poland.pdf` alongside `pierogi-recipe.docx`. This spec's Post-run cleanup section only deletes the `pierogi-recipe.docx` object, its metadata row, and its Qdrant points. After this run, `curl -fsS "http://localhost:9070/knowledge-base?list-type=2"` still lists `documents/banana-price-poland.pdf` and `markdown/markdown-canary.md`, and `docker exec postgres psql -U postgres -d ascend_ai -c "SELECT metadata_key FROM int_metadata_store WHERE metadata_key LIKE '%markdown-canary.md%' OR metadata_key LIKE '%banana-price-poland.pdf%';"` returns both rows. This is a spec defect (not a product defect): spec 6 writes state it does not own the cleanup contract for. It did not affect this run's Expected assertions, and it does not violate the file-write boundary (the leftover state is a side effect of running the spec's own prescribed commands, not an extra action I took). Flagging for the caller since spec 5 and spec 7 both declare a strict hermetic "only touch your own fixtures" contract that spec 6 breaks on the write side while only partially honouring on the cleanup side.
- Did not edit `docs/api/request/AscendAI/ascend-agent/testing/*.yml` at any point in this run; all three Bruno requests used by spec 6 (`rag-ingestion-upload.yml`, `rag-ingestion-run.yml`, `attach-sources-prompt.yml`) ran unmodified.
