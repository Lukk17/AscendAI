# Prompt cache: Anthropic: e2e test

## What this verifies

Anthropic's native `cache_control` (wired via Spring AI 1.1.5's `AnthropicCacheOptions(SYSTEM_ONLY, multiBlockSystemCaching=true)`) fires on the second of two identical prompts sent to `provider=anthropic`. The second response's `metadata.usage.nativeUsage.cache_read_input_tokens` is greater than zero. Validates the `add-prompt-caching` change end-to-end against the real Anthropic API.

> The wire format echoes Anthropic's own field names verbatim under `nativeUsage` (snake_case). Earlier revisions of this spec referenced a camelCase shape (`cacheCreationInputTokens`, `cacheReadInputTokens`) directly on `metadata.usage`; that shape was never on the wire and any older runs that asserted against it were reading nothing. `AnthropicApi.Usage` (Spring AI 1.1.5, `org.springframework.ai.anthropic.api.AnthropicApi`) declares the fields as `@JsonProperty("cache_creation_input_tokens") Integer cacheCreationInputTokens` and `@JsonProperty("cache_read_input_tokens") Integer cacheReadInputTokens`, and that object is carried unmodified as `DefaultUsage.nativeUsage` (`org.springframework.ai.chat.metadata.DefaultUsage`).

Hermetic: owns the `frostyPromptCacheAnthropicTest` chat-history rows.

## Prerequisites

Check Bruno CLI, ascend-ai-agent `/actuator/health`, Postgres + Redis healthy.

Check the `ASCEND_ANTHROPIC_API_KEY` env var is configured for the running ascend-ai-agent.

```bash
docker exec ascend-agent sh -c '[ -n "$ASCEND_ANTHROPIC_API_KEY" ] && echo present || echo missing'
```

Should print `present`. Never `printenv` the raw value, even truncated. This check proves the variable is set
without printing any of it.

## Reset state

Truncate the test user's chat-history so the static prefix is byte-identical between the two calls.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyPromptCacheAnthropicTest';"
```

```bash
docker exec redis redis-cli DEL chat:frostyPromptCacheAnthropicTest
```

Drop the Redis instructions cache key so the pre-run reset and the Post-run cleanup stay symmetric.

```bash
docker exec redis redis-cli DEL user:frostyPromptCacheAnthropicTest:instructions
```

## Run

Step 1. First prompt (cache miss expected; this writes the cache entry).

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ascend-agent/testing/prompt-cache-anthropic.yml" --env ascend-local
```

Capture response 1's `metadata.usage`. Note `nativeUsage.cache_creation_input_tokens` (expected: > 0, Anthropic charges to write the cache entry on the first call).

Step 2. Second prompt within ~5 minutes (cache hit expected).

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ascend-agent/testing/prompt-cache-anthropic.yml" --env ascend-local
```

Capture response 2's `metadata.usage`. Note `nativeUsage.cache_read_input_tokens` (expected: > 0 and equal-ish to step-1's `nativeUsage.cache_creation_input_tokens`).

## Post-run cleanup

The Reset section clears the `chat_history` rows and the Redis `chat:` key before the run, and the two prompt calls write both again. The run also leaves a Redis instructions-cache entry that `UserInstructionService` writes on every prompt (an `EMPTY` marker with a 24 hour TTL when the user has no stored instructions). Remove all three so the run leaves the system exactly as it found it. Run these regardless of whether the Run steps passed or failed. Every command is idempotent.

Drop this spec's chat-history rows.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyPromptCacheAnthropicTest';"
```

Drop the Redis chat cache key.

```bash
docker exec redis redis-cli DEL chat:frostyPromptCacheAnthropicTest
```

Drop the Redis instructions cache key.

```bash
docker exec redis redis-cli DEL user:frostyPromptCacheAnthropicTest:instructions
```

Wipe any semantic-memory points AscendMemory's background extractor stored for this user. The agent runs the extractor after every prompt, whether or not it concerns memory. With no `provider` query parameter the endpoint clears the user across every provider collection, which stays correct if the embedding provider changes.

```bash
curl -sS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyPromptCacheAnthropicTest"
```

Expect `{"status":"success","message":"All memories wiped for user frostyPromptCacheAnthropicTest"}`.

Nothing else survives the run. This spec sends no attachment, uploads no object and triggers no ingestion, so the object store, `int_metadata_store` and the RAG collection are untouched.

## Expected

- After step 1: HTTP 200. Response `metadata.usage.nativeUsage.cache_creation_input_tokens > 0` OR `metadata.usage.nativeUsage.cache_read_input_tokens > 0`. Anthropic charges to populate the cache on a true cold start; on a warm-cache cold-test (a previous identical prompt fired within the last ~5 minutes, e.g. during in-session iteration on the test itself) you observe a read instead of a creation. Either path proves the `cache_control` directive was accepted.
- After step 2: HTTP 200. Response `metadata.usage.nativeUsage.cache_read_input_tokens > 0`. The read count should approximate step-1's `cache_creation_input_tokens + cache_read_input_tokens` total (the cached chunk hasn't grown between the two calls).
- Both responses succeed structurally.

If `nativeUsage.cache_read_input_tokens` is 0 on step 2:

- Possible cause: Spring AI `AnthropicCacheOptions` not actually applied. Check Spring AI version is `1.1.5`; verify `AnthropicPromptCacheStrategy` is being resolved by the resolver for `provider=anthropic` (check the boot log for the `[PromptCache]` resolver init line).
- Possible cause: more than 5 minutes elapsed between calls (Anthropic's `ephemeral` cache TTL is 5 min by default). Re-run closer together.
- Possible cause: prompt body too short. Anthropic requires a minimum content length per cache breakpoint (a few hundred tokens). The test prompt is sized to clear that minimum.

## Fixtures

(none)

## Concurrency

- **Mutates:** Postgres `chat_history` (user_id=`frostyPromptCacheAnthropicTest`); Redis keys `chat:frostyPromptCacheAnthropicTest` and `user:frostyPromptCacheAnthropicTest:instructions`; Qdrant collections `ascend_memory_*` (user-scoped: `frostyPromptCacheAnthropicTest`, written by the background memory extractor on any prompt)
- **Conflicts with:** none
- **Serial:** false
- **Hermetic contract:** Self-cleaning. `Post-run cleanup` removes every row and key the Run steps wrote. Anthropic's ephemeral cache entry lives on Anthropic's side and expires on its own after roughly five minutes.
