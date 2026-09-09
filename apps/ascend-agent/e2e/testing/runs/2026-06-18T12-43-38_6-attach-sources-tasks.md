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

All six Expected assertions passed. Step 1 (upload) returned HTTP 200 with `{"uploaded":["documents/pierogi-recipe.docx","markdown/markdown-canary.md","documents/banana-price-poland.pdf"],"failures":[]}`. Step 2 (ingestion run) returned HTTP 200; Qdrant scroll confirmed one point for `source=documents/pierogi-recipe.docx`. Step 3 (attach-sources prompt) returned HTTP 200 with a `sources` array containing one entry: `name=pierogi-recipe.docx`, `mimeType=application/octet-stream`, `downloadUrl=http://localhost:9070/knowledge-base/documents/pierogi-recipe.docx?...`, `expiresAt=2026-06-18T13:08:10.499244213Z`. The host portion of the `downloadUrl` is `http://localhost:9070`, confirming the `app.s3.public-endpoint` override is in effect. Step 4 (follow presigned URL) returned HTTP 200 and downloaded a 13,563-byte non-empty `.docx` file. Post-run cleanup removed the fixture from MinIO, deleted 1 `int_metadata_store` row, wiped Qdrant points, deleted 2 `chat_history` rows, and deleted the Redis key.

Input tokens: ~4500

Output tokens: ~800

Start (UTC): 2026-06-18T12:50:17Z

End (UTC): 2026-06-18T12:54:43Z

Duration: 00:04:26

---

## Additional tasks I did

- Re-ran the upload via curl (in addition to the Bruno run) to capture the full JSON response body and confirm `documents/pierogi-recipe.docx` appeared in the `uploaded` array, since Bruno CLI does not print the response body in its summary output.
- Re-ran ingestion via curl after the Bruno ingestion run; the second call returned `indexed=0, skipped=3` confirming the three files were already indexed by the Bruno run. Verified Qdrant scroll directly to confirm the pierogi point exists.
- The Reset state `mc rm` step returned "Object does not exist" (exit code 1) because the file was already absent from MinIO. This is the correct pre-condition; the step is idempotent by design.
- Used PowerShell to extract the `downloadUrl` from the response JSON because Python3 and the Bash node JSON parsing patterns were not available in the Git Bash environment on this Windows host.
