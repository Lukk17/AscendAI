# RAG — e2e test

## What this verifies

- Documents uploaded to the ingestion endpoint land in MinIO under the right folder prefix (`markdown/` for Markdown, `documents/` for others).
- The manual ingestion run reads them, splits into chunks, embeds, and writes points to Qdrant.
- A later prompt retrieves the relevant chunk and produces an answer grounded in the uploaded content.

Three document formats are exercised: Markdown, PDF, DOCX.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string. If the command is not found, install it with `npm install -g @usebruno/cli`.

Check the AscendAgent health endpoint.

```bash
curl -fsS http://localhost:9917/actuator/health
```

Expect HTTP 200 with `{"status":"UP"}`.

Check Docling Serve is reachable.

```bash
curl -fsS http://localhost:5001/health
```

Expect HTTP 200.

Check Unstructured API is reachable.

```bash
curl -fsS -X POST http://localhost:9080/general/v0/general
```

Expect HTTP 4xx (the bare POST without a file is rejected, but it proves the service is up).

Check Qdrant is reachable.

```bash
curl -fsS http://localhost:6333/healthz
```

Expect HTTP 200.

Check MinIO is reachable.

```bash
curl -fsS http://localhost:9070/minio/health/live
```

Expect HTTP 200.

Check Postgres responds.

```bash
psql "postgresql://postgres:local@localhost:5432/ascend_ai" -c "SELECT 1"
```

Expect a row with `1` in the output.

Check the MinIO `mc` client is installed.

```bash
mc --version
```

Expect a version string. If not installed, install it from MinIO's documentation site.

Check the three fixtures exist.

```bash
ls AscendAgent/e2e/fixtures/markdown-canary.md AscendAgent/e2e/fixtures/banana-price-poland.pdf AscendAgent/e2e/fixtures/pierogi-recipe.docx
```

Expect all three paths to print.

## Reset state

Register the MinIO alias once per shell (idempotent).

```bash
mc alias set ascend http://localhost:9070 minioadmin minioadmin
```

Drop all objects from the `knowledge-base` bucket so the upload step is fresh.

```bash
mc rm --recursive --force ascend/knowledge-base
```

Truncate the Spring Integration metadata store so the run step does not classify files as already-ingested via stored ETags.

```bash
psql "postgresql://postgres:local@localhost:5432/ascend_ai" -c "TRUNCATE TABLE int_metadata_store;"
```

Wipe RAG points for the three fixtures from Qdrant.

```bash
curl -X POST http://localhost:6333/collections/ascendai-1536/points/delete -H "Content-Type: application/json" -d '{"filter":{"must":[{"key":"source","match":{"any":["markdown/markdown-canary.md","documents/banana-price-poland.pdf","documents/pierogi-recipe.docx"]}}]}}'
```

## Run

Step 1 — upload the three fixtures in one multipart request. Wait for HTTP 200 before continuing.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/rag-ingestion-upload.yml" --env ascend-local
```

Step 2 — trigger ingestion (no prefix → scans the whole bucket). Wait for HTTP 200 and a non-zero `indexed` count before continuing.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/rag-ingestion-run.yml" --env ascend-local
```

Step 3 — send the RAG prompt. The Bruno request saves three alternative `prompt=` rows on the same field; only one is enabled by default. Run the request once with the current default, then edit the YAML to enable the next prompt row (and disable the previous) and re-run. Do this once per fixture for full coverage.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/rag-prompt.yml" --env ascend-local
```

The three prompts saved in the request:
- `What is the Ascend canary phrase?` (markdown fixture)
- `What was the retail price of bananas in Poland in October 2026?` (PDF fixture)
- `How long should I rest the pierogi dough according to Babcia Helena's recipe?` (DOCX fixture)

## Expected

After step 1 the Bruno output shows HTTP 200 and the response body lists three uploaded keys under `markdown/` and `documents/`.

After step 1 `mc ls ascend/knowledge-base/markdown/` shows `markdown-canary.md` and `mc ls ascend/knowledge-base/documents/` shows both `banana-price-poland.pdf` and `pierogi-recipe.docx`.

After step 2 the Bruno output shows HTTP 200 and the response body has `indexed` ≥ 3, `failed` = 0.

After step 2 the AscendAgent log shows three `Processing ... stream for file: ...` lines and three `Split into N chunks` lines.

After each run of step 3 the Bruno output shows HTTP 200, the response `content` cites the relevant fixture (canary phrase like `PURPLE-MOOSE-42` / a price from the PDF / `30 minutes` from the recipe), and the AscendAgent log shows `[RagRetrievalService] Retrieval: <k>/<N> candidates above threshold=<t> - scores=[...], inject=YES` with the retrieved chunk's source matching the prompt.

## Fixtures

- `AscendAgent/e2e/fixtures/markdown-canary.md`
- `AscendAgent/e2e/fixtures/banana-price-poland.pdf`
- `AscendAgent/e2e/fixtures/pierogi-recipe.docx`
