# Attach-sources: run tasks template

Spec: [../6-attach-sources-test.md](../6-attach-sources-test.md)

Copy this file to `runs/<UTC-timestamp>_6-attach-sources-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version) — 3.4.0
- [x] ascend-ai-agent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] Qdrant `/healthz` returns HTTP 200 — "healthz check passed"
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
- [x] Deleted Redis key `chat:frostyAttachSourcesTest` — 0 (already absent)
- [x] Deleted Redis key `user:frostyAttachSourcesTest:instructions` — 0 (already absent)

### Run

- [x] Step 1: sent `rag-ingestion-upload.yml`, HTTP 200
- [x] Step 2: sent `rag-ingestion-run.yml`, HTTP 200 with `indexed >= 1` (indexed=3, failed=0)
- [x] Step 3: sent `attach-sources-prompt.yml`, HTTP 200
- [x] Step 4: captured `response.sources[0].downloadUrl`, issued GET against it — HTTP 200

### Expected

- [x] Step 1: response `uploaded` field includes `documents/pierogi-recipe.docx` (uploaded: markdown/markdown-canary.md, documents/banana-price-poland.pdf, documents/pierogi-recipe.docx; failures: [])
- [x] Step 2: response `indexed >= 1` and `failed == 0` (indexed=3, skipped=2, failed=0)
- [x] Step 3: response body has a `sources` array with at least 1 entry (3 entries)
- [x] Step 3: first entry has non-empty `name`, `mimeType`, `downloadUrl`, `expiresAt` (name="Babcia Helena's pierogi recipe (e2e dedup fixture)", mimeType="application/octet-stream", expiresAt="2026-09-09T17:49:17.928223522Z")
- [x] Step 3: `downloadUrl` host portion equals `localhost:9070`, NOT `host.docker.internal:9070` — `echo "<url>" | grep -oE 'https?://[^/]+'` printed `http://localhost:9070`
- [x] Step 4: HTTP 200, downloaded file non-empty (3744 bytes)

### Post-run cleanup

Run regardless of Run-step verdict (idempotent; honours Group A hermetic contract). Step 1 writes three objects, so all three come out again here.

- [x] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/pierogi-recipe.docx"` returned HTTP 204
- [x] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/banana-price-poland.pdf"` returned HTTP 204
- [x] `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/markdown/markdown-canary.md"` returned HTTP 204
- [x] Deleted `int_metadata_store` rows for all three keys (pierogi, banana, markdown-canary) — DELETE 3
- [x] Wiped Qdrant points for `documents/pierogi-recipe.docx`, `documents/banana-price-poland.pdf` and `markdown/markdown-canary.md` in collection `ascendai-1536` — acknowledged
- [x] Truncated `chat_history` rows for `frostyAttachSourcesTest` + deleted Redis key `chat:frostyAttachSourcesTest` — DELETE 2, Redis DEL=1
- [x] Deleted Redis key `user:frostyAttachSourcesTest:instructions` — DEL=1
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyAttachSourcesTest` returned `{"status":"success", ...}`

### Verdict

- [x] Verdict: PASS

## Result summary

All five Expected assertions held. Step 1 uploaded the three RAG fixtures with `documents/pierogi-recipe.docx` present in `uploaded` and no failures. Step 2 indexed 3 objects with 0 failures. Step 3 returned HTTP 200 with a `sources[]` array of 3 entries, each with non-empty `name`/`mimeType`/`downloadUrl`/`expiresAt`; the first entry's `downloadUrl` host portion was verified via `grep -oE 'https?://[^/]+'` to be exactly `http://localhost:9070`, confirming the `app.s3.public-endpoint` override is in effect under the docker profile. Step 4 followed the presigned URL and received HTTP 200 with a non-empty 3744-byte payload. Bruno's own embedded test scripts on all three requests passed as well.

Input tokens:

Output tokens:

Start (UTC): 2026-09-09T17:31:28Z

End (UTC): 2026-09-09T17:36:48Z

Duration: 00:05:20

---

## Additional tasks I did

- Environmental observation, not a spec violation by this run: step 3's response `sources[]` contained 3 entries, not the 1 (`pierogi-recipe.docx`) the spec's Reset/Post-run-cleanup accounting implies. Two of the three (`markdown/dedup-pierogi-helena.md`, `markdown/dedup-pierogi-grandma.md`) are spec 7's own fixtures (`7-rag-dedup-test.md`), which had not yet run in this sweep (group order 5 -> 6 -> 7) and per the hermetic contract spec 6 does not reset or clean spec 7's territory. Their presence means a prior sweep's spec-7 run (before this session) did not complete its own Post-run cleanup and left `dedup-pierogi-*` behind in the shared `knowledge-base` bucket / `ascendai-1536` Qdrant collection. This did not break any Expected assertion here: `sources[0]` still had all required non-empty fields and a correct `localhost:9070` host, and the downloaded payload in step 4 was non-empty. It did mean the step-4 payload was `dedup-pierogi-helena.md` (a markdown fixture) rather than `pierogi-recipe.docx` (the `.docx` blob the spec's Expected section parenthetically describes) — both fixtures happen to describe the same "Babcia Helena" 30-minute-rest pierogi recipe, so this had no effect on the literal, verifiable assertion (HTTP 200, non-empty file). Flagging so spec 7's next run confirms it completes its own Post-run cleanup, and so a future sweep isn't misread as spec 6 leaking into spec 7's territory.
- Extracted the Bruno JSON response bodies for verification (via `-o <scratchpad>/stepN.json -f json` and a Python one-liner) rather than relying on Bruno's console summary alone, since the spec's Expected section requires inspecting specific response fields (`uploaded`, `indexed`, `sources[]` entries). Scratchpad files were deleted after use.
- No commands were blocked by the permission classifier during this run.
