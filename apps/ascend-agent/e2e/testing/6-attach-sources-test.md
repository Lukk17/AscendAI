# Attach-sources: e2e test

## What this verifies

When `attachSources=true` is sent on a prompt request, the response carries a `sources[]` array whose `downloadUrl` (a) returns HTTP 200 from the object store when followed from the host network, and (b) uses the host-reachable hostname `localhost:9070`, NOT the docker-internal `host.docker.internal:9070`. This proves end-to-end that the presigning service works AND that the `app.s3.public-endpoint` override is in effect under the docker profile.

The spec is hermetic: it owns its own object-store key + Qdrant points + chat-history rows for the user-id `frostyAttachSourcesTest`. It re-uses the existing `pierogi-recipe.docx` fixture from the rag suite.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Check the ascend-ai-agent health endpoint.

```bash
curl -fsS http://localhost:9917/actuator/health
```

Check Qdrant is reachable.

```bash
curl -fsS http://localhost:6333/healthz
```

Check the object store is reachable. It serves the S3 API on port 9070 without authentication, so the runbook needs no client and no credentials.

```bash
curl -fsS http://localhost:9070/_floci/health
```

Expect HTTP 200 with `"s3":"running"` in the JSON body.

Check Postgres responds.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "SELECT 1"
```

Check the fixture exists.

```bash
ls apps/ascend-agent/e2e/fixtures/pierogi-recipe.docx
```

## Reset state

Drop all three objects the Run step uploads. Step 1 re-uses `rag-ingestion-upload.yml`, which writes `documents/pierogi-recipe.docx`, `documents/banana-price-poland.pdf` and `markdown/markdown-canary.md`, so the reset has to cover the same three keys as the Post-run cleanup. Resetting only the pierogi key leaves the other two behind whenever a previous run crashed before its cleanup, and a stale object plus its surviving `int_metadata_store` row makes the ingestion scanner skip the file. Each command names the `knowledge-base` bucket literally and one key, and a key that is already gone also returns HTTP 204, so every delete is safe to re-run.

If one of these deletes returns HTTP 404 with `<Code>NoSuchBucket</Code>` rather than 204, `knowledge-base` does not exist, which means the agent never completed startup. That is a broken prerequisite, not a clean slate.

```bash
curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/pierogi-recipe.docx"
```

```bash
curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/banana-price-poland.pdf"
```

```bash
curl -fsS -X DELETE "http://localhost:9070/knowledge-base/markdown/markdown-canary.md"
```

Truncate Spring Integration metadata for the same three keys so the run step does not classify any of them as already-ingested.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM int_metadata_store WHERE metadata_key LIKE '%pierogi-recipe.docx%' OR metadata_key LIKE '%banana-price-poland.pdf%' OR metadata_key LIKE '%markdown-canary.md%';"
```

Wipe Qdrant points for the same three fixtures.

```bash
curl -X POST http://localhost:6333/collections/ascendai-1536/points/delete -H "Content-Type: application/json" -d '{"filter":{"must":[{"key":"source","match":{"any":["documents/pierogi-recipe.docx","documents/banana-price-poland.pdf","markdown/markdown-canary.md"]}}]}}'
```

Truncate this user's chat-history rows + Redis key.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyAttachSourcesTest';"
```

```bash
docker exec redis redis-cli DEL chat:frostyAttachSourcesTest
```

Drop the Redis instructions cache key so the pre-run reset and the Post-run cleanup stay symmetric.

```bash
docker exec redis redis-cli DEL user:frostyAttachSourcesTest:instructions
```

Per the Group A hermetic contract, this spec only resets and cleans the artifacts it owns for the duration of a run: the three objects its upload step writes, plus the `frostyAttachSourcesTest` user-id. It never touches spec 7's `dedup-pierogi-*` fixtures or another spec's user-id.

## Run

Step 1. Upload the pierogi-recipe fixture. The existing rag-ingestion-upload sends three; for this spec we re-use it because dropping just one upload from the multipart request and re-running it for one file is overkill. The other two uploads are idempotent against the object store.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ascend-agent/testing/rag-ingestion-upload.yml" --env ascend-local
```

Step 2. Trigger ingestion (no prefix → scans the whole bucket).

A previous ingestion-run that failed mid-way may have left a stale `int_metadata_store` row for the pierogi key (with the same ETag as the freshly-uploaded object). That stale row would make the scanner skip this file. The product code already removes the marker on ingestion failure (see `ManualIngestionService.processObject`), but as a belt-and-braces guard the test re-deletes the row immediately before the run so the test does not depend on the prior run's exit path.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM int_metadata_store WHERE metadata_key LIKE '%pierogi-recipe.docx%';"
```

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ascend-agent/testing/rag-ingestion-run.yml" --env ascend-local
```

Step 3. Send the attach-sources prompt. This request asks about Helena's pierogi recipe with `attachSources=true` and the test user-id `frostyAttachSourcesTest`.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ascend-agent/testing/attach-sources-prompt.yml" --env ascend-local
```

Capture the response body (Bruno prints it on success). Extract `response.sources[0].downloadUrl` from the JSON.

Step 4. Follow the presigned URL.

```bash
curl -fsS -o /tmp/attach-sources-payload "<paste the downloadUrl from step 3 here>"
```

## Post-run cleanup

Every Group A spec self-cleans so the next spec in the chain sees a hermetic RAG state. Run these regardless of whether the Run steps passed or failed; they are idempotent.

Step 1 re-uses `rag-ingestion-upload.yml`, which writes three objects into `knowledge-base`, not just the pierogi one. All three are this spec's residue for the duration of the run, so all three come out again here. Each delete names the `knowledge-base` bucket literally and one key, so it never sweeps a bucket and never touches a bucket this repository does not own. A key that is already gone also returns HTTP 204, so every delete is safe to re-run.

Drop the three uploaded fixtures from the object store.

```bash
curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/pierogi-recipe.docx"
```

```bash
curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/banana-price-poland.pdf"
```

```bash
curl -fsS -X DELETE "http://localhost:9070/knowledge-base/markdown/markdown-canary.md"
```

Drop their `int_metadata_store` rows so the next ingestion run does not skip a re-upload.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM int_metadata_store WHERE metadata_key LIKE '%pierogi-recipe.docx%' OR metadata_key LIKE '%banana-price-poland.pdf%' OR metadata_key LIKE '%markdown-canary.md%';"
```

Wipe their Qdrant points so they cannot leak into the next spec's retrieval.

```bash
curl -X POST http://localhost:6333/collections/ascendai-1536/points/delete -H "Content-Type: application/json" -d '{"filter":{"must":[{"key":"source","match":{"any":["documents/pierogi-recipe.docx","documents/banana-price-poland.pdf","markdown/markdown-canary.md"]}}]}}'
```

Truncate this spec's chat-history rows + Redis key.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyAttachSourcesTest';"
```

```bash
docker exec redis redis-cli DEL chat:frostyAttachSourcesTest
```

Drop the Redis instructions cache key. `UserInstructionService` writes it on every prompt (an `EMPTY` marker with a 24 hour TTL when the user has no stored instructions), so it outlives the run unless the spec deletes it.

```bash
docker exec redis redis-cli DEL user:frostyAttachSourcesTest:instructions
```

Wipe any semantic-memory points AscendMemory's background extractor stored for this user. The agent runs the extractor after every prompt, whether or not it concerns memory. With no `provider` query parameter the endpoint clears the user across every provider collection, which stays correct if the embedding provider changes.

```bash
curl -sS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyAttachSourcesTest"
```

Expect `{"status":"success","message":"All memories wiped for user frostyAttachSourcesTest"}`.

## Expected

- After step 1: HTTP 200, `uploaded` field includes `documents/pierogi-recipe.docx`.
- After step 2: HTTP 200, `indexed >= 1`.
- After step 3: HTTP 200, response body is JSON containing a `sources` field of type array with at least 1 entry. The first entry has non-empty `name`, `mimeType`, `downloadUrl`, and `expiresAt`.
- After step 3, **the `downloadUrl` host portion equals `localhost:9070`** (NOT `host.docker.internal:9070`). Verify with: `echo "<downloadUrl>" | grep -oE 'https?://[^/]+'` should print `http://localhost:9070`.
- After step 4: HTTP 200, the file at `/tmp/attach-sources-payload` is non-empty (a valid `.docx` blob).

## Fixtures

- `apps/ascend-agent/e2e/fixtures/pierogi-recipe.docx` (re-used from the rag suite)

## Concurrency

Docling-bound. This spec runs alone: no runner of any suite active while it is in flight, from this suite or from any other module's sweep. Start it only when nothing else is running anywhere, and start nothing else until it has returned. The PDF and DOCX fixtures are ingested through docling-serve. docling's worker is single-threaded per page, so any other runner on the host competes for the core it runs on (the OCR suite measured that effect on 2026-09-10: 59.2 seconds on a quiet host against 160.9 seconds on a loaded one for one fixture), and docling peaks close to its own compose memory limit (defect register A3 and A38), so a second runner costs memory headroom as well as time. See [`apps/ascend-agent/e2e/README.md`](../README.md) "Parallelism and execution order".

- Mutates: object-store bucket `knowledge-base` (`documents/pierogi-recipe.docx`, `documents/banana-price-poland.pdf`, `markdown/markdown-canary.md`, all three written by the shared upload request), Qdrant collection `ascendai-1536` (`source` filters for those three keys), Qdrant collections `ascend_memory_*` (user-scoped: `frostyAttachSourcesTest`, written by the background memory extractor on any prompt), Postgres `int_metadata_store` (rows for those three keys), Postgres `chat_history` (user_id=`frostyAttachSourcesTest`), Redis keys `chat:frostyAttachSourcesTest` and `user:frostyAttachSourcesTest:instructions`
- Conflicts with: `5-rag`, `7-rag-dedup` (share Qdrant `ascendai-1536` and object-store bucket `knowledge-base`). The overlap with `5-rag` is total for the three upload keys, so these two must never run concurrently.
- Serial: true
- Hermetic contract: Self-cleaning. `Post-run cleanup` removes every object the Run steps wrote, so the bucket, the metadata store and the vector store are left as the spec found them.
