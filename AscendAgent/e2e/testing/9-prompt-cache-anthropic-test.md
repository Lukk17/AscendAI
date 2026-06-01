# Prompt cache: Anthropic: e2e test

## What this verifies

Anthropic's native `cache_control` (wired via Spring AI 1.1.5's `AnthropicCacheOptions(SYSTEM_ONLY, multiBlockSystemCaching=true)`) fires on the second of two identical prompts sent to `provider=anthropic`. The second response's `metadata.usage.cacheReadInputTokens` is greater than zero. Validates the `add-prompt-caching` change end-to-end against the real Anthropic API.

Hermetic: owns the `frostyPromptCacheAnthropicTest` chat-history rows.

## Prerequisites

Check Bruno CLI, AscendAgent `/actuator/health`, Postgres + Redis healthy.

Check the `ASCEND_ANTHROPIC_API_KEY` env var is configured for the running AscendAgent.

```bash
docker exec ascend-agent printenv ASCEND_ANTHROPIC_API_KEY | head -c 8
```

## Reset state

Truncate the test user's chat-history so the static prefix is byte-identical between the two calls.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyPromptCacheAnthropicTest';"
```

```bash
docker exec redis redis-cli DEL chat:frostyPromptCacheAnthropicTest
```

## Run

Step 1. First prompt (cache miss expected; this writes the cache entry).

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/prompt-cache-anthropic.yml" --env ascend-local
```

Capture response 1's `metadata.usage`. Note `cacheCreationInputTokens` (expected: > 0, Anthropic charges to write the cache entry on the first call).

Step 2. Second prompt within ~5 minutes (cache hit expected).

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/prompt-cache-anthropic.yml" --env ascend-local
```

Capture response 2's `metadata.usage`. Note `cacheReadInputTokens` (expected: > 0 and equal-ish to step-1's `cacheCreationInputTokens`).

## Expected

- After step 1: HTTP 200. Response `metadata.usage.cacheCreationInputTokens > 0` OR `metadata.usage.cacheReadInputTokens > 0`. Anthropic charges to populate the cache on a true cold start; on a warm-cache cold-test (a previous identical prompt fired within the last ~5 minutes, e.g. during in-session iteration on the test itself) you observe a read instead of a creation. Either path proves the `cache_control` directive was accepted.
- After step 2: HTTP 200. Response `metadata.usage.cacheReadInputTokens > 0`. The read count should approximate step-1's `cacheCreationInputTokens + cacheReadInputTokens` total (the cached chunk hasn't grown between the two calls).
- Both responses succeed structurally.

If `cacheReadInputTokens` is 0 on step 2:

- Possible cause: Spring AI `AnthropicCacheOptions` not actually applied. Check Spring AI version is `1.1.5`; verify `AnthropicPromptCacheStrategy` is being resolved by the resolver for `provider=anthropic` (check the boot log for the `[PromptCache]` resolver init line).
- Possible cause: more than 5 minutes elapsed between calls (Anthropic's `ephemeral` cache TTL is 5 min by default). Re-run closer together.
- Possible cause: prompt body too short. Anthropic requires a minimum content length per cache breakpoint (a few hundred tokens). The test prompt is sized to clear that minimum.

## Fixtures

(none)

## Concurrency

- **Mutates:** Postgres `chat_history` (user_id=`frostyPromptCacheAnthropicTest`); Redis key `chat:frostyPromptCacheAnthropicTest`
- **Conflicts with:** none
- **Serial:** false
