# Semantic Memory — manual e2e test

## What this verifies

A fact stated in one turn is extracted, stored in Qdrant via AscendMemory, and recalled in a later turn — independently of Redis chat history. Covers:

- **Bug 1** — robust semantic memory extraction
- **Bug 4** — AscendMemory `search` query-parameter name mismatch
- **Bug 5** — memory-client gaps & silent failures (now surface real errors)
- **Bug 12** — AscendMemory per-provider OpenAI routing (embeddings target the correct collection)
- **Bug 13** — `SemanticMemoryItem` JSON field-name alignment
- **Bug 14** — AscendMemory truncates embeddings to the collection dimension

## Prerequisites

- `docker compose up -d` stack up
- AscendAgent on 9917, AscendMemory on 7020, Qdrant on 6333
- A chat provider that runs reliably (the Bruno default is MiniMax M2.7; Anthropic / OpenAI / Gemini all work)
- A fresh `X-User-Id` so prior state can't pollute results. The Bruno files use `frosty` — wipe that user's points in the Qdrant dashboard before running, or change the header.

Active Qdrant collection depends on the embedding provider: `ascend_memory_1536` for `openai`, `ascend_memory_768` for `lmstudio` / `gemini`. The Bruno files default to `openai`.

## Bruno collection

Open Bruno → `docs/api/request/AscendAI/ascend-agent/testing/`. This test uses two requests:

1. `memory-test-save.yml` — write turn
2. `memory-test-retrieve.yml` — recall turn

Both are templates with multiple `provider=` / `embeddingProvider=` rows. Enable exactly one of each before sending.

### Save turn (`memory-test-save.yml`)

Enable:

- `prompt`: `Hello, my name is Luke. I am a software engineer.`
- `provider`: `minimax` (or toggle to `anthropic` + `claude-sonnet-4-6`)
- `model`: `MiniMax-M2.7`
- `embeddingProvider`: `openai`

### Retrieve turn (`memory-test-retrieve.yml`)

Enable:

- `prompt`: `What is my name and what do I do?`
- `provider`: same as save turn
- `model`: same as save turn
- `embeddingProvider`: same as save turn (must match — different providers write to different collections)

Header `X-User-Id: frosty` is pinned in both files; keep it consistent across the two turns.

## Steps

1. Send `memory-test-save.yml`. Watch the agent log.
2. (Optional, to prove recall doesn't come from chat history) flush Redis and truncate `chat_history` in Postgres before sending the second turn.
3. Send `memory-test-retrieve.yml`. Watch the agent log.

## Expected

**After save:**

- HTTP 200.
- Agent log contains `Inserted N/N facts for user 'frosty'` with N ≥ 1.
- A Qdrant scroll on `ascend_memory_1536` filtered by `user_id=frosty` returns at least one point mentioning Luke / software engineer.

**After retrieve:**

- HTTP 200.
- Agent log contains `SemanticMemory: YES (N items)` with N ≥ 1 (Bug 13 — note this is the corrected field name).
- `content` mentions `Luke` and `software engineer`.
- If the log shows `SemanticMemory: NO` or the response says "I don't know your name", check that the same `embeddingProvider` was used for both turns (Bugs 4 + 12) and that the points exist in Qdrant.

## Bugs this covers

Bugs 1, 4, 5, 12, 13, 14 (see list above).

## Fixtures

None.
