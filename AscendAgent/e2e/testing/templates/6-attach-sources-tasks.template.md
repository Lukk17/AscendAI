# Attach-sources: run tasks template

Spec: [../6-attach-sources-test.md](../6-attach-sources-test.md)

Copy this file to `runs/<UTC-timestamp>_6-attach-sources-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [ ] Qdrant `/healthz` returns HTTP 200
- [ ] Object store `curl -fsS http://localhost:9070/_floci/health` returns HTTP 200 with `"s3":"running"`
- [ ] Postgres responds to `SELECT 1` with a row
- [ ] Fixture `pierogi-recipe.docx` exists under `AscendAgent/e2e/fixtures/`

### Reset state

Step 1 uploads three objects, so the reset covers the same three keys as the Post-run cleanup.

- [ ] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/pierogi-recipe.docx"` returned HTTP 204
- [ ] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/banana-price-poland.pdf"` returned HTTP 204
- [ ] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/markdown/markdown-canary.md"` returned HTTP 204
- [ ] Removed `int_metadata_store` rows for all three keys (pierogi, banana, markdown-canary)
- [ ] Wiped Qdrant points for all three `source` values in collection `ascendai-1536`
- [ ] Truncated `chat_history` rows for user `frostyAttachSourcesTest`
- [ ] Deleted Redis key `chat:frostyAttachSourcesTest`
- [ ] Deleted Redis key `user:frostyAttachSourcesTest:instructions`

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

### Post-run cleanup

Run regardless of Run-step verdict (idempotent; honours Group A hermetic contract). Step 1 writes three objects, so all three come out again here.

- [ ] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/pierogi-recipe.docx"` returned HTTP 204
- [ ] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/banana-price-poland.pdf"` returned HTTP 204
- [ ] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/markdown/markdown-canary.md"` returned HTTP 204
- [ ] Deleted `int_metadata_store` rows for all three keys (pierogi, banana, markdown-canary)
- [ ] Wiped Qdrant points for `documents/pierogi-recipe.docx`, `documents/banana-price-poland.pdf` and `markdown/markdown-canary.md` in collection `ascendai-1536`
- [ ] Truncated `chat_history` rows for `frostyAttachSourcesTest` + deleted Redis key `chat:frostyAttachSourcesTest`
- [ ] Deleted Redis key `user:frostyAttachSourcesTest:instructions`
- [ ] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyAttachSourcesTest` returned `{"status":"success", ...}`

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
