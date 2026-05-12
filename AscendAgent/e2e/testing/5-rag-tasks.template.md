# RAG — run tasks template

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
- [ ] MinIO `mc` client present (`mc --version` returns a version)
- [ ] Fixtures `markdown-canary.md`, `banana-price-poland.pdf`, `pierogi-recipe.docx` all exist under `AscendAgent/e2e/fixtures/`

### Reset state

- [ ] Registered MinIO alias (`mc alias set ascend ...`)
- [ ] Dropped all objects in MinIO `knowledge-base` bucket
- [ ] Truncated Postgres `int_metadata_store` table
- [ ] Wiped Qdrant `ascendai-*` points for the three fixture sources

### Run

- [ ] Step 1 — sent `rag-ingestion-upload.yml` and waited for HTTP 200 with three uploaded keys
- [ ] Step 2 — sent `rag-ingestion-run.yml` and waited for HTTP 200 with `indexed >= 3`
- [ ] Step 3a — sent `rag-prompt.yml` for the markdown-canary prompt
- [ ] Step 3b — enabled the next `prompt=` row, sent `rag-prompt.yml` for the banana-price prompt
- [ ] Step 3c — enabled the next `prompt=` row, sent `rag-prompt.yml` for the pierogi-recipe prompt

### Expected

- [ ] Step 1: response body lists three uploaded keys (one markdown, two documents)
- [ ] Step 1: `mc ls` shows `markdown-canary.md` under `markdown/` and the two other files under `documents/`
- [ ] Step 2: response body has `indexed` ≥ 3, `failed` = 0
- [ ] Step 2: AscendAgent log shows three `Processing ... stream for file: ...` lines and three `Split into N chunks` lines
- [ ] Step 3a: response `content` contains the canary phrase from the fixture
- [ ] Step 3b: response `content` contains the price quote from the fixture
- [ ] Step 3c: response `content` mentions `30 minutes` (rest time from the recipe)
- [ ] For each of step 3a/b/c: AscendAgent log shows `[RagRetrievalService] Retrieval: <k>/<N> candidates above threshold=<t> - scores=[...], inject=YES` with the source matching the prompt

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary

<!-- One short paragraph: what happened, key evidence, anything noteworthy. -->

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
