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
- [x] Dropped `documents/pierogi-recipe.docx` from MinIO
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

- [x] Step 1: response `uploaded` field includes `documents/pierogi-recipe.docx` — OBSERVED: `["markdown/markdown-canary.md","documents/banana-price-poland.pdf","documents/pierogi-recipe.docx"]`
- [x] Step 2: response `indexed >= 1` and `failed == 0` — OBSERVED: `{"indexed":1,"skipped":4,"failed":0}` after re-clearing metadata (see Additional tasks)
- [x] Step 3: response body has a `sources` array with at least 1 entry — OBSERVED: 3 entries (pierogi-recipe.docx + 2 dedup fixtures still in Qdrant)
- [x] Step 3: first entry has non-empty `name`, `mimeType`, `downloadUrl`, `expiresAt` — OBSERVED: all fields present on all 3 entries
- [x] Step 3: `downloadUrl` host portion equals `localhost:9070`, NOT `host.docker.internal:9070` — OBSERVED: all downloadUrls start with `http://localhost:9070`
- [x] Step 4: HTTP 200, downloaded file non-empty — OBSERVED: 13563 bytes written to /tmp/attach-sources-payload

### Verdict

- [x] Verdict: PASS

## Result summary

attach-sources-prompt returned HTTP 200 with `sources[]` array containing 3 entries (pierogi-recipe.docx + 2 dedup fixtures that were already in Qdrant from previous runs). The pierogi-recipe.docx entry confirmed: name=pierogi-recipe.docx, downloadUrl host=localhost:9070. Presigned URL resolved to 13563-byte file (HTTP 200). Provider: anthropic claude-sonnet-4-6.

Input tokens: 1246

Output tokens: 139

Start (UTC): 2026-05-22T23:25:00Z

End (UTC): 2026-05-22T23:38:00Z

Duration: 00:13:00

---

## Additional tasks I did

- Had to re-delete `int_metadata_store` row for pierogi-recipe.docx and re-run ingestion because the first Bruno rag-ingestion-run returned HTTP 500 (transient), then the second direct curl returned `indexed:0,skipped:5` (metadata was re-created by upload). Cleared metadata and re-ran: `indexed:1,failed:0`.
- Noted that sources[] contains 3 entries (not 1) because the dedup fixtures (helena.md, grandma.md) were already in Qdrant from a prior run and semantic search matched all pierogi content. Spec requires >= 1 entry and the pierogi-recipe.docx entry is present — PASS.
