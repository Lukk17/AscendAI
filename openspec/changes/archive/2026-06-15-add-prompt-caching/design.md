## Context

AscendAgent's hot path (`ChatExecutor.execute`) assembles a `Prompt` whose first message is always the same `app.system-prompt` SystemMessage (~500 tokens). Every paid-provider turn pays for that prefix at the full input rate. Separately, the async memory-extraction pipeline (`SemanticMemoryExtractor`) sends a ~150-token static `EXTRACTOR_INSTRUCTION` on every extract call. Both prefixes are excellent caching candidates: stable across calls, well above the 1024-token threshold OpenAI requires when combined, and reused dozens of times per user-session.

This change introduces a per-provider caching layer that wraps the existing chat flow without changing its public contract.

## Provider Matrix (verified against Spring AI 1.1.4 sources during implementation)

| Provider name | Spring AI client used | Mechanism | Strategy impl | Default toggle |
|---|---|---|---|---|
| `anthropic` | spring-ai-anthropic | Native `AnthropicChatOptions.cacheOptions(AnthropicCacheOptions.builder().strategy(SYSTEM_ONLY).multiBlockSystemCaching(true).build())`. Reads `AnthropicApi.Usage.cacheReadInputTokens` / `cacheCreationInputTokens`. TTL default `FIVE_MINUTES` (controlled by `AnthropicCacheTtl` enum). | `AnthropicPromptCacheStrategy` | **on** |
| `openai` | spring-ai-openai | OpenAI auto-prefix-cache (≥1024-token prefix). Read-only — log `OpenAiApi.Usage.PromptTokensDetails.cachedTokens`. | `OpenAiPromptCacheStrategy` | **on** |
| `gemini` | spring-ai-openai (Gemini's OpenAI-compat surface — that's how this codebase wires it) | Same as openai. Native `CachedContent` would require switching to the Vertex client — **deferred**. | `OpenAiPromptCacheStrategy` (reused) | **on** |
| `minimax` | spring-ai-anthropic (MiniMax's Anthropic-compat surface) | `cache_control` is NOT documented as supported by MiniMax's compat endpoint. Sending it would risk a 400. | `NoopPromptCacheStrategy` | **off** |
| `lmstudio` | spring-ai-anthropic (LM Studio's Anthropic-compat surface) | No cache API. | `NoopPromptCacheStrategy` | **off** |

## Architectural Decisions

### Decision 1: One strategy per provider NAME (deviation from original)

`PromptCacheStrategy` is a small interface:

```java
public interface PromptCacheStrategy {
    String providerName();
    ChatOptions buildOptions(String model);            // returns provider-specific options w/ cache directive
    void recordOutcome(String userId, ChatResponse response);
    default boolean isCacheConfigError(Throwable t) { return false; }
}
```

**Deviation from the original Decision 1**: dispatch is by provider NAME, not by `ProviderConfig.type`. Reason: the codebase wires Gemini through `type: openai` (Google's OpenAI-compatible surface) and MiniMax through `type: anthropic` (MiniMax's Anthropic-compat surface). Type-based dispatch would (a) try to send `cache_control` to MiniMax which doesn't document support, and (b) skip OpenAI-style cached-token logging for Gemini. Provider-name dispatch matches actual cache-support boundaries.

`PromptCacheStrategyResolver` instantiates strategies in `@PostConstruct`, returns the matching one per call, and falls back to a per-provider `NoopPromptCacheStrategy` when either the master toggle or the per-provider toggle is off (or when the provider name is unknown).

### Decision 2: Strategies live in `service/cache/`

The package mirrors `service/memory/` and `service/ingestion/`. All three strategies are stateless. `GeminiPromptCacheStrategy` (with `CachedContent` lifecycle management) is **deferred** — Gemini in this codebase rides on the OpenAI-compat client and gets the same read-only treatment as OpenAI.

### Decision 2b: Static-vs-dynamic system message split via `AssembledSystemMessages`

`ChatContextAssembler.buildSystemMessages(...)` returns a new record `AssembledSystemMessages(String staticPrefix, String dynamicSuffix)`. The `staticPrefix` is the `app.system-prompt` text only — globally identical, eligible for provider caching. The `dynamicSuffix` carries per-user content (instructions, semantic memory) that varies per request.

`ChatExecutor` builds the prompt as `List.of(new SystemMessage(staticPrefix), new SystemMessage(dynamicSuffix), ...history)`. With `AnthropicCacheOptions.multiBlockSystemCaching(true)`, Spring AI emits each `SystemMessage` as a separate `system` array entry to the Anthropic API and applies `cache_control` to the second-to-last block — i.e., the static one. The dynamic block varies freely without invalidating the cache.

For OpenAI/Gemini the two SystemMessages are joined upstream of the wire (or sent as a multi-message system payload, depending on client). Either way the byte-prefix of the assembled system text is stable across users for the static portion, so OpenAI's auto prefix cache hits.

The existing `buildSystemMessage(...)` String form is kept as a thin adapter that returns `combined()` so non-cache callers don't break.

### Decision 3: Cache the system prompt and the extractor instruction; nothing else

Out of scope explicitly:

- **User memory and RAG context** vary per request — caching them is wrong.
- **Document content** attached via the `document` field is too variable.
- **Tool-callback definitions** would be a great cache target, but Spring AI 1.1.x's MCP integration injects them late in the chain in a way we'd have to monkey-patch. Defer to a future change once we audit the tool-callback surface.
- **Cross-user cache keys**: caching is per-prefix-content, which is global by construction (the system prompt is the same for everyone). User-scoped data does not enter the cached prefix, so there is no cross-user leak.

### Decision 4: Fallback always retries once without cache

If `decorate(...)` succeeded but the underlying provider call throws something we recognize as cache-related (Anthropic 400 mentioning `cache_control`, Gemini 404 / 400 on `cachedContent`, OpenAI is implicit so it can't fail this way), `ChatExecutor` catches and retries the call without the decoration, logs a WARN with the provider + reason, and serves the response normally. Cache failures never reach the user.

### Decision 5: Observability v1 = logs; counters live in `add-observability`

Each strategy's `recordOutcome(...)` reads `cached_tokens` (or equivalent) off the response metadata and logs at INFO:

```
[PromptCache] provider=anthropic hit=true cached_tokens=487 prompt_tokens=612
```

The `add-observability` change adds the matching Micrometer counters (`ai.prompt_cache.hits{provider}`, `ai.prompt_cache.misses{provider}`) on top of these log points. We don't add the counters here to avoid coupling the two changes.

### Decision 6: Prefix-stability test for OpenAI / MiniMax

OpenAI's automatic cache only fires when the prefix is byte-identical across calls. The test for `OpenAiPromptCacheStrategy` does not call OpenAI — it captures the constructed `Prompt` for two consecutive `ChatExecutor.execute` calls with the same `app.system-prompt` and asserts the first N tokens (or first system message text) are identical. This catches accidental nondeterminism (timestamps, request ids) sneaking into the prefix.

## Spring AI 1.1.x API Survey (RESULTS — verified against 1.1.4 sources during implementation)

- **`AnthropicChatOptions`**: ✅ `cacheOptions(AnthropicCacheOptions)` exposed since 1.1.0. `AnthropicCacheOptions` has `strategy` (`AnthropicCacheStrategy.{NONE, TOOLS_ONLY, SYSTEM_ONLY, SYSTEM_AND_TOOLS, CONVERSATION_HISTORY}`), per-`MessageType` `messageTypeTtl` (`AnthropicCacheTtl.{FIVE_MINUTES, ONE_HOUR}`), per-`MessageType` `messageTypeMinContentLengths`, and a `multiBlockSystemCaching` flag. `AnthropicApi.Usage` record carries `cacheReadInputTokens` + `cacheCreationInputTokens`. **No raw HTTP, no advisor needed.**
- **`OpenAiChatOptions`**: ✅ no cache decoration knob (caching is automatic ≥1024-token prefix). `OpenAiApi.Usage.PromptTokensDetails.cachedTokens` is surfaced via `Usage.getNativeUsage()` cast. Strategy is read-only.
- **`VertexAiGeminiChatOptions`**: not investigated — Gemini in this codebase is wired through the **OpenAI-compat** client, not Vertex. Native `CachedContent` is **deferred** to a follow-up change that would also swap the Gemini client.
- **MiniMax**: wired via spring-ai-anthropic (MiniMax's Anthropic-compat endpoint). MiniMax does NOT publicly document `cache_control` support; sending it would risk a 400. Strategy: noop with default-off toggle. Flip on once endpoint behavior is verified.

## Configuration (final)

```yaml
app:
  ai:
    prompt-cache:
      enabled: true        # master toggle
      providers:
        anthropic:
          enabled: true    # native cache_control via Spring AI 1.1.4
        openai:
          enabled: true    # auto prefix cache; read-only
        gemini:
          enabled: true    # rides on OpenAI-compat client; read-only
        minimax:
          enabled: false   # Anthropic-compat endpoint; cache_control unverified
        lmstudio:
          enabled: false   # no cache API
```

**Deviation from original config**: removed `gemini.cached-content-ttl` (no native CachedContent in v1).

## Cost Modeling (back-of-envelope)

Assumptions: ~650 token cached prefix (system prompt + tool descriptions where applicable), 25 turns/user/day, 100 active users, Anthropic Claude Sonnet 4.6 pricing as of 2026-05.

- Without cache: 650 × 25 × 100 × 30 = ~48.7 M input tokens/month at full rate.
- With cache (90% savings on cached tokens): same 48.7 M tokens, but billed at ~10% of full rate after the first call in each 5-min window.
- Net savings: roughly 40-43 M token-equivalents/month — material at any paid scale, irrelevant for LM Studio-only deployments (no-op anyway).

Exact dollar figures are intentionally not pinned in this doc since pricing changes; the rollout's `tasks.md` includes a "log dollar savings observed during week-1 rollout" verification step.

## Test Strategy

1. **Strategy unit tests** per provider — assert decorated prompt / options carry the expected cache directive (Anthropic block annotation, Gemini resource reference, OpenAI no-op, LM Studio no-op).
2. **`ChatExecutor` integration test (mocked provider)** — stub a `ChatResponse` whose metadata reports `cached_tokens=487`; assert the `[PromptCache] hit=true` log line fires and the response reaches the controller untouched.
3. **`SemanticMemoryExtractor` test** — assert the extractor instruction goes through the strategy on the extraction call.
4. **Fallback test** — first provider call throws a simulated cache-config exception; assert exactly one retry without decoration, exactly one WARN logged, and the user-visible response is the retry result.
5. **OpenAI prefix-stability test** — two consecutive `execute(...)` calls with the same input produce byte-identical first-N-token prefixes.

No real provider calls in CI.

## Rollout

1. Land the framework + Anthropic strategy + LM Studio no-op + tests. Default `app.ai.prompt-cache.enabled=true` but only Anthropic is wired; rest go through `NoopPromptCacheStrategy`.
2. Watch the `[PromptCache] hit=true` log line in staging for 48 hours on the Anthropic provider. Confirm `cached_tokens > 0` on every turn after the first in a session.
3. Land Gemini strategy. Repeat watch.
4. Land OpenAI / MiniMax prefix-stability strategy. Repeat watch.
5. Once `add-observability` lands, add the Micrometer counters as a follow-up.
6. Per-provider toggle gives us a fast kill-switch if any provider misbehaves.
