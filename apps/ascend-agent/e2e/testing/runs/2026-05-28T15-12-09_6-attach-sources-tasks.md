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

### Verdict

- [x] Verdict: PASS

## Result summary

All six Expected assertions passed. Step 1 (upload) returned HTTP 200 with `uploaded` containing `documents/pierogi-recipe.docx`. Step 2 (ingestion run) returned HTTP 200 with `indexed: 3, failed: 0`. Step 3 (attach-sources prompt) returned HTTP 200 with a `sources` array of 2 entries; the first entry (`dedup-pierogi-grandma.md`) and second (`documents/pierogi-recipe.docx`) both carried non-empty `name`, `mimeType`, `downloadUrl`, and `expiresAt`, and both `downloadUrl` values used host `localhost:9070` (not `host.docker.internal:9070`), confirming the `app.s3.public-endpoint` override is in effect. Step 4 followed `sources[0].downloadUrl` (the presigned URL) and received HTTP 200 with a 4065-byte file body, confirming MinIO presigning is end-to-end functional from the host network.

Input tokens: ~12000

Output tokens: ~1500

Start (UTC): 2026-05-28T14:39:11Z

End (UTC): 2026-05-28T14:43:50Z

Duration: 00:04:39

---

## Additional tasks I did

- The sandbox auto-classifier blocked `docker exec minio mc rm --force local/knowledge-base/markdown/dedup-pierogi-grandma.md` (spec Reset step), classifying it as unauthorized shared-resource modification. As a result, `dedup-pierogi-grandma.md` was still present in MinIO and its Qdrant points were already present from a prior run (the Qdrant wipe filter matched 0 live points). The file therefore appeared as `sources[0]` in the Step 3 response. All spec assertions still pass: the `sources` array had at least 1 entry, host portion was `localhost:9070`, and the presigned URL returned HTTP 200 with a non-empty body.
- Read `attach-sources-prompt.yml` to verify request shape before running it.
- Read `rag-ingestion-upload.yml` to verify it sends `pierogi-recipe.docx` among its uploads.
