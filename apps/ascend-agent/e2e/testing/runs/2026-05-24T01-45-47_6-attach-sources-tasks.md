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
- [x] Removed `int_metadata_store` rows for the pierogi fixture — DELETE 1
- [x] Wiped Qdrant points for `documents/pierogi-recipe.docx` — operation acknowledged
- [x] Truncated `chat_history` rows for user `frostyAttachSourcesTest` — DELETE 2
- [x] Deleted Redis key `chat:frostyAttachSourcesTest` — 1 key deleted

### Run

- [x] Step 1: sent `rag-ingestion-upload.yml`, HTTP 200
- [x] Step 2: sent `rag-ingestion-run.yml`, HTTP 200 with `indexed >= 1` (belt-and-braces DELETE before run; Qdrant confirmed 1 point for pierogi.docx after bru run)
- [x] Step 3: sent `attach-sources-prompt.yml`, HTTP 200
- [x] Step 4: captured `response.sources[2].downloadUrl` (pierogi.docx entry), issued GET against it

### Expected

- [x] Step 1: response `uploaded` field includes `documents/pierogi-recipe.docx` — confirmed in `uploaded` array
- [x] Step 2: response `indexed >= 1` and `failed == 0` — Qdrant count=1 for pierogi.docx confirmed
- [x] Step 3: response body has a `sources` array with at least 1 entry — 3 entries (pierogi.docx + two dedup markdown fixtures from Qdrant)
- [x] Step 3: first entry has non-empty `name`, `mimeType`, `downloadUrl`, `expiresAt` — all fields present
- [x] Step 3: `downloadUrl` host portion equals `localhost:9070`, NOT `host.docker.internal:9070` — confirmed for all 3 entries
- [x] Step 4: HTTP 200, downloaded file non-empty — 13563 bytes

### Verdict

- [x] Verdict: PASS

## Result summary

Attach-sources returned 3 sources (2 dedup markdown fixtures from a prior shared-bucket run + the pierogi.docx). The spec requires at least 1 entry with a valid presigned URL pointing to localhost:9070 — all entries satisfy that. The pierogi.docx source's `name` is `documents/pierogi-recipe.docx` (filename fallback; Unstructured did not extract a title from the .docx). Per spec: "note it but treat HTTP 200 + correct downloadUrl + presigned download as the pass criteria." Presigned URL returned 13563 bytes (valid .docx). Provider: Anthropic claude-sonnet-4-6.

Input tokens: 1252

Output tokens: 155

Start (UTC): 2026-05-24T02:02:10Z

End (UTC): 2026-05-24T02:08:30Z

Duration: 00:06:20

---

## Additional tasks I did

- Issued direct curl after bru run to capture full JSON response body for sources verification.
- Followed presigned URL for the pierogi.docx source entry (sources[2]) to verify 13563-byte non-empty download.
- Noted that the dedup markdown fixtures appear in sources because they were left in Qdrant from the prior test suite run (shared bucket). Test 7 reset clears them.
