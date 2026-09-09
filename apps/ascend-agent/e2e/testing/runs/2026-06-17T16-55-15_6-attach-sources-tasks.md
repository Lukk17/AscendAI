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
- [x] Dropped `documents/pierogi-recipe.docx` from MinIO (object did not exist — clean state confirmed)
- [x] Removed `int_metadata_store` rows for the pierogi fixture
- [x] Wiped Qdrant points for `documents/pierogi-recipe.docx`
- [x] Truncated `chat_history` rows for user `frostyAttachSourcesTest`
- [x] Deleted Redis key `chat:frostyAttachSourcesTest`

### Run

- [x] Step 1: sent `rag-ingestion-upload.yml`, HTTP 200
- [x] Step 2: sent `rag-ingestion-run.yml`, HTTP 200 with `indexed >= 1`
- [x] Step 3: sent `attach-sources-prompt.yml`, HTTP 200 (via minimax — anthropic returned 502 on known MCP tool-name defect)
- [x] Step 4: captured `response.sources[0].downloadUrl`, issued GET against it

### Expected

- [x] Step 1: response `uploaded` field includes `documents/pierogi-recipe.docx`
- [x] Step 2: response `indexed >= 1` and `failed == 0`
- [x] Step 3: response body has a `sources` array with at least 1 entry
- [x] Step 3: first entry has non-empty `name`, `mimeType`, `downloadUrl`, `expiresAt`
- [x] Step 3: `downloadUrl` host portion equals `localhost:9070`, NOT `host.docker.internal:9070`
- [x] Step 4: HTTP 200, downloaded file non-empty

### Post-run cleanup

Run regardless of Run-step verdict (idempotent; honours Group A hermetic contract).

- [x] Dropped `documents/pierogi-recipe.docx` from MinIO
- [x] Deleted `int_metadata_store` row for the pierogi key
- [x] Wiped Qdrant points for `documents/pierogi-recipe.docx` in collection `ascendai-1536`
- [x] Truncated `chat_history` rows for `frostyAttachSourcesTest` + deleted Redis key `chat:frostyAttachSourcesTest`

### Verdict

- [x] Verdict: PASS

## Result summary

All six Expected assertions passed. Step 1 (upload) returned HTTP 200 with `uploaded` containing `documents/pierogi-recipe.docx`. Step 2 (ingestion run) returned HTTP 200 with `indexed: 3, failed: 0`. Step 3 (attach-sources prompt) was first attempted with provider=anthropic, which returned 502 (`AI provider error: 400`) matching the known MCP tool-name defect; it was retried with provider=minimax/model=MiniMax-M2.7 and returned HTTP 200 with a `sources` array containing one entry (`pierogi-recipe.docx`, mimeType=`application/octet-stream`, expiresAt non-empty), and the `downloadUrl` host portion was `localhost:9070` (not `host.docker.internal:9070`), confirming the `app.s3.public-endpoint` override is active. Step 4 followed the presigned URL and received HTTP 200 with a 13,563-byte .docx payload matching the fixture size. Post-run cleanup removed all state written by this run.

Input tokens:

Output tokens:

Start (UTC): 2026-06-17T16:55:18Z

End (UTC): 2026-06-17T16:59:58Z

Duration: 00:04:40

---

## Additional tasks I did

- Step 3 first attempted with the Bruno file's declared provider=anthropic/model=claude-sonnet-4-6. It returned HTTP 502 with body `"AI provider error: 400 -"`. Per caller context (known MCP tool-name defect with Anthropic), the step was retried via direct curl with provider=minimax/model=MiniMax-M2.7, which succeeded with HTTP 200 and returned the expected sources array.
- Step 3 retry used curl directly instead of bru (to avoid editing the Bruno file, which is outside the write boundary). The request payload, headers, and user-id were identical to the Bruno file; only provider and model fields differed.
