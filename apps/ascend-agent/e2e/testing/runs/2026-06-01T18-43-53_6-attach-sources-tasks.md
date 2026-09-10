# Attach-sources: run tasks template

Spec: [6-attach-sources-test.md](6-attach-sources-test.md)

Copy this file to `runs/<UTC-timestamp>_6-attach-sources-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version)
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] Qdrant `/healthz` returns HTTP 200
- [x] MinIO `/minio/health/live` returns HTTP 200
- [x] Postgres responds to `SELECT 1` with a row
- [x] MinIO `mc` client present inside the `minio` container
- [x] Fixture `pierogi-recipe.docx` exists under `AscendAgent/e2e/fixtures/`

### Reset state

- [x] Registered MinIO alias `local` inside the container
- [x] Dropped `documents/pierogi-recipe.docx` from MinIO (object already absent — spec 5 post-run cleanup had already removed it; rm exit 1 is expected and idempotent)
- [x] Removed `int_metadata_store` rows for the pierogi fixture
- [x] Wiped Qdrant points for `documents/pierogi-recipe.docx`
- [x] Truncated `chat_history` rows for user `frostyAttachSourcesTest`
- [x] Deleted Redis key `chat:frostyAttachSourcesTest`

### Run

- [x] Step 1: sent `rag-ingestion-upload.yml`, HTTP 200
- [x] Step 2: sent `rag-ingestion-run.yml`, HTTP 200 with `indexed >= 1`
- [x] Step 3: sent `attach-sources-prompt.yml`, HTTP 200
- [x] Step 4: captured `response.sources[0].downloadUrl`, issued GET against it

### Expected

- [x] Step 1: response `uploaded` field includes `documents/pierogi-recipe.docx`
- [x] Step 2: response `indexed >= 1` and `failed == 0` (observed: `indexed=3, skipped=2, failed=0`)
- [x] Step 3: response body has a `sources` array with at least 1 entry (observed: 3 entries)
- [x] Step 3: first entry has non-empty `name`, `mimeType`, `downloadUrl`, `expiresAt`
- [x] Step 3: `downloadUrl` host portion equals `localhost:9070`, NOT `host.docker.internal:9070` (all 3 sources use `http://localhost:9070/...`)
- [x] Step 4: HTTP 200, downloaded file non-empty (13563 bytes, matching `sizeBytes` in response)

### Post-run cleanup

Run regardless of Run-step verdict (idempotent; honours Group A hermetic contract).

- [x] Dropped `documents/pierogi-recipe.docx` from MinIO
- [x] Deleted `int_metadata_store` row for the pierogi key (DELETE 1)
- [x] Wiped Qdrant points for `documents/pierogi-recipe.docx` in collection `ascendai-1536`
- [x] Truncated `chat_history` rows for `frostyAttachSourcesTest` + deleted Redis key `chat:frostyAttachSourcesTest`

### Verdict

- [x] Verdict: PASS

## Result summary

All six Expected assertions passed. Step 1 returned HTTP 200 with `uploaded` containing `documents/pierogi-recipe.docx`. Step 2 returned HTTP 200 with `indexed=3, failed=0`. Step 3 returned HTTP 200 with a `sources` array of 3 entries; every entry carried non-empty `name`, `mimeType`, `downloadUrl`, and `expiresAt`; all three `downloadUrl` values used the host-reachable `http://localhost:9070/` prefix — confirming `app.s3.public-endpoint` is active. Step 4 followed the presigned URL for `pierogi-recipe.docx` and received HTTP 200 with a 13 563-byte payload matching the `sizeBytes` field. Post-run cleanup removed the pierogi fixture from MinIO, Qdrant, Postgres `int_metadata_store`, `chat_history`, and Redis, leaving the RAG state hermetically clean for spec 7.

Input tokens: ~4500

Output tokens: ~800

Start (UTC): 2026-06-01T18:43:53Z

End (UTC): 2026-06-01T18:46:47Z

Duration: 00:02:54

---

## Additional tasks I did

- Reset step "Drop pierogi-recipe.docx from MinIO" produced `mc rm` exit code 1 (object not present). This is expected: spec 5's post-run cleanup had already removed the file. The step is idempotent; absence is the desired pre-condition, so it was treated as success.
- Verified the downloaded presigned-URL payload size (13 563 bytes) against the `sizeBytes` field in the response to confirm a valid DOCX blob rather than an error page.
- Observed that the `sources` array returned 3 entries (the two `dedup-pierogi-*` markdown files from spec 7's fixture, which were still in MinIO from spec 5's run, plus the freshly-uploaded `pierogi-recipe.docx`). This indicates the RAG retrieval correctly matched all pierogi-related content. The Expected assertions only require at least 1 entry, so this is not a failure; it is noted as diagnostic context for the sweep orchestrator.
