# RAG: e2e test

## What this verifies

- Documents uploaded to the ingestion endpoint land in the object store under the right folder prefix (`markdown/` for Markdown, `documents/` for others).
- The manual ingestion run reads them, splits into chunks, embeds, and writes points to Qdrant.
- A later prompt retrieves the relevant chunk and produces an answer grounded in the uploaded content.

Three document formats are exercised: Markdown, PDF, DOCX.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string. If the command is not found, install it with `npm install -g @usebruno/cli`.

Check the ascend-ai-agent health endpoint.

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

Check the object store is reachable. It serves the S3 API on port 9070 without authentication, so the runbook needs no client and no credentials.

```bash
curl -fsS http://localhost:9070/_floci/health
```

Expect HTTP 200 with `"s3":"running"` in the JSON body.

Check Postgres responds. Run inside the `postgres` container because `psql` is not on the host shell in this dev environment.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "SELECT 1"
```

Expect a row with `1` in the output.

Check the three fixtures exist.

```bash
ls apps/ascend-agent/e2e/fixtures/markdown-canary.md apps/ascend-agent/e2e/fixtures/banana-price-poland.pdf apps/ascend-agent/e2e/fixtures/pierogi-recipe.docx
```

Expect all three paths to print.

## Reset state

Drop only this test's three fixtures from the object store so re-upload is clean. Each command names the `knowledge-base` bucket literally and one key, so it never touches another test's fixtures sharing the same bucket, and never reaches a bucket this repository does not own. A key that is already gone also returns HTTP 204, so every delete is safe to re-run.

If one of these deletes returns HTTP 404 with `<Code>NoSuchBucket</Code>` rather than 204, `knowledge-base` does not exist, which means the agent never completed startup. That is a broken prerequisite, not a clean slate.

```bash
curl -fsS -X DELETE "http://localhost:9070/knowledge-base/markdown/markdown-canary.md"
```

```bash
curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/banana-price-poland.pdf"
```

```bash
curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/pierogi-recipe.docx"
```

Delete only the `int_metadata_store` rows for these three fixtures so the run step does not classify them as already-ingested. Trailing `%` in each pattern matches the ETag suffix appended to the metadata key.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM int_metadata_store WHERE metadata_key LIKE '%markdown-canary.md%' OR metadata_key LIKE '%banana-price-poland.pdf%' OR metadata_key LIKE '%pierogi-recipe.docx%';"
```

Wipe RAG points for the three fixtures from Qdrant.

```bash
curl -X POST http://localhost:6333/collections/ascendai-1536/points/delete -H "Content-Type: application/json" -d '{"filter":{"must":[{"key":"source","match":{"any":["markdown/markdown-canary.md","documents/banana-price-poland.pdf","documents/pierogi-recipe.docx"]}}]}}'
```

Truncate this spec's chat-history rows + Redis key so the Post-run cleanup and the pre-run reset stay symmetric. A run that crashed before reaching Post-run cleanup would otherwise leave stale `chat_history` rows that change the prompt the model sees on the next run.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyRagTest';"
```

```bash
docker exec redis redis-cli DEL chat:frostyRagTest
```

Drop the Redis instructions cache key.

```bash
docker exec redis redis-cli DEL user:frostyRagTest:instructions
```

## Run

Step 1. Upload the three fixtures in one multipart request. Wait for HTTP 200 before continuing.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ascend-agent/testing/rag-ingestion-upload.yml" --env ascend-local
```

Step 2. Trigger ingestion (no prefix → scans the whole bucket). Wait for HTTP 200 and a non-zero `indexed` count before continuing.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ascend-agent/testing/rag-ingestion-run.yml" --env ascend-local
```

Step 3. Send the RAG prompt. The Bruno request saves three alternative `prompt=` rows on the same field; only one is enabled by default. Run the request once with the current default, then edit the YAML to enable the next prompt row (and disable the previous) and re-run. Do this once per fixture for full coverage.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ascend-agent/testing/rag-prompt.yml" --env ascend-local
```

The three prompts saved in the request:
- `What is the Ascend canary phrase?` (markdown fixture)
- `What was the retail price of bananas in Poland in October 2026?` (PDF fixture)
- `How long should I rest the pierogi dough according to Babcia Helena's recipe?` (DOCX fixture)

## Post-run cleanup

Every Group A spec self-cleans so the next spec in the chain sees a hermetic RAG state without having to reach into another spec's artifacts. Run these regardless of whether the Run steps passed or failed; they are idempotent and never touch state owned by tests 6 or 7.

Drop this spec's three fixtures from the object store.

```bash
curl -fsS -X DELETE "http://localhost:9070/knowledge-base/markdown/markdown-canary.md"
```

```bash
curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/banana-price-poland.pdf"
```

```bash
curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/pierogi-recipe.docx"
```

Drop their `int_metadata_store` rows so subsequent re-ingestion is not skipped.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM int_metadata_store WHERE metadata_key LIKE '%markdown-canary.md%' OR metadata_key LIKE '%banana-price-poland.pdf%' OR metadata_key LIKE '%pierogi-recipe.docx%';"
```

Wipe their Qdrant points.

```bash
curl -X POST http://localhost:6333/collections/ascendai-1536/points/delete -H "Content-Type: application/json" -d '{"filter":{"must":[{"key":"source","match":{"any":["markdown/markdown-canary.md","documents/banana-price-poland.pdf","documents/pierogi-recipe.docx"]}}]}}'
```

Truncate this spec's chat-history rows + Redis key so the per-user slot is clean.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyRagTest';"
```

```bash
docker exec redis redis-cli DEL chat:frostyRagTest
```

Drop the Redis instructions cache key. `UserInstructionService` writes it on every prompt (an `EMPTY` marker with a 24 hour TTL when the user has no stored instructions), so it outlives the run unless the spec deletes it.

```bash
docker exec redis redis-cli DEL user:frostyRagTest:instructions
```

Wipe any semantic-memory points AscendMemory's background extractor stored for this user. The agent runs the extractor after every prompt, including the three RAG prompts this spec sends, whether or not they concern memory. With no `provider` query parameter the endpoint clears the user across every provider collection, which stays correct if the embedding provider changes.

```bash
curl -sS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyRagTest"
```

Expect `{"status":"success","message":"All memories wiped for user frostyRagTest"}`.

## Expected

After step 1 the Bruno output shows HTTP 200.

After step 1 the response body's `uploaded` field lists exactly three keys: one under `markdown/` and two under `documents/`.

After step 1 `curl -fsS "http://localhost:9070/knowledge-base?list-type=2&prefix=markdown/"` returns a `ListBucketResult` whose `Contents` carry `<Key>markdown/markdown-canary.md</Key>`.

After step 1 `curl -fsS "http://localhost:9070/knowledge-base?list-type=2&prefix=documents/"` returns a `ListBucketResult` whose `Contents` carry both `<Key>documents/banana-price-poland.pdf</Key>` and `<Key>documents/pierogi-recipe.docx</Key>`.

After step 2 the Bruno output shows HTTP 200.

After step 2 the response body has `indexed` ≥ 3 and `failed` = 0.

After step 3a (markdown-canary prompt) the response body's `content` field contains the canary phrase from the markdown fixture (e.g. `PURPLE-MOOSE-42`).

After step 3b (banana-price prompt) the response body's `content` field contains a numeric price in PLN that matches the PDF fixture (e.g. `6.49`).

After step 3c (pierogi-recipe prompt) the response body's `content` field contains the rest time from the DOCX fixture (`30 minutes`).

For each of step 3a/3b/3c the response is NOT a refusal like "I don't have that document". A refusal means the RAG retrieval did not inject the relevant chunk into the prompt.

## Fixtures

- `apps/ascend-agent/e2e/fixtures/markdown-canary.md`
- `apps/ascend-agent/e2e/fixtures/banana-price-poland.pdf`
- `apps/ascend-agent/e2e/fixtures/pierogi-recipe.docx`

## Concurrency

- **Mutates:** object-store bucket `knowledge-base` (`markdown/markdown-canary.md`, `documents/banana-price-poland.pdf`, `documents/pierogi-recipe.docx`); Qdrant collection `ascendai-1536` (filtered by these `source` values); Qdrant collections `ascend_memory_*` (user-scoped: `frostyRagTest`, written by the background memory extractor on any prompt); Postgres `int_metadata_store` (rows for these object keys); Postgres `chat_history` (user_id=`frostyRagTest`); Redis keys `chat:frostyRagTest` and `user:frostyRagTest:instructions`
- **Conflicts with:** `6-attach-sources`, `7-rag-dedup` (share Qdrant `ascendai-1536` and object-store bucket `knowledge-base`)
- **Serial:** false
- **Hermetic contract:** Self-cleaning. Both `Reset state` (pre) and `Post-run cleanup` (post) touch the same set: this spec's own fixtures, the `frostyRagTest` user-id's chat/Redis/memory state. Never reaches into other Group A specs' artifacts.

## Optional: attach source files

The `attachSources=true` form field opts the response into a `sources` array of presigned object-store URLs for the documents that grounded the answer. Default is `false` (response shape unchanged).

Run this section immediately after Run step 3, while the three fixtures are still ingested, and before the Post-run cleanup section above. Every call below sends this spec's own user id, `frostyRagTest`, so the Post-run cleanup commands already remove the chat-history rows and Redis keys the section writes. Nothing extra is needed afterwards, and the same cleanup stays correct when the section is skipped. Earlier revisions of this spec sent `user1` here, which no cleanup covered and which collides with the configured default user id, so those rows survived every run.

The three flags after the prompt mirror the enabled rows in `rag-prompt.yml` and are not optional. Omitting `embeddingProvider` returns HTTP 400 with `Unknown embedding provider: 'null'`, and sending `embeddingProvider=openai` without `provider=minimax` returns HTTP 400 because the default chat provider expects 768-dim embeddings while the RAG collection is the 1536-dim `ascendai-1536`.

Send a prompt with the flag set.

```bash
curl -s -X POST http://localhost:9917/api/v1/ai/prompt -F "prompt=What is the Ascend canary phrase?" -F "attachSources=true" -F "provider=minimax" -F "model=MiniMax-M2.7" -F "embeddingProvider=openai" -H "X-User-Id: frostyRagTest"
```

Expected response shape (truncated):

```json
{
  "content": "...PURPLE-MOOSE-42...",
  "metadata": { "...": "..." },
  "sources": [
    {
      "name": "markdown-canary.md",
      "mimeType": "text/markdown",
      "downloadUrl": "http://localhost:9070/knowledge-base/markdown/markdown-canary.md?X-Amz-...",
      "expiresAt": "2026-05-14T06:14:34Z",
      "sizeBytes": 412
    }
  ]
}
```

Verify the `downloadUrl` resolves to a 200 GET against the object store from the host network.

```bash
curl -fsS -o /tmp/source.bin "<paste downloadUrl from previous response>"
```

Re-run the same prompt without `attachSources=true` and assert the response JSON does NOT contain a `sources` key (byte-for-byte backward compat).

```bash
curl -s -X POST http://localhost:9917/api/v1/ai/prompt -F "prompt=What is the Ascend canary phrase?" -F "provider=minimax" -F "model=MiniMax-M2.7" -F "embeddingProvider=openai" -H "X-User-Id: frostyRagTest"
```

Send a prompt that retrieves nothing with `attachSources=true` and expect `"sources": []`.

```bash
curl -s -X POST http://localhost:9917/api/v1/ai/prompt -F "prompt=What is the airspeed velocity of an unladen swallow?" -F "attachSources=true" -F "provider=minimax" -F "model=MiniMax-M2.7" -F "embeddingProvider=openai" -H "X-User-Id: frostyRagTest"
```
