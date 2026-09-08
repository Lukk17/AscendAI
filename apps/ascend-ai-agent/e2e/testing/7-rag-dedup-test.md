# RAG dedup: e2e test

## What this verifies

When RAG retrieval pulls multiple chunks across two different source files, the response's `sources[]` array contains exactly one entry per unique source file (not one per chunk). Proves `RagRetrievalService.buildSourceRefs` collapses per-chunk duplicates by `(bucket, key)` while still surfacing every unique source.

Hermetic: owns the two `dedup-pierogi-*.md` fixtures in the object store + Qdrant + the `frostyRagDedupTest` chat-history rows.

## Prerequisites

Check Bruno CLI, ascend-ai-agent `/actuator/health`, Qdrant `/healthz`, the object store `/_floci/health`, and that Postgres responds. Same set as `5-rag-test.md` and `6-attach-sources-test.md`.

Check the two dedup fixtures exist.

```bash
ls apps/ascend-ai-agent/e2e/fixtures/dedup-pierogi-helena.md apps/ascend-ai-agent/e2e/fixtures/dedup-pierogi-grandma.md
```

## Reset state

Drop the two dedup fixtures from the object store. Each command names the `knowledge-base` bucket literally and one key, and a key that is already gone also returns HTTP 204, so both deletes are safe to re-run.

If one of these deletes returns HTTP 404 with `<Code>NoSuchBucket</Code>` rather than 204, `knowledge-base` does not exist, which means the agent never completed startup. That is a broken prerequisite, not a clean slate.

```bash
curl -fsS -X DELETE "http://localhost:9070/knowledge-base/markdown/dedup-pierogi-helena.md"
```

```bash
curl -fsS -X DELETE "http://localhost:9070/knowledge-base/markdown/dedup-pierogi-grandma.md"
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

Drop the Redis instructions cache key so the pre-run reset and the Post-run cleanup stay symmetric.

```bash
docker exec redis redis-cli DEL user:frostyRagDedupTest:instructions
```

Per the Group A hermetic contract, this spec only resets its own artifacts (`dedup-pierogi-*` + `frostyRagDedupTest`). Spec 5 and spec 6 are responsible for clearing `pierogi-recipe.docx` in their own `Post-run cleanup` sections; this spec must not reach across into their territory.

## Run

Step 1. Upload the two dedup fixtures.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ascend-agent/testing/rag-dedup-upload.yml" --env ascend-local
```

Step 2. Trigger ingestion.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ascend-agent/testing/rag-ingestion-run.yml" --env ascend-local
```

Step 3. Send the dedup prompt with `attachSources=true`.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ascend-agent/testing/rag-dedup-prompt.yml" --env ascend-local
```

## Post-run cleanup

Every Group A spec self-cleans so the next sweep sees a hermetic RAG state without having to reach into another spec's artifacts. Run these regardless of whether the Run steps passed or failed; they are idempotent.

Drop the two dedup fixtures from the object store.

```bash
curl -fsS -X DELETE "http://localhost:9070/knowledge-base/markdown/dedup-pierogi-helena.md"
```

```bash
curl -fsS -X DELETE "http://localhost:9070/knowledge-base/markdown/dedup-pierogi-grandma.md"
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

Drop the Redis instructions cache key. `UserInstructionService` writes it on every prompt (an `EMPTY` marker with a 24 hour TTL when the user has no stored instructions), so it outlives the run unless the spec deletes it.

```bash
docker exec redis redis-cli DEL user:frostyRagDedupTest:instructions
```

Wipe any semantic-memory points AscendMemory's background extractor stored for this user. The agent runs the extractor after every prompt, whether or not it concerns memory. With no `provider` query parameter the endpoint clears the user across every provider collection, which stays correct if the embedding provider changes.

```bash
curl -sS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyRagDedupTest"
```

Expect `{"status":"success","message":"All memories wiped for user frostyRagDedupTest"}`.

## Expected

- After step 1: HTTP 200, `uploaded` field includes both `markdown/dedup-pierogi-helena.md` and `markdown/dedup-pierogi-grandma.md`.
- After step 2: HTTP 200, `indexed >= 2`.
- After step 3: HTTP 200. Response body has a `sources` array with **exactly 2 entries**, proving the dedup collapse (multiple Qdrant chunks across two files → one source entry per unique file). Identify which file each entry points at by inspecting `downloadUrl`: one entry's URL path contains `markdown/dedup-pierogi-helena.md`, the other's contains `markdown/dedup-pierogi-grandma.md` (in either order). Each entry's `name` field carries the document's H1 title (`Babcia Helena's pierogi recipe (e2e dedup fixture)` and `Grandma Maria's pierogi recipe (e2e dedup fixture)`) per the `SourceFile.name` contract. Don't assert on `name` equality with the filename; the contract is "H1 title when extractable, filename basename otherwise" (see `SourceFile.java`).
- The response `content` references both recipes (mentions Helena AND Grandma / Maria, or alternately mentions both filling types: sauerkraut/mushroom AND potato/cheese). This is a soft assertion that the LLM actually used both retrieved sources; if it only mentions one, the retrieval still pulled chunks from both files (verifiable from `sources[]`) but the LLM chose to draw on one.

## Fixtures

- `apps/ascend-ai-agent/e2e/fixtures/dedup-pierogi-helena.md`
- `apps/ascend-ai-agent/e2e/fixtures/dedup-pierogi-grandma.md`

## Concurrency

- **Mutates:** object-store bucket `knowledge-base` (`markdown/dedup-pierogi-helena.md`, `markdown/dedup-pierogi-grandma.md`); Qdrant collection `ascendai-1536` (dedup `source` filters); Qdrant collections `ascend_memory_*` (user-scoped: `frostyRagDedupTest`, written by the background memory extractor on any prompt); Postgres `int_metadata_store` (dedup keys); Postgres `chat_history` (user_id=`frostyRagDedupTest`); Redis keys `chat:frostyRagDedupTest` and `user:frostyRagDedupTest:instructions`
- **Conflicts with:** `5-rag`, `6-attach-sources` (share Qdrant `ascendai-1536` and object-store bucket `knowledge-base`)
- **Serial:** false
- **Hermetic contract:** Self-cleaning. Both `Reset state` (pre) and `Post-run cleanup` (post) only touch this spec's own fixtures + user-id; never reaches into other Group A specs' artifacts. Relies on specs 5 and 6 honouring their own post-run cleanup contracts.
