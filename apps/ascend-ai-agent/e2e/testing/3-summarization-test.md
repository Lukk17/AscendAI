# Document summarization: e2e test

## What this verifies

- A PDF attached inline on the prompt endpoint is parsed page by page through the document pipeline (PDFBox → Docling).
- Extracted text is injected into the prompt under `<document_context>`.
- The chat model returns a summary grounded in real content from the source document, with specific proper nouns and facts.

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

Check Docling Serve is reachable from the host.

```bash
curl -fsS http://localhost:5001/health
```

Expect HTTP 200.

Check the fixture PDF exists.

```bash
ls apps/ascend-ai-agent/e2e/fixtures/argent-saga-chronicle.pdf
```

Expect the file path to print.

## Reset state

The PDF is sent inline with the prompt and never reaches the object store or `int_metadata_store`, so the only state a run leaves behind is the per-user chat history and Redis keys. Clear them before the run. Post-run cleanup removes the same three, but a run that crashed before reaching that section leaves them behind, and stale `chat_history` rows change the prompt the model sees on the next run. Every command is idempotent.

Drop this spec's chat-history rows.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostySummarizationTest';"
```

Drop the Redis chat cache key.

```bash
docker exec redis redis-cli DEL chat:frostySummarizationTest
```

Drop the Redis instructions cache key.

```bash
docker exec redis redis-cli DEL user:frostySummarizationTest:instructions
```

## Run

Send the Bruno request and wait for the response before moving to the Expected section. The request may take 30–90 seconds because each PDF page is sent to Docling.

```bash
cd docs/api/request/AscendAI
bru run "ascend-agent/testing/doc-summarization-prompt.yml" --env ascend-local
```

## Post-run cleanup

Every prompt this spec sends writes three pieces of per-user state: a `chat_history` row pair in Postgres, the same turns cached under the Redis `chat:` key, and a Redis instructions-cache entry that `UserInstructionService` writes on every prompt (an `EMPTY` marker with a 24 hour TTL when the user has no stored instructions). The agent also runs its semantic-memory extractor after every prompt, whether or not the prompt itself concerns memory, so a fourth cleanup step wipes any fact AscendMemory happened to extract from this prompt. Remove all four so the run leaves the system exactly as it found it. Run these regardless of whether the Run step passed or failed. Every command is idempotent.

Drop this spec's chat-history rows.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostySummarizationTest';"
```

Drop the Redis chat cache key.

```bash
docker exec redis redis-cli DEL chat:frostySummarizationTest
```

Drop the Redis instructions cache key.

```bash
docker exec redis redis-cli DEL user:frostySummarizationTest:instructions
```

Wipe any semantic-memory points AscendMemory's background extractor stored for this user. With no `provider` query parameter the endpoint clears the user across every provider collection, which stays correct if the embedding provider changes.

```bash
curl -sS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostySummarizationTest"
```

Expect `{"status":"success","message":"All memories wiped for user frostySummarizationTest"}`.

## Expected

The Bruno output shows HTTP 200.

The response body's `content` field is a coherent summary that quotes specific facts from the source document. For `argent-saga-chronicle.pdf` it contains at least three of: `Aenaria Solveh`, `Halen Veyr`, `4317 P.E.`, `Heron's Tooth`, `thrall-burn`, `57 seconds`, `Concord of Mireth`, `412 A.E.`, `Vorsh-Ka the Quiet`, `81 duels`, `Iren Hask`, `498 A.E.`. Presence of those proper nouns proves the PDF was parsed page-by-page through Docling and the extracted text reached the model.

The response body's `content` field is NOT a refusal like "the document context block is empty" or "I don't see a document attached". Either indicates the parse pipeline silently returned nothing.

## Fixtures

- `apps/ascend-ai-agent/e2e/fixtures/argent-saga-chronicle.pdf` (with the `.md` source alongside for regeneration).

## Concurrency

- **Mutates:** Postgres `chat_history` (user_id=`frostySummarizationTest`); Redis keys `chat:frostySummarizationTest` and `user:frostySummarizationTest:instructions`; Qdrant collections `ascend_memory_*` (user-scoped: `frostySummarizationTest`, written by the background memory extractor on any prompt)
- **Conflicts with:** none
- **Serial:** false
- **Hermetic contract:** Self-cleaning. `Reset state` (pre) and `Post-run cleanup` (post) both remove every row, key and vector point this spec's user id could carry. The PDF travels inline on the prompt request, so no object-store key and no `int_metadata_store` row is created.
