# Attach-sources: e2e test

## What this verifies

When `attachSources=true` is sent on a prompt request, the response carries a `sources[]` array whose `downloadUrl` (a) returns HTTP 200 from MinIO when followed from the host network, and (b) uses the host-reachable hostname `localhost:9070`, NOT the docker-internal `host.docker.internal:9070`. This proves end-to-end that the presigning service works AND that the `app.s3.public-endpoint` override is in effect under the docker profile.

The spec is hermetic: it owns its own MinIO key + Qdrant points + chat-history rows for the user-id `frostyAttachSourcesTest`. It re-uses the existing `pierogi-recipe.docx` fixture from the rag suite.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Check the AscendAgent health endpoint.

```bash
curl -fsS http://localhost:9917/actuator/health
```

Check Qdrant is reachable.

```bash
curl -fsS http://localhost:6333/healthz
```

Check MinIO is reachable.

```bash
curl -fsS http://localhost:9070/minio/health/live
```

Check Postgres responds.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "SELECT 1"
```

Check the MinIO `mc` client is available inside the `minio` container.

```bash
docker exec minio mc --version
```

Check the fixture exists.

```bash
ls AscendAgent/e2e/fixtures/pierogi-recipe.docx
```

## Reset state

Register the MinIO alias inside the `minio` container (idempotent).

```bash
docker exec minio sh -c 'mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"'
```

Drop the `pierogi-recipe.docx` object from MinIO so re-ingest is clean.

```bash
docker exec minio mc rm --force local/knowledge-base/documents/pierogi-recipe.docx
```

Truncate Spring Integration metadata so the run step does not classify the file as already-ingested.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM int_metadata_store WHERE metadata_key LIKE '%pierogi-recipe.docx%';"
```

Wipe Qdrant points for the pierogi fixture.

```bash
curl -X POST http://localhost:6333/collections/ascendai-1536/points/delete -H "Content-Type: application/json" -d '{"filter":{"must":[{"key":"source","match":{"value":"documents/pierogi-recipe.docx"}}]}}'
```

Truncate this user's chat-history rows + Redis key.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyAttachSourcesTest';"
```

```bash
docker exec redis redis-cli DEL chat:frostyAttachSourcesTest
```

Wipe Test 7's dedup-pierogi fixtures too. Test 7 owns them, but if it ran earlier in the same sweep its chunks linger in the shared `ascendai-1536` collection — and the "How long should I rest the pierogi dough" retrieval would then pull extra sources, drowning out this spec's single-source assertion.

```bash
docker exec minio mc rm --force local/knowledge-base/markdown/dedup-pierogi-helena.md
```

```bash
docker exec minio mc rm --force local/knowledge-base/markdown/dedup-pierogi-grandma.md
```

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM int_metadata_store WHERE metadata_key LIKE '%dedup-pierogi-%';"
```

```bash
curl -X POST http://localhost:6333/collections/ascendai-1536/points/delete -H "Content-Type: application/json" -d '{"filter":{"must":[{"key":"source","match":{"any":["markdown/dedup-pierogi-helena.md","markdown/dedup-pierogi-grandma.md"]}}]}}'
```

## Run

Step 1. Upload the pierogi-recipe fixture. The existing rag-ingestion-upload sends three; for this spec we re-use it because dropping just one upload from the multipart request and re-running it for one file is overkill. The other two uploads are idempotent against MinIO.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/rag-ingestion-upload.yml" --env ascend-local
```

Step 2. Trigger ingestion (no prefix → scans the whole bucket).

A previous ingestion-run that failed mid-way may have left a stale `int_metadata_store` row for the pierogi key (with the same ETag as the freshly-uploaded object). That stale row would make the scanner skip this file. The product code already removes the marker on ingestion failure (see `ManualIngestionService.processObject`), but as a belt-and-braces guard the test re-deletes the row immediately before the run so the test does not depend on the prior run's exit path.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM int_metadata_store WHERE metadata_key LIKE '%pierogi-recipe.docx%';"
```

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/rag-ingestion-run.yml" --env ascend-local
```

Step 3. Send the attach-sources prompt. This request asks about Helena's pierogi recipe with `attachSources=true` and the test user-id `frostyAttachSourcesTest`.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/attach-sources-prompt.yml" --env ascend-local
```

Capture the response body (Bruno prints it on success). Extract `response.sources[0].downloadUrl` from the JSON.

Step 4. Follow the presigned URL.

```bash
curl -fsS -o /tmp/attach-sources-payload "<paste the downloadUrl from step 3 here>"
```

## Expected

- After step 1: HTTP 200, `uploaded` field includes `documents/pierogi-recipe.docx`.
- After step 2: HTTP 200, `indexed >= 1`.
- After step 3: HTTP 200, response body is JSON containing a `sources` field of type array with at least 1 entry. The first entry has non-empty `name`, `mimeType`, `downloadUrl`, and `expiresAt`.
- After step 3, **the `downloadUrl` host portion equals `localhost:9070`** (NOT `host.docker.internal:9070`). Verify with: `echo "<downloadUrl>" | grep -oE 'https?://[^/]+'` should print `http://localhost:9070`.
- After step 4: HTTP 200, the file at `/tmp/attach-sources-payload` is non-empty (a valid `.docx` blob).

## Fixtures

- `AscendAgent/e2e/fixtures/pierogi-recipe.docx` (re-used from the rag suite)
