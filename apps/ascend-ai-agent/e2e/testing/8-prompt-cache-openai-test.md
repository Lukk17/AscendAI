# Prompt cache: OpenAI: e2e test

## What this verifies

OpenAI's automatic prefix caching fires on the second of two identical prompts sent to the same provider. The second response's `metadata.usage.nativeUsage.prompt_tokens_details.cached_tokens` is greater than zero. Validates that the `add-prompt-caching` change is wired correctly end-to-end against a live OpenAI provider.

> The wire format echoes OpenAI's own field names verbatim under `nativeUsage` (snake_case, nested under `prompt_tokens_details`). Earlier revisions of this spec referenced a camelCase shape (`promptTokensDetails.cachedTokens`); that shape was never on the wire and any older runs that asserted against it were reading nothing.

Hermetic: owns the `frostyPromptCacheOpenaiTest` chat-history rows (and Redis key). The first call seeds the cache; the second call hits it.

## Prerequisites

Check Bruno CLI, ascend-ai-agent `/actuator/health`, Postgres + Redis healthy.

Check the `OPENAI_API_KEY` env var is configured for the running ascend-ai-agent (from `.env` / docker-compose). Without it, OpenAI calls return an auth error and this test fails before it can assert anything about cache.

```bash
docker exec ascend-ai-agent sh -c '[ -n "$OPENAI_API_KEY" ] && echo present || echo missing'
```

Should print `present`. Never `printenv` the raw value, even truncated. This check proves the variable is set
without printing any of it.

## Reset state

Truncate the test user's chat-history so the static prompt prefix is byte-identical between the two calls (no prior turns leaking into the prefix).

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyPromptCacheOpenaiTest';"
```

```bash
docker exec redis redis-cli DEL chat:frostyPromptCacheOpenaiTest
```

Drop the Redis instructions cache key so the pre-run reset and the Post-run cleanup stay symmetric.

```bash
docker exec redis redis-cli DEL user:frostyPromptCacheOpenaiTest:instructions
```

## Run

Step 1. First prompt (cache miss expected; this seeds OpenAI's prefix cache).

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ascend-agent/testing/prompt-cache-openai.yml" --env ascend-local
```

Capture response 1's `metadata.usage` block. Note `nativeUsage.prompt_tokens_details.cached_tokens` (expected: 0 or absent on a fresh-cache run; non-zero is acceptable when OpenAI's server-side cache TTL hasn't expired from a prior local run) and `promptTokens` (expected: ≥ 1024, required for OpenAI auto cache to fire on the next call).

Step 2. Second prompt within ~5 minutes (cache hit expected). Same Bruno request, run again.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ascend-agent/testing/prompt-cache-openai.yml" --env ascend-local
```

Capture response 2's `metadata.usage`. Note `nativeUsage.prompt_tokens_details.cached_tokens` (expected: > 0).

## Post-run cleanup

The Reset section clears the `chat_history` rows and the Redis `chat:` key before the run, and the two prompt calls write both again. The run also leaves a Redis instructions-cache entry that `UserInstructionService` writes on every prompt (an `EMPTY` marker with a 24 hour TTL when the user has no stored instructions). Remove all three so the run leaves the system exactly as it found it. Run these regardless of whether the Run steps passed or failed. Every command is idempotent.

Drop this spec's chat-history rows.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyPromptCacheOpenaiTest';"
```

Drop the Redis chat cache key.

```bash
docker exec redis redis-cli DEL chat:frostyPromptCacheOpenaiTest
```

Drop the Redis instructions cache key.

```bash
docker exec redis redis-cli DEL user:frostyPromptCacheOpenaiTest:instructions
```

Wipe any semantic-memory points AscendMemory's background extractor stored for this user. The agent runs the extractor after every prompt, whether or not it concerns memory. With no `provider` query parameter the endpoint clears the user across every provider collection, which stays correct if the embedding provider changes.

```bash
curl -sS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyPromptCacheOpenaiTest"
```

Expect `{"status":"success","message":"All memories wiped for user frostyPromptCacheOpenaiTest"}`.

Nothing else survives the run. This spec sends no attachment, uploads no object and triggers no ingestion, so the object store, `int_metadata_store` and the RAG collection are untouched.

## Expected

- After step 1: HTTP 200. Response `metadata.usage.promptTokens >= 1024` (otherwise OpenAI's auto cache won't fire on the next call; the test prompt is sized to clear this threshold). `metadata.usage.nativeUsage.prompt_tokens_details.cached_tokens` is 0 or absent on a fresh-cache run; non-zero is acceptable when OpenAI's server-side cache TTL hasn't expired from a prior local run (the local Reset cannot clear the server-side TTL — this is environmental, not a regression).
- After step 2: HTTP 200. Response `metadata.usage.nativeUsage.prompt_tokens_details.cached_tokens > 0`. The cached portion should be most of the prompt prefix; expect the cached count to be in the high hundreds at minimum.
- Two consecutive runs of the same exact prompt produce stable structural responses (both succeed, both have `usage` blocks).

If `cached_tokens` is 0 on step 2 with promptTokens ≥ 1024:

- Possible cause: prefix not byte-identical. Check that the assembled SystemMessage doesn't include user-instructions or memory that drift between turns. (For a fresh test user with no instructions / no memory, the prefix should be stable.)
- Possible cause: more than 5 minutes elapsed between calls (OpenAI's prefix cache TTL is ~5 min). Re-run the two steps closer together.

## Fixtures

(none. Uses no object-store / Qdrant content; the prompt is self-contained.)

## Concurrency

- **Mutates:** Postgres `chat_history` (user_id=`frostyPromptCacheOpenaiTest`); Redis keys `chat:frostyPromptCacheOpenaiTest` and `user:frostyPromptCacheOpenaiTest:instructions`; Qdrant collections `ascend_memory_*` (user-scoped: `frostyPromptCacheOpenaiTest`, written by the background memory extractor on any prompt)
- **Conflicts with:** none
- **Serial:** false
- **Hermetic contract:** Self-cleaning. `Post-run cleanup` removes every row and key the Run steps wrote. OpenAI's server-side prefix cache is outside this stack and expires on its own after roughly five minutes.
