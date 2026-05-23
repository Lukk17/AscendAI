# RAG dedup: e2e test

## What this verifies

When RAG retrieval pulls multiple chunks across two different source files, the response's `sources[]` array contains exactly one entry per unique source file (not one per chunk). Proves `RagRetrievalService.buildSourceRefs` collapses per-chunk duplicates by `(bucket, key)` while still surfacing every unique source.

Hermetic: owns the two `dedup-pierogi-*.md` fixtures in MinIO + Qdrant + the `frostyRagDedupTest` chat-history rows.

## Prerequisites

Check Bruno CLI, AscendAgent `/actuator/health`, Qdrant `/healthz`, MinIO `/minio/health/live`, Postgres responds. Same set as `5-rag-test.md` and `6-attach-sources-test.md`.

Check the two dedup fixtures exist.

```bash
ls AscendAgent/e2e/fixtures/dedup-pierogi-helena.md AscendAgent/e2e/fixtures/dedup-pierogi-grandma.md
```

## Reset state

Register MinIO alias.

```bash
docker exec minio sh -c 'mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"'
```

Drop the two dedup fixtures from MinIO.

```bash
docker exec minio mc rm --force local/knowledge-base/markdown/dedup-pierogi-helena.md local/knowledge-base/markdown/dedup-pierogi-grandma.md
```

Truncate the metadata store for the two fixtures so re-ingest is clean.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM int_metadata_store WHERE metadata_key LIKE '%dedup-pierogi-%';"
```

Wipe Qdrant points for the two fixtures.

```bash
curl -X POST http://localhost:6333/collections/ascendai-1536/points/delete -H "Content-Type: application/json" -d '{"filter":{"must":[{"key":"source","match":{"any":["markdown/dedup-pierogi-helena.md","markdown/dedup-pierogi-grandma.md"]}}]}}'
```

Truncate `frostyRagDedupTest` chat-history.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyRagDedupTest';"
```

```bash
docker exec redis redis-cli DEL chat:frostyRagDedupTest
```

Also clear any leftover `pierogi-recipe.docx` from MinIO, Qdrant, and the metadata store so the dedup prompt's retrieval can't pull a third source from prior RAG-suite runs. Without this, tests 5 / 6 may have left pierogi ingested and the dedup `sources[]` array would contain 3 entries instead of the expected 2.

```bash
docker exec minio mc rm --force local/knowledge-base/documents/pierogi-recipe.docx
```

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM int_metadata_store WHERE metadata_key LIKE '%pierogi-recipe.docx%';"
```

```bash
curl -X POST http://localhost:6333/collections/ascendai-1536/points/delete -H "Content-Type: application/json" -d '{"filter":{"must":[{"key":"source","match":{"value":"documents/pierogi-recipe.docx"}}]}}'
```

## Run

Step 1. Upload the two dedup fixtures.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/rag-dedup-upload.yml" --env ascend-local
```

Step 2. Trigger ingestion.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/rag-ingestion-run.yml" --env ascend-local
```

Step 3. Send the dedup prompt with `attachSources=true`.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/rag-dedup-prompt.yml" --env ascend-local
```

## Expected

- After step 1: HTTP 200, `uploaded` field includes both `markdown/dedup-pierogi-helena.md` and `markdown/dedup-pierogi-grandma.md`.
- After step 2: HTTP 200, `indexed >= 2`.
- After step 3: HTTP 200. Response body has a `sources` array with **exactly 2 entries**. The two entries' `name` fields equal `dedup-pierogi-helena.md` and `dedup-pierogi-grandma.md` (in either order).
- The response `content` references both recipes (mentions Helena AND Grandma / Maria, or alternately mentions both filling types: sauerkraut/mushroom AND potato/cheese). This is a soft assertion that the LLM actually used both retrieved sources; if it only mentions one, the retrieval still pulled chunks from both files (verifiable from `sources[]`) but the LLM chose to draw on one.

## Fixtures

- `AscendAgent/e2e/fixtures/dedup-pierogi-helena.md`
- `AscendAgent/e2e/fixtures/dedup-pierogi-grandma.md`
