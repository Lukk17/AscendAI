# Attach-sources: run tasks template

Spec: [6-attach-sources-test.md](6-attach-sources-test.md)

Copy this file to `runs/<UTC-timestamp>_6-attach-sources-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [ ] Qdrant `/healthz` returns HTTP 200
- [ ] MinIO `/minio/health/live` returns HTTP 200
- [ ] Postgres responds to `SELECT 1` with a row
- [ ] MinIO `mc` client present inside the `minio` container
- [ ] Fixture `pierogi-recipe.docx` exists under `AscendAgent/e2e/fixtures/`

### Reset state

- [ ] Registered MinIO alias `local` inside the container
- [ ] Dropped `documents/pierogi-recipe.docx` from MinIO
- [ ] Removed `int_metadata_store` rows for the pierogi fixture
- [ ] Wiped Qdrant points for `documents/pierogi-recipe.docx`
- [ ] Truncated `chat_history` rows for user `frostyAttachSourcesTest`
- [ ] Deleted Redis key `chat:frostyAttachSourcesTest`

### Run

- [ ] Step 1: sent `rag-ingestion-upload.yml`, HTTP 200
- [ ] Step 2: sent `rag-ingestion-run.yml`, HTTP 200 with `indexed >= 1`
- [ ] Step 3: sent `attach-sources-prompt.yml`, HTTP 200
- [ ] Step 4: captured `response.sources[0].downloadUrl`, issued GET against it

### Expected

- [ ] Step 1: response `uploaded` field includes `documents/pierogi-recipe.docx`
- [ ] Step 2: response `indexed >= 1` and `failed == 0`
- [ ] Step 3: response body has a `sources` array with at least 1 entry
- [ ] Step 3: first entry has non-empty `name`, `mimeType`, `downloadUrl`, `expiresAt`
- [ ] Step 3: `downloadUrl` host portion equals `localhost:9070`, NOT `host.docker.internal:9070`
- [ ] Step 4: HTTP 200, downloaded file non-empty

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary



Input tokens:

Output tokens:

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
