## 1. Foundations — interface, properties, resolver

- [ ] 1.1 Create `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/cache/PromptCacheStrategy.java` with `decorate(PromptCacheRequest)` and `recordOutcome(PromptCacheOutcome)` methods
- [ ] 1.2 Create `PromptCacheRequest` and `PromptCacheOutcome` records (provider type, prompt, options, response metadata)
- [ ] 1.3 Create `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/properties/PromptCacheProperties.java` bound to `app.ai.prompt-cache` (enabled, per-provider map, gemini `cachedContentTtl`)
- [ ] 1.4 Add the `app.ai.prompt-cache.*` block to `AscendAgent/src/main/resources/application.yaml` with documented defaults
- [ ] 1.5 Create `PromptCacheStrategyResolver` injecting `Map<String, PromptCacheStrategy>` and dispatching on `AiProviderProperties.ProviderConfig.type`
- [ ] 1.6 Unit test: resolver returns the matching strategy per provider type and the `Noop` strategy when the master toggle is off

## 2. Spring AI 1.1.x API survey (verification before each impl)

- [ ] 2.1 Inspect `AnthropicChatOptions` source on the classpath; document whether `cacheControl` is exposed; record the chosen integration path (options field vs. advisor) in `design.md` survey section
- [ ] 2.2 Inspect `OpenAiChatOptions` and `ChatResponse.metadata()` paths to surface `cached_tokens`; document the exact accessor in `design.md`
- [ ] 2.3 Inspect `VertexAiGeminiChatOptions` for `cachedContent` support; if absent, decide on a thin REST client and document
- [ ] 2.4 Confirm MiniMax adapter shares the OpenAI options surface (it currently does)

## 3. Anthropic strategy (first rollout)

- [ ] 3.1 Implement `AnthropicPromptCacheStrategy` — decorate the SystemMessage block with `cache_control: ephemeral` via the path chosen in 2.1
- [ ] 3.2 Read back `cache_read_input_tokens` / `cache_creation_input_tokens` from response metadata in `recordOutcome`
- [ ] 3.3 Log `[PromptCache] provider=anthropic hit=<bool> cached_tokens=<n> prompt_tokens=<n>` at INFO
- [ ] 3.4 Unit test: decorated outgoing options carry the cache-control marker on the system block
- [ ] 3.5 Unit test: response with `cache_read_input_tokens=487` produces the `hit=true` log line

## 4. LM Studio no-op strategy

- [ ] 4.1 Implement `NoopPromptCacheStrategy` — pass-through `decorate`, no-op `recordOutcome`
- [ ] 4.2 Wire to provider type `lmstudio`
- [ ] 4.3 Unit test: decorate returns the request unchanged

## 5. OpenAI strategy + prefix stability

- [ ] 5.1 Implement `OpenAiPromptCacheStrategy` — `decorate` is a pass-through; `recordOutcome` reads `prompt_tokens_details.cached_tokens` and logs the same INFO line shape
- [ ] 5.2 Wire to provider type `openai` and `minimax`
- [ ] 5.3 Unit test: two consecutive `decorate` calls with the same input produce byte-identical SystemMessage text in the outgoing prompt
- [ ] 5.4 Unit test: stubbed response with `cached_tokens=512` produces `hit=true` log

## 6. Gemini strategy

- [ ] 6.1 If Spring AI exposes `cachedContent`, implement via options. Otherwise, build `GeminiCachedContentClient` — a `RestClient`-based wrapper around `https://generativelanguage.googleapis.com/v1beta/cachedContents`
- [ ] 6.2 Implement `GeminiPromptCacheStrategy` — on `decorate`, look up `(systemPromptHash → cachedContentName)` in an in-memory map; if missing or expired, create a new `CachedContent` with TTL from properties; attach the resource name to the outgoing request via options or advisor
- [ ] 6.3 `recordOutcome` reads `usageMetadata.cachedContentTokenCount`
- [ ] 6.4 Unit test: decorate creates a `CachedContent` on first call and reuses on the second
- [ ] 6.5 Unit test: expired entry triggers a re-create

## 7. Wire strategies into `ChatExecutor` and `SemanticMemoryExtractor`

- [ ] 7.1 In `ChatExecutor.execute`, resolve the strategy for the active provider and apply `decorate(...)` before the provider call
- [ ] 7.2 After the call, invoke `recordOutcome(...)` with the response metadata
- [ ] 7.3 In `SemanticMemoryExtractor`, do the same on the extractor-instruction prompt
- [ ] 7.4 Unit test: `ChatExecutor` calls the resolved strategy exactly once per request
- [ ] 7.5 Unit test: extractor calls the resolved strategy exactly once per extraction

## 8. Fallback on cache-config failure

- [ ] 8.1 In `ChatExecutor`, wrap the decorated provider call in try/catch for the recognized cache-related exception types (Anthropic 400 with `cache_control` in body; Gemini 4xx on `cachedContent`)
- [ ] 8.2 On catch: log `[PromptCache] provider=<x> WARN cache call failed, retrying without cache: <reason>`, then re-call the provider with the undecorated request, and serve that result
- [ ] 8.3 Apply the same wrapper inside `SemanticMemoryExtractor`
- [ ] 8.4 Unit test: simulated cache-config exception triggers exactly one retry without decoration and the WARN line fires
- [ ] 8.5 Unit test: a non-cache exception is NOT swallowed (no retry, original exception bubbles)

## 9. Configuration and toggles

- [ ] 9.1 Master `app.ai.prompt-cache.enabled=false` produces `NoopPromptCacheStrategy` for every provider
- [ ] 9.2 Per-provider override `app.ai.prompt-cache.providers.anthropic.enabled=false` falls back to `Noop` for that provider only
- [ ] 9.3 Test: matrix asserting toggle interactions (master off + provider on = Noop; master on + provider off = Noop; master on + provider on = strategy)

## 10. Cross-cutting verification

- [ ] 10.1 Run `./gradlew test` — all new tests pass
- [ ] 10.2 Run `./gradlew build` — clean build
- [ ] 10.3 Manual rollout step: deploy with only Anthropic strategy active. Send a prompt as `frosty` twice in succession. Confirm log shows `cached_tokens=0` on call 1 and `cached_tokens>0` on call 2.
- [ ] 10.4 Repeat for Gemini once 6.* lands.
- [ ] 10.5 Repeat for OpenAI / MiniMax once 5.* lands.
- [ ] 10.6 After a week of rollout, capture observed `cached_tokens` from logs and pin a real dollar-saved estimate into `design.md` Cost Modeling section.

## 11. Follow-ups (deferred)

- [ ] 11.1 Add `ai.prompt_cache.hits{provider}` and `ai.prompt_cache.misses{provider}` Micrometer counters — landed in `add-observability` change
- [ ] 11.2 Audit Spring AI MCP tool-callback chain to determine whether tool definitions can be cached as a stable block — separate future change
