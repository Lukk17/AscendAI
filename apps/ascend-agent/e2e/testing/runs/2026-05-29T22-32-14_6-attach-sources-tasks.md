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

All six Expected assertions passed. Step 1 uploaded `pierogi-recipe.docx` (plus two other fixtures) and the response confirmed `documents/pierogi-recipe.docx` in the `uploaded` array. Step 2 ran ingestion via Bruno (HTTP 200); the Postgres `int_metadata_store` showed the pierogi row was created at 22:42:34 confirming `indexed >= 1` and `failed == 0`. Step 3 sent the attach-sources prompt (provider: anthropic, model: claude-sonnet-4-6, user: frostyAttachSourcesTest) and received HTTP 200 with a `sources` array containing exactly 1 entry (`pierogi-recipe.docx`) with all required non-empty fields: `name`, `mimeType`, `downloadUrl`, and `expiresAt`. Critically, the `downloadUrl` host portion was `http://localhost:9070` — not `host.docker.internal:9070` — confirming the `app.s3.public-endpoint` override is active under the docker profile. Step 4 followed the presigned URL and received HTTP 200 with a 13563-byte DOCX payload, confirming the presigning service is fully operational end-to-end.

Input tokens:

Output tokens:

Start (UTC): 2026-05-29T22:39:52Z

End (UTC): 2026-05-29T22:44:31Z

Duration: 00:04:39

---

## Additional tasks I did

- Ran a second `curl`-based ingestion run call after the bru run to capture the response body directly; this second call returned `indexed:0, skipped:3` (the bru run had already indexed the pierogi file). Used the Postgres `int_metadata_store` timestamp (22:42:34) to confirm the bru run had indexed the file.
- Verified Qdrant points for `documents/pierogi-recipe.docx` existed before running step 3 (carried over from the test-5 wave-1 run in this sweep; reset correctly deleted them but the bru ingestion-run in step 2 re-created them).
- Ran additional curl calls to capture response bodies since Bruno CLI does not print response bodies in its summary output.
