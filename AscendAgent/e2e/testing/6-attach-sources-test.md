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

Per the Group A hermetic contract, this spec only resets its own artifacts. If a prior spec (5 or 7) left RAG state behind, that's their `Post-run cleanup` responsibility; this spec must not reach into another spec's territory.

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

## Post-run cleanup

Every Group A spec self-cleans so the next spec in the chain sees a hermetic RAG state without having to reach into another spec's artifacts. Run these regardless of whether the Run steps passed or failed; they are idempotent.

Drop the pierogi-recipe fixture from MinIO.

```bash
docker exec minio mc rm --force local/knowledge-base/documents/pierogi-recipe.docx
```

Drop its `int_metadata_store` row so the next ingestion run does not skip a re-upload.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM int_metadata_store WHERE metadata_key LIKE '%pierogi-recipe.docx%';"
```

Wipe its Qdrant points so they cannot leak into the next spec's retrieval.

```bash
curl -X POST http://localhost:6333/collections/ascendai-1536/points/delete -H "Content-Type: application/json" -d '{"filter":{"must":[{"key":"source","match":{"value":"documents/pierogi-recipe.docx"}}]}}'
```

Truncate this spec's chat-history rows + Redis key.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyAttachSourcesTest';"
```

```bash
docker exec redis redis-cli DEL chat:frostyAttachSourcesTest
```

## Expected

- After step 1: HTTP 200, `uploaded` field includes `documents/pierogi-recipe.docx`.
- After step 2: HTTP 200, `indexed >= 1`.
- After step 3: HTTP 200, response body is JSON containing a `sources` field of type array with at least 1 entry. The first entry has non-empty `name`, `mimeType`, `downloadUrl`, and `expiresAt`.
- After step 3, **the `downloadUrl` host portion equals `localhost:9070`** (NOT `host.docker.internal:9070`). Verify with: `echo "<downloadUrl>" | grep -oE 'https?://[^/]+'` should print `http://localhost:9070`.
- After step 4: HTTP 200, the file at `/tmp/attach-sources-payload` is non-empty (a valid `.docx` blob).

## Fixtures

- `AscendAgent/e2e/fixtures/pierogi-recipe.docx` (re-used from the rag suite)

## Concurrency

- **Mutates:** MinIO bucket `knowledge-base` (`documents/pierogi-recipe.docx`); Qdrant collection `ascendai-1536` (pierogi `source` filter); Postgres `int_metadata_store` (pierogi key); Postgres `chat_history` (user_id=`frostyAttachSourcesTest`); Redis key `chat:frostyAttachSourcesTest`
- **Conflicts with:** `5-rag`, `7-rag-dedup` (share Qdrant `ascendai-1536` and MinIO `knowledge-base`)
- **Serial:** false
- **Hermetic contract:** Self-cleaning. Both `Reset state` (pre) and `Post-run cleanup` (post) only touch this spec's own fixture + user-id; never reaches into other Group A specs' artifacts.
