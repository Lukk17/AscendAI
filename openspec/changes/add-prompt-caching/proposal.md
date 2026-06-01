## Why

Every chat turn in AscendAgent re-sends the same ~500-token static system prompt (`app.system-prompt` from `application.yaml`) and, on the asynchronous memory-extraction path, the same ~150-token static `EXTRACTOR_INSTRUCTION` from `SemanticMemoryExtractor`. Against paid providers (Anthropic, OpenAI, Gemini, MiniMax) those tokens are billed at full input rate on every single call, even though the prefix is byte-identical turn-over-turn. Across a typical session of 20-30 turns per user this is several thousand wasted input tokens per user per day, and it scales linearly with traffic.

Every supported paid provider now offers some form of prompt caching that drops cache-hit input cost by 75-90%:

- **Anthropic** — explicit `cache_control: ephemeral` markers on system blocks, 5 min / 1 hr TTL.
- **OpenAI** (and OpenAI-compatible MiniMax) — automatic prefix caching when the prompt is ≥ 1024 tokens, reported back as `cached_tokens` in response usage.
- **Gemini** — explicit `CachedContent` resource pre-created and referenced by name on each `generateContent`.
- **LM Studio** — local; no caching API.

Wiring this across providers is its own design problem because each one's API surface is different and Spring AI 1.1.x exposes them inconsistently. This change introduces a small per-provider abstraction inside AscendAgent so the static prefix is cached on every paid provider and the savings are observable.

## What Changes

- **Provider abstraction**: `PromptCacheStrategy` interface under `service/cache/` with three implementations (`AnthropicPromptCacheStrategy`, `OpenAiPromptCacheStrategy`, `NoopPromptCacheStrategy`). Dispatch is by **provider name** (not type) because in this codebase Gemini is wired through the OpenAI-compat client (`type: openai`), so native Gemini `CachedContent` is unreachable without switching to the Vertex client. Strategies build provider-specific `ChatOptions` with cache directives (Anthropic) or pass through (OpenAI/Gemini auto-prefix-cache).
- **Static prefixes covered**: (1) `app.system-prompt` used by every `ChatExecutor.execute`; (2) `SemanticMemoryExtractor.EXTRACTOR_INSTRUCTION` used on every async extraction. Tool-callback definitions are explicitly out of scope for v1 — Spring AI's MCP tool callback chain does not expose them as a stable cacheable block.
- **System message split**: `ChatContextAssembler` now exposes `buildSystemMessages(...)` returning `AssembledSystemMessages(staticPrefix, dynamicSuffix)`. `ChatExecutor` constructs the prompt with TWO `SystemMessage` instances (static, dynamic) so Spring AI's `AnthropicCacheOptions.multiBlockSystemCaching=true` marks `cache_control` on the static block only. The existing single-String `buildSystemMessage(...)` is kept for back-compat with current callers.
- **Configuration toggle**: new `app.ai.prompt-cache.enabled` (default `true`), with per-provider override `app.ai.prompt-cache.providers.<name>.enabled`. Defaults: anthropic + openai + gemini = `true`; **minimax + lmstudio = `false`** (conservative; MiniMax uses the Anthropic-compat endpoint but does NOT document `cache_control` support; LM Studio has no cache API).
- **Observability**: each strategy logs `[PromptCache] provider=X user=Y hit=BOOL cached_tokens=N prompt_tokens=N` at INFO. Anthropic reads `cacheReadInputTokens` from `AnthropicApi.Usage`. OpenAI/Gemini read `prompt_tokens_details.cached_tokens` from `OpenAiApi.Usage.PromptTokensDetails`. Per-provider Micrometer counters are deferred to `add-observability`.
- **Fallback behavior**: if Anthropic returns a 400 referencing `cache_control`, `ChatExecutor` and `SemanticMemoryExtractor` both retry exactly once with un-decorated options, log a single WARN, and serve the result. Non-cache exceptions propagate unchanged.
- **Spring AI native API used**: `AnthropicChatOptions.cacheOptions(AnthropicCacheOptions)` with `AnthropicCacheStrategy.SYSTEM_ONLY` + `multiBlockSystemCaching(true)`. No raw HTTP, no advisor mutation, no JSON post-processing needed.
- **Test strategy**: pure-mock — strategy unit tests assert that decorated `ChatOptions` carry the expected cache directive shape; resolver tests cover the toggle matrix; existing `ChatExecutorTest` and `SemanticMemoryExtractorTest` updated to inject a noop resolver. No real provider calls in CI.

## Capabilities

### New Capabilities

- `prompt-caching` — AscendAgent caches the static system-prompt prefix (and the memory-extractor instruction) on every supported paid provider via that provider's native cache mechanism, behind a master toggle and per-provider overrides, with graceful fallback when caching fails.

### Modified Capabilities

(none — this is a new capability layered on top of the existing chat and memory-extraction flows; no existing requirements change behavior except that token-usage logs gain a `cached_tokens` field where the provider reports it)

## Impact

- **Code (final, as implemented)**:
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/cache/PromptCacheStrategy.java` — interface
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/cache/AnthropicPromptCacheStrategy.java` — uses Spring AI 1.1.4 native `AnthropicChatOptions.cacheOptions(...)` + `AnthropicCacheStrategy.SYSTEM_ONLY` + `multiBlockSystemCaching=true`; reads back `AnthropicApi.Usage.cacheReadInputTokens`
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/cache/OpenAiPromptCacheStrategy.java` — read-only; logs `OpenAiApi.Usage.PromptTokensDetails.cachedTokens`. Used for both `openai` and `gemini` provider names.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/cache/NoopPromptCacheStrategy.java` — passthrough; used for `lmstudio` and `minimax`, and as the universal fallback when toggles are off.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/cache/PromptCacheStrategyResolver.java` — dispatches by **provider name** with toggle awareness.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/ChatExecutor.java` — new `execute(...)` overload taking `AssembledSystemMessages`; constructs prompt with two `SystemMessage`s (static + dynamic); applies strategy options + fallback retry; calls `recordOutcome` after.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/memory/SemanticMemoryExtractor.java` — applies strategy + fallback retry on the extractor invocation; `EXTRACTOR_INSTRUCTION` sent as `SystemMessage` (not `defaultSystem`) so cache markers reach the request.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/ChatContextAssembler.java` — new `buildSystemMessages(...)` returns `AssembledSystemMessages(staticPrefix, dynamicSuffix)`. Existing `buildSystemMessage(...)` String form kept as a thin combined-text adapter.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/AssembledSystemMessages.java` — new record.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/AscendChatService.java` — switched to `buildSystemMessages` + new `ChatExecutor.execute` overload.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/properties/PromptCacheProperties.java` — new `@ConfigurationProperties("app.ai.prompt-cache")` with `enabled` master + per-provider `Map<String, ProviderCache>`.
  - `AscendAgent/src/main/resources/application.yaml` — new `app.ai.prompt-cache.*` block; defaults true for anthropic/openai/gemini, false for minimax/lmstudio.
- **APIs**: no contract change. Response shape unchanged.
- **Dependencies**: none added. Spring AI 1.1.4 already on the classpath has full native Anthropic cache support; no raw HTTP / no advisor mutation needed (significant simplification vs. the original design).
- **Tests**: unit tests per strategy (option-shape + outcome-log + cache-error detection), resolver toggle-matrix test, `PropertiesTest` row, plus existing `ChatExecutorTest` and `SemanticMemoryExtractorTest` updated to inject a noop resolver.
- **Deviations from the original proposal/design** documented in `design.md` Deviations section:
  - Provider-name dispatch (not type-based) because the codebase wires Gemini via `type: openai`.
  - Native Gemini `CachedContent` is **deferred** — would require swapping the Gemini client to the Vertex SDK.
  - MiniMax + LM Studio default-OFF (not always-on with master toggle).
  - No tool-callback caching in v1.
  - No Micrometer counters in v1 (deferred to `add-observability`).
