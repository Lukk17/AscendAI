## Why

Every chat turn in AscendAgent re-sends the same ~500-token static system prompt (`app.system-prompt` from `application.yaml`) and, on the asynchronous memory-extraction path, the same ~150-token static `EXTRACTOR_INSTRUCTION` from `SemanticMemoryExtractor`. Against paid providers (Anthropic, OpenAI, Gemini, MiniMax) those tokens are billed at full input rate on every single call, even though the prefix is byte-identical turn-over-turn. Across a typical session of 20-30 turns per user this is several thousand wasted input tokens per user per day, and it scales linearly with traffic.

Every supported paid provider now offers some form of prompt caching that drops cache-hit input cost by 75-90%:

- **Anthropic** — explicit `cache_control: ephemeral` markers on system blocks, 5 min / 1 hr TTL.
- **OpenAI** (and OpenAI-compatible MiniMax) — automatic prefix caching when the prompt is ≥ 1024 tokens, reported back as `cached_tokens` in response usage.
- **Gemini** — explicit `CachedContent` resource pre-created and referenced by name on each `generateContent`.
- **LM Studio** — local; no caching API.

Wiring this across providers is its own design problem because each one's API surface is different and Spring AI 1.1.x exposes them inconsistently. This change introduces a small per-provider abstraction inside AscendAgent so the static prefix is cached on every paid provider and the savings are observable.

## What Changes

- **Provider abstraction**: introduce `PromptCacheStrategy` (one impl per provider type, dispatched on `AiProviderProperties.ProviderConfig.type`) under `service/cache/`. Strategies decorate the outgoing `Prompt` / provider options with cache markers (Anthropic), pre-create-and-attach a `CachedContent` (Gemini), or no-op while verifying prefix stability (OpenAI / MiniMax). LM Studio strategy is a documented no-op.
- **Static prefixes covered**: (1) `app.system-prompt` used by every `ChatExecutor.execute`; (2) `SemanticMemoryExtractor.EXTRACTOR_INSTRUCTION` used on every async extraction. Tool-callback definitions are explicitly out of scope for v1 — Spring AI's MCP tool callback chain does not currently expose them as a stable cacheable block.
- **Configuration toggle**: new `app.ai.prompt-cache.enabled` (default `true`), with per-provider override `app.ai.prompt-cache.providers.<name>.enabled` and a Gemini-specific `cached-content-ttl` (default `PT10M`). When the master toggle is off all strategies become no-ops.
- **Observability**: each strategy reads back the provider's response metadata and logs `cached_input_tokens` / `cached_tokens` at INFO. Per-provider Micrometer counters (`ai.prompt_cache.hits` / `ai.prompt_cache.misses`) are deferred to the `add-observability` change and tracked there as a follow-up — for v1 we ship structured logs only.
- **Fallback behavior**: if a cache-decorated call fails because of cache config (e.g., Gemini `CachedContent` missing/expired, Anthropic rejects a malformed `cache_control` block), the runner SHALL retry once without cache, log a WARN, and serve the user normally. Cache must never break the chat flow.
- **Spring AI API survey baked into `design.md`**: `design.md` documents what each provider's Spring AI 1.1.x module actually exposes today, and where a custom advisor or raw HTTP call is needed because the framework option doesn't exist.
- **Test strategy**: pure-mock — strategy tests assert that the outgoing options/prompt carry the right cache directive for each provider; chat-flow tests stub the response to include `cached_tokens` and assert the log line fires. No real provider calls in CI.
- **Per-provider rollout**: caching is enabled per provider one at a time (Anthropic first, then Gemini, then OpenAI/MiniMax) with the metric / log reviewed in between.

## Capabilities

### New Capabilities

- `prompt-caching` — AscendAgent caches the static system-prompt prefix (and the memory-extractor instruction) on every supported paid provider via that provider's native cache mechanism, behind a master toggle and per-provider overrides, with graceful fallback when caching fails.

### Modified Capabilities

(none — this is a new capability layered on top of the existing chat and memory-extraction flows; no existing requirements change behavior except that token-usage logs gain a `cached_tokens` field where the provider reports it)

## Impact

- **Code**:
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/cache/PromptCacheStrategy.java` (new interface)
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/cache/AnthropicPromptCacheStrategy.java` (new)
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/cache/OpenAiPromptCacheStrategy.java` (new — verifies prefix stability, no-op on options)
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/cache/GeminiPromptCacheStrategy.java` (new — manages `CachedContent` lifecycle)
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/cache/NoopPromptCacheStrategy.java` (new — LM Studio)
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/cache/PromptCacheStrategyResolver.java` (dispatch on provider type)
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/ChatExecutor.java` (apply strategy before provider call; read back cache hit from response metadata)
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/memory/SemanticMemoryExtractor.java` (apply strategy on extractor instruction prefix)
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/properties/PromptCacheProperties.java` (new `@ConfigurationProperties("app.ai.prompt-cache")`)
  - `AscendAgent/src/main/resources/application.yaml` (new `app.ai.prompt-cache.*` block)
- **APIs**: no contract change. Response shape unchanged.
- **Dependencies**: none added. Uses Spring AI 1.1.x options surface that's already on the classpath. Custom raw-HTTP path for Gemini `CachedContent` is documented in `design.md` if Spring AI doesn't expose it natively.
- **Tests**: unit tests per strategy (option-shape assertions), `ChatExecutor` test asserting cache-hit log on a stubbed response, `SemanticMemoryExtractor` test asserting the extractor instruction goes through the strategy, fallback test asserting one retry without cache when the first call throws a cache-config exception.
- **Cost**: back-of-envelope in `design.md` — at ~650 cached tokens × ~25 turns/user/day × 100 users × Anthropic Claude Sonnet pricing, roughly $X/month saved. Justifies the work even at small scale.
