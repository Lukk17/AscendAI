# RAG: run tasks template

Spec: [5-rag-test.md](5-rag-test.md)

Copy this file to `runs/<UTC-timestamp>_5-rag-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [ ] Docling Serve `/health` returns HTTP 200
- [ ] Unstructured API `POST /general/v0/general` returns HTTP 4xx (service up, request rejected for missing body)
- [ ] Qdrant `/healthz` returns HTTP 200
- [ ] MinIO `/minio/health/live` returns HTTP 200
- [ ] Postgres responds to `SELECT 1` with a row
- [ ] MinIO `mc` client present inside the `minio` container (`docker exec minio mc --version` returns a version)
- [ ] Fixtures `markdown-canary.md`, `banana-price-poland.pdf`, `pierogi-recipe.docx` all exist under `AscendAgent/e2e/fixtures/`

### Reset state

- [ ] Registered MinIO alias `local` inside the container (`docker exec minio sh -c 'mc alias set local ...'`)
- [ ] Dropped all objects in MinIO `knowledge-base` bucket
- [ ] Truncated Postgres `int_metadata_store` table
- [ ] Wiped Qdrant `ascendai-*` points for the three fixture sources

### Run

- [ ] Step 1: sent `rag-ingestion-upload.yml` and waited for HTTP 200 with three uploaded keys
- [ ] Step 2: sent `rag-ingestion-run.yml` and waited for HTTP 200 with `indexed >= 3`
- [ ] Step 3a: sent `rag-prompt.yml` for the markdown-canary prompt
- [ ] Step 3b: enabled the next `prompt=` row, sent `rag-prompt.yml` for the banana-price prompt
- [ ] Step 3c: enabled the next `prompt=` row, sent `rag-prompt.yml` for the pierogi-recipe prompt

### Expected

- [ ] Step 1: HTTP 200
- [ ] Step 1: response body's `uploaded` field lists exactly three keys (one under `markdown/`, two under `documents/`)
- [ ] Step 1: `docker exec minio mc ls local/knowledge-base/markdown/` lists `markdown-canary.md`
- [ ] Step 1: `docker exec minio mc ls local/knowledge-base/documents/` lists both `banana-price-poland.pdf` and `pierogi-recipe.docx`
- [ ] Step 2: HTTP 200
- [ ] Step 2: response body has `indexed` ≥ 3 and `failed` = 0
- [ ] Step 3a: response `content` contains the canary phrase from the markdown fixture (e.g. `PURPLE-MOOSE-42`)
- [ ] Step 3b: response `content` contains a numeric price in PLN matching the PDF fixture (e.g. `6.49`)
- [ ] Step 3c: response `content` contains `30 minutes` (rest time from the DOCX fixture)
- [ ] None of step 3a/3b/3c returned a refusal like "I don't have that document"

### Post-run cleanup

Run regardless of Run-step verdict (idempotent; honours Group A hermetic contract).

- [ ] Dropped this spec's three fixtures from MinIO (`markdown-canary.md`, `banana-price-poland.pdf`, `pierogi-recipe.docx`)
- [ ] Deleted `int_metadata_store` rows for the three fixtures
- [ ] Wiped Qdrant points for the three `source` values in collection `ascendai-1536`
- [ ] Truncated `chat_history` rows for `frostyRagTest` + deleted Redis key `chat:frostyRagTest`

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
