# Attach-sources: run tasks template

Spec: [../6-attach-sources-test.md](../6-attach-sources-test.md)

Copy this file to `runs/<UTC-timestamp>_6-attach-sources-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version) — 3.4.0
- [x] ascend-ai-agent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] Qdrant `/healthz` returns HTTP 200
- [x] Object store `curl -fsS http://localhost:9070/_floci/health` returns HTTP 200 with `"s3":"running"`
- [x] Postgres responds to `SELECT 1` with a row
- [x] Fixture `pierogi-recipe.docx` exists under `apps/ascend-agent/e2e/fixtures/`

### Reset state

Step 1 uploads three objects, so the reset covers the same three keys as the Post-run cleanup.

- [x] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/pierogi-recipe.docx"` returned HTTP 204
- [x] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/banana-price-poland.pdf"` returned HTTP 204
- [x] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/markdown/markdown-canary.md"` returned HTTP 204
- [x] Removed `int_metadata_store` rows for all three keys (pierogi, banana, markdown-canary) — DELETE 0 (already clean)
- [x] Wiped Qdrant points for all three `source` values in collection `ascendai-1536` — acknowledged
- [x] Truncated `chat_history` rows for user `frostyAttachSourcesTest` — DELETE 0 (already clean)
- [x] Deleted Redis key `chat:frostyAttachSourcesTest`
- [x] Deleted Redis key `user:frostyAttachSourcesTest:instructions`

### Run

- [x] Step 1: sent `rag-ingestion-upload.yml`, HTTP 200
- [x] Step 2: sent `rag-ingestion-run.yml`, HTTP 200 with `indexed >= 1`
- [x] Step 3: sent `attach-sources-prompt.yml`, HTTP 200
- [x] Step 4: captured `response.sources[0].downloadUrl`, issued GET against it

### Expected

- [x] Step 1: response `uploaded` field includes `documents/pierogi-recipe.docx`
- [x] Step 2: response `indexed >= 1` and `failed == 0` — indexed=3, failed=0
- [x] Step 3: response body has a `sources` array with at least 1 entry — 1 entry
- [x] Step 3: first entry has non-empty `name`, `mimeType`, `downloadUrl`, `expiresAt` — name=pierogi-recipe.docx, mimeType=application/octet-stream, expiresAt=2026-09-10T08:07:07.260283449Z
- [x] Step 3: `downloadUrl` host portion equals `localhost:9070`, NOT `host.docker.internal:9070` — verified `http://localhost:9070`
- [x] Step 4: HTTP 200, downloaded file non-empty — 13563 bytes, identified as "Microsoft Word 2007+" (.docx)

### Post-run cleanup

Run regardless of Run-step verdict (idempotent; honours Group A hermetic contract). Step 1 writes three objects, so all three come out again here.

- [x] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/pierogi-recipe.docx"` returned HTTP 204
- [x] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/banana-price-poland.pdf"` returned HTTP 204
- [x] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/markdown/markdown-canary.md"` returned HTTP 204
- [x] Deleted `int_metadata_store` rows for all three keys (pierogi, banana, markdown-canary) — DELETE 3
- [x] Wiped Qdrant points for `documents/pierogi-recipe.docx`, `documents/banana-price-poland.pdf` and `markdown/markdown-canary.md` in collection `ascendai-1536` — acknowledged
- [x] Truncated `chat_history` rows for `frostyAttachSourcesTest` + deleted Redis key `chat:frostyAttachSourcesTest` — DELETE 2 rows, Redis key deleted
- [x] Deleted Redis key `user:frostyAttachSourcesTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyAttachSourcesTest` returned `{"status":"success", ...}`

### Verdict

- [x] Verdict: PASS

## Result summary

All five Expected assertions held. Step 1 (`rag-ingestion-upload.yml`) returned HTTP 200 with `uploaded` including `documents/pierogi-recipe.docx` and no failures. Step 2 (`rag-ingestion-run.yml`) returned HTTP 200 with `indexed=3, failed=0`. Step 3 (`attach-sources-prompt.yml`) returned HTTP 200 with a `sources[]` array of exactly 1 entry, all required fields (`name`, `mimeType`, `downloadUrl`, `expiresAt`) non-empty, and the `downloadUrl` host portion verified as `http://localhost:9070` (not `host.docker.internal:9070`), proving the `app.s3.public-endpoint` override is active under the docker profile. Step 4 followed the presigned `downloadUrl` with a plain `curl`, got HTTP 200, and the downloaded 13563-byte payload was identified as a valid "Microsoft Word 2007+" document, matching the original fixture size and the `sizeBytes` field in the response. Reset and Post-run cleanup both completed against all three shared object-store keys, Qdrant points, Postgres rows, Redis keys, and AscendMemory points for `frostyAttachSourcesTest`, leaving the bucket, metadata store, and vector store as the spec found them.

Input tokens: ~52000

Output tokens: ~3800

Start (UTC): 2026-09-10T07:49:32Z

End (UTC): 2026-09-10T07:52:57Z

Duration: 00:03:25

---

## Additional tasks I did

- Saved Bruno's JSON-format output and the step-4 downloaded payload to the scratchpad directory (`--output` flag, `curl -o`) rather than `/tmp` per this session's environment instructions, since `/tmp` on this Windows/Git-Bash host is not a reliable location. Deleted all of them (`rag-upload-result.json`, `rag-ingestion-run-result.json`, `attach-sources-prompt-result.json`, `attach-sources-payload`) after extracting the evidence needed for the Expected assertions; none of this is spec-owned persisted state, so it required no entry in the spec's own Reset or Post-run cleanup sections.
- Ran `rag-ingestion-upload.yml` twice (once without capturing output, once with `--output`/`--format json` to extract the response body for the `uploaded` assertion) because the plain run doesn't print the response body and the spec requires verifying it, not just the HTTP status. The second run is idempotent against the object store per the spec's own note ("The other two uploads are idempotent against the object store"), so no extra reset was needed.
