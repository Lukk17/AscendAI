# Attach-sources: run tasks template

Spec: [6-attach-sources-test.md](6-attach-sources-test.md)

Copy this file to `runs/<UTC-timestamp>_6-attach-sources-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version) — 3.4.0
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] Qdrant `/healthz` returns HTTP 200
- [x] MinIO `/minio/health/live` returns HTTP 200
- [x] Postgres responds to `SELECT 1` with a row
- [x] MinIO `mc` client present inside the `minio` container
- [x] Fixture `pierogi-recipe.docx` exists under `AscendAgent/e2e/fixtures/`

### Reset state

- [x] Registered MinIO alias `local` inside the container
- [x] Dropped `documents/pierogi-recipe.docx` from MinIO
- [x] Removed `int_metadata_store` rows for the pierogi fixture (DELETE 1)
- [x] Wiped Qdrant points for `documents/pierogi-recipe.docx` — acknowledged
- [x] Truncated `chat_history` rows for user `frostyAttachSourcesTest` (DELETE 4)
- [x] Deleted Redis key `chat:frostyAttachSourcesTest` (returned 1)

### Run

- [x] Step 1: sent `rag-ingestion-upload.yml`, HTTP 200 — `uploaded` includes `documents/pierogi-recipe.docx`
- [x] Step 2 (pre-guard): DELETE FROM int_metadata_store LIKE '%pierogi-recipe.docx%' — DELETE 0
- [x] Step 2: sent `rag-ingestion-run.yml`, HTTP 200 with `indexed: 1, failed: 0`
- [x] Step 3: sent `attach-sources-prompt.yml`, HTTP 200
- [x] Step 4: captured `response.sources[2].downloadUrl` (pierogi-recipe.docx), issued GET against it — 13563 bytes

### Expected

- [x] Step 1: response `uploaded` field includes `documents/pierogi-recipe.docx`
- [x] Step 2: response `indexed >= 1` (= 1) and `failed == 0`
- [x] Step 3: response body has a `sources` array with at least 1 entry — 3 entries returned
- [x] Step 3: first entry has non-empty `name`, `mimeType`, `downloadUrl`, `expiresAt` — confirmed all fields present
- [x] Step 3: `downloadUrl` host portion equals `localhost:9070`, NOT `host.docker.internal:9070` — confirmed `http://localhost:9070/...`
- [x] Step 4: HTTP 200, downloaded file non-empty — 13563 bytes

### Verdict

- [x] Verdict: PASS

## Result summary

pierogi-recipe.docx uploaded, re-ingested (indexed=1), and the attach-sources prompt returned it in the sources array. All 3 sources had localhost:9070 URLs. Presigned download returned 13563 bytes matching the MinIO sizeBytes.

Input tokens: n/a (Bruno CLI)

Output tokens: n/a (Bruno CLI)

Start (UTC): 2026-05-23T23:17:13Z

End (UTC): 2026-05-23T23:20:24Z

Duration: 00:03:11

---

## Additional tasks I did

- Applied spec's belt-and-braces pre-run DELETE for int_metadata_store before Step 2.
- Note: sources array returned 3 entries (pierogi-recipe.docx plus the two dedup fixtures left in Qdrant from test 5); spec requires >=1 and presence of pierogi-recipe.docx — both satisfied.
