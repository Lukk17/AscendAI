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

Per the Group A hermetic contract, this spec only resets its own artifacts (`dedup-pierogi-*` + `frostyRagDedupTest`). Spec 5 and spec 6 are responsible for clearing `pierogi-recipe.docx` in their own `Post-run cleanup` sections; this spec must not reach across into their territory.

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

## Post-run cleanup

Every Group A spec self-cleans so the next sweep sees a hermetic RAG state without having to reach into another spec's artifacts. Run these regardless of whether the Run steps passed or failed; they are idempotent.

Drop the two dedup fixtures from MinIO.

```bash
docker exec minio mc rm --force local/knowledge-base/markdown/dedup-pierogi-helena.md local/knowledge-base/markdown/dedup-pierogi-grandma.md
```

Drop their `int_metadata_store` rows.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM int_metadata_store WHERE metadata_key LIKE '%dedup-pierogi-%';"
```

Wipe their Qdrant points.

```bash
curl -X POST http://localhost:6333/collections/ascendai-1536/points/delete -H "Content-Type: application/json" -d '{"filter":{"must":[{"key":"source","match":{"any":["markdown/dedup-pierogi-helena.md","markdown/dedup-pierogi-grandma.md"]}}]}}'
```

Truncate this spec's chat-history rows + Redis key.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyRagDedupTest';"
```

```bash
docker exec redis redis-cli DEL chat:frostyRagDedupTest
```

## Expected

- After step 1: HTTP 200, `uploaded` field includes both `markdown/dedup-pierogi-helena.md` and `markdown/dedup-pierogi-grandma.md`.
- After step 2: HTTP 200, `indexed >= 2`.
- After step 3: HTTP 200. Response body has a `sources` array with **exactly 2 entries**, proving the dedup collapse (multiple Qdrant chunks across two files → one source entry per unique file). Identify which file each entry points at by inspecting `downloadUrl`: one entry's URL path contains `markdown/dedup-pierogi-helena.md`, the other's contains `markdown/dedup-pierogi-grandma.md` (in either order). Each entry's `name` field carries the document's H1 title (`Babcia Helena's pierogi recipe (e2e dedup fixture)` and `Grandma Maria's pierogi recipe (e2e dedup fixture)`) per the `SourceFile.name` contract. Don't assert on `name` equality with the filename; the contract is "H1 title when extractable, filename basename otherwise" (see `SourceFile.java`).
- The response `content` references both recipes (mentions Helena AND Grandma / Maria, or alternately mentions both filling types: sauerkraut/mushroom AND potato/cheese). This is a soft assertion that the LLM actually used both retrieved sources; if it only mentions one, the retrieval still pulled chunks from both files (verifiable from `sources[]`) but the LLM chose to draw on one.

## Fixtures

- `AscendAgent/e2e/fixtures/dedup-pierogi-helena.md`
- `AscendAgent/e2e/fixtures/dedup-pierogi-grandma.md`

## Concurrency

- **Mutates:** MinIO bucket `knowledge-base` (`markdown/dedup-pierogi-helena.md`, `markdown/dedup-pierogi-grandma.md`); Qdrant collection `ascendai-1536` (dedup `source` filters); Postgres `int_metadata_store` (dedup keys); Postgres `chat_history` (user_id=`frostyRagDedupTest`); Redis key `chat:frostyRagDedupTest`
- **Conflicts with:** `5-rag`, `6-attach-sources` (share Qdrant `ascendai-1536` and MinIO `knowledge-base`)
- **Serial:** false
- **Hermetic contract:** Self-cleaning. Both `Reset state` (pre) and `Post-run cleanup` (post) only touch this spec's own fixtures + user-id; never reaches into other Group A specs' artifacts. Relies on specs 5 and 6 honouring their own post-run cleanup contracts.
