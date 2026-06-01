# Prompt cache: OpenAI: e2e test

## What this verifies

OpenAI's automatic prefix caching fires on the second of two identical prompts sent to the same provider. The second response's `metadata.usage.nativeUsage.prompt_tokens_details.cached_tokens` is greater than zero. Validates that the `add-prompt-caching` change is wired correctly end-to-end against a live OpenAI provider.

> The wire format echoes OpenAI's own field names verbatim under `nativeUsage` (snake_case, nested under `prompt_tokens_details`). Earlier revisions of this spec referenced a camelCase shape (`promptTokensDetails.cachedTokens`); that shape was never on the wire and any older runs that asserted against it were reading nothing.

Hermetic: owns the `frostyPromptCacheOpenaiTest` chat-history rows (and Redis key). The first call seeds the cache; the second call hits it.

## Prerequisites

Check Bruno CLI, AscendAgent `/actuator/health`, Postgres + Redis healthy.

Check the `OPENAI_API_KEY` env var is configured for the running AscendAgent (from `.env` / docker-compose). Without it, OpenAI calls return an auth error and this test fails before it can assert anything about cache.

```bash
docker exec ascend-agent printenv OPENAI_API_KEY | head -c 8
```

Should print the first few chars of the key.

## Reset state

Truncate the test user's chat-history so the static prompt prefix is byte-identical between the two calls (no prior turns leaking into the prefix).

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyPromptCacheOpenaiTest';"
```

```bash
docker exec redis redis-cli DEL chat:frostyPromptCacheOpenaiTest
```

## Run

Step 1. First prompt (cache miss expected; this seeds OpenAI's prefix cache).

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/prompt-cache-openai.yml" --env ascend-local
```

Capture response 1's `metadata.usage` block. Note `nativeUsage.prompt_tokens_details.cached_tokens` (expected: 0 or absent on a fresh-cache run; non-zero is acceptable when OpenAI's server-side cache TTL hasn't expired from a prior local run) and `promptTokens` (expected: ≥ 1024, required for OpenAI auto cache to fire on the next call).

Step 2. Second prompt within ~5 minutes (cache hit expected). Same Bruno request, run again.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/prompt-cache-openai.yml" --env ascend-local
```

Capture response 2's `metadata.usage`. Note `nativeUsage.prompt_tokens_details.cached_tokens` (expected: > 0).

## Expected

- After step 1: HTTP 200. Response `metadata.usage.promptTokens >= 1024` (otherwise OpenAI's auto cache won't fire on the next call; the test prompt is sized to clear this threshold). `metadata.usage.nativeUsage.prompt_tokens_details.cached_tokens` is 0 or absent on a fresh-cache run; non-zero is acceptable when OpenAI's server-side cache TTL hasn't expired from a prior local run (the local Reset cannot clear the server-side TTL — this is environmental, not a regression).
- After step 2: HTTP 200. Response `metadata.usage.nativeUsage.prompt_tokens_details.cached_tokens > 0`. The cached portion should be most of the prompt prefix; expect the cached count to be in the high hundreds at minimum.
- Two consecutive runs of the same exact prompt produce stable structural responses (both succeed, both have `usage` blocks).

If `cached_tokens` is 0 on step 2 with promptTokens ≥ 1024:

- Possible cause: prefix not byte-identical. Check that the assembled SystemMessage doesn't include user-instructions or memory that drift between turns. (For a fresh test user with no instructions / no memory, the prefix should be stable.)
- Possible cause: more than 5 minutes elapsed between calls (OpenAI's prefix cache TTL is ~5 min). Re-run the two steps closer together.

## Fixtures

(none. Uses no MinIO / Qdrant content; the prompt is self-contained.)

## Concurrency

- **Mutates:** Postgres `chat_history` (user_id=`frostyPromptCacheOpenaiTest`); Redis key `chat:frostyPromptCacheOpenaiTest`
- **Conflicts with:** none
- **Serial:** false
