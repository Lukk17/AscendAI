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

Check Postgres responds. Run inside the `postgres` container because `psql` is not on the host shell in this dev environment.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "SELECT 1"
```

Expect a row with `1` in the output.

Check the MinIO `mc` client is available inside the `minio` container (it ships with the image).

```bash
docker exec minio mc --version
```

Expect a version string.

Check the three fixtures exist.

```bash
ls AscendAgent/e2e/fixtures/markdown-canary.md AscendAgent/e2e/fixtures/banana-price-poland.pdf AscendAgent/e2e/fixtures/pierogi-recipe.docx
```

Expect all three paths to print.

## Reset state

Register the MinIO alias inside the `minio` container (idempotent). Credentials are the single source of truth in `docker-compose.yaml` under the `minio` service env (`MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`). The command below runs through `sh -c` so the env vars expand *inside* the container — the host shell doesn't have them set.

```bash
docker exec minio sh -c 'mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"'
```

Drop all objects from the `knowledge-base` bucket so the upload step is fresh.

```bash
docker exec minio mc rm --recursive --force local/knowledge-base
```

Truncate the Spring Integration metadata store so the run step does not classify files as already-ingested via stored ETags.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "TRUNCATE TABLE int_metadata_store;"
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

After step 1 the Bruno output shows HTTP 200.

After step 1 the response body's `uploaded` field lists exactly three keys: one under `markdown/` and two under `documents/`.

After step 1 `docker exec minio mc ls local/knowledge-base/markdown/` lists `markdown-canary.md`.

After step 1 `docker exec minio mc ls local/knowledge-base/documents/` lists both `banana-price-poland.pdf` and `pierogi-recipe.docx`.

After step 2 the Bruno output shows HTTP 200.

After step 2 the response body has `indexed` ≥ 3 and `failed` = 0.

After step 3a (markdown-canary prompt) the response body's `content` field contains the canary phrase from the markdown fixture (e.g. `PURPLE-MOOSE-42`).

After step 3b (banana-price prompt) the response body's `content` field contains a numeric price in PLN that matches the PDF fixture (e.g. `6.49`).

After step 3c (pierogi-recipe prompt) the response body's `content` field contains the rest time from the DOCX fixture (`30 minutes`).

For each of step 3a/3b/3c the response is NOT a refusal like "I don't have that document" — a refusal means the RAG retrieval did not inject the relevant chunk into the prompt.

## Fixtures

- `AscendAgent/e2e/fixtures/markdown-canary.md`
- `AscendAgent/e2e/fixtures/banana-price-poland.pdf`
- `AscendAgent/e2e/fixtures/pierogi-recipe.docx`
