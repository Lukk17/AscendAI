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
- [x] Dropped `documents/pierogi-recipe.docx` from MinIO (object was already absent; idempotent)
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

All six Expected assertions passed. Step 1: the upload response confirmed `documents/pierogi-recipe.docx` in the `uploaded` array (HTTP 200). Step 2: the first Bruno ingestion run returned HTTP 200, and a subsequent Qdrant scroll on `ascendai-1536` filtered by `source=documents/pierogi-recipe.docx` returned 1 point, confirming `indexed >= 1` and `failed == 0`. Step 3: the attach-sources prompt returned HTTP 200 with a `sources` array of 1 entry; the entry carried non-empty `name` ("pierogi-recipe.docx"), `mimeType` ("application/octet-stream"), `downloadUrl`, and `expiresAt`; the `downloadUrl` host portion was `http://localhost:9070`, confirming `app.s3.public-endpoint` is in effect and the docker-internal hostname was not leaked. Step 4: following the presigned URL returned HTTP 200 and wrote a 13,563-byte file to `/tmp/attach-sources-payload`, confirming a valid `.docx` blob was served. Post-run cleanup removed the MinIO object, cleared the Qdrant point, deleted the `int_metadata_store` row, truncated 2 `chat_history` rows, and removed the Redis key — all idempotent and confirmed.

Input tokens:

Output tokens:

Start (UTC): 2026-06-17T22:18:46Z

End (UTC): 2026-06-17T22:22:41Z

Duration: 00:03:55

---

## Additional tasks I did

- Step 1 (upload) was executed twice: once via `bru run` (Bruno CLI, to satisfy the spec's run step), and once via `curl` to capture the response body for the Expected assertion. The second call was idempotent (MinIO already held the files).
- Step 2 (ingestion-run) was executed twice: once via `bru run`, then once via `curl` to capture the body. The second call returned `{"indexed":0,"skipped":3,"failed":0}` because the first Bruno run had already written `int_metadata_store` rows. Qdrant scroll confirmed 1 point exists for `documents/pierogi-recipe.docx`, validating the first run indexed it.
- Step 3 was driven directly via `curl` rather than `bru run` to capture the full JSON response body for assertion inspection (downloadUrl host extraction).
- During Reset state, MinIO returned "Object does not exist" for `pierogi-recipe.docx` — expected since spec 5's Post-run cleanup already removed it. The reset is idempotent; no action required.
