## Context

AscendAgent's hot path (`ChatExecutor.execute`) assembles a `Prompt` whose first message is always the same `app.system-prompt` SystemMessage (~500 tokens). Every paid-provider turn pays for that prefix at the full input rate. Separately, the async memory-extraction pipeline (`SemanticMemoryExtractor`) sends a ~150-token static `EXTRACTOR_INSTRUCTION` on every extract call. Both prefixes are excellent caching candidates: stable across calls, well above the 1024-token threshold OpenAI requires when combined, and reused dozens of times per user-session.

This change introduces a per-provider caching layer that wraps the existing chat flow without changing its public contract.

## Provider Matrix

| Provider | Mechanism | Knob | TTL | Reported Hit Field | Spring AI 1.1.x exposure |
|---|---|---|---|---|---|
| Anthropic | Explicit `cache_control: { type: "ephemeral" }` on system block | Per-block annotation | 5 min default; 1 hr with `ttl` extension | `usage.cache_read_input_tokens` / `cache_creation_input_tokens` | `AnthropicChatOptions` — verify exact field name during impl; if absent, use a `RequestResponseAdvisor` to mutate the outgoing JSON before the HTTP call |
| OpenAI (GPT-4o, GPT-5) | Automatic prefix cache when prompt ≥ 1024 tokens | None — implicit | ~5 min sliding | `usage.prompt_tokens_details.cached_tokens` | Read-only via response metadata; verify prefix stability is our only job |
| MiniMax | OpenAI-compatible endpoint; same automatic behavior | None | Provider-defined | Same field as OpenAI when supported | Treat identically to OpenAI |
| Gemini | Pre-create `CachedContent` resource, reference by `cachedContent: <name>` | Resource lifecycle | Configurable, min 1 min | `usageMetadata.cachedContentTokenCount` | Spring AI 1.1.x `VertexAiGeminiChatOptions` may not expose `cachedContent`; fallback is a thin `GeminiCachedContentClient` that calls the REST API directly and a `RequestResponseAdvisor` that injects the resource name |
| LM Studio | None (local) | — | — | — | No-op strategy; documented |

## Architectural Decisions

### Decision 1: One strategy per provider type, dispatched on `ProviderConfig.type`

`PromptCacheStrategy` is a small interface:

```java
public interface PromptCacheStrategy {
    PromptCacheDecoration decorate(PromptCacheRequest request);
    void recordOutcome(PromptCacheOutcome outcome);
}
```

`PromptCacheStrategyResolver` injects a `Map<String, PromptCacheStrategy>` keyed by provider type (`anthropic`, `openai`, `minimax`, `gemini`, `lmstudio`) and resolves per request using the same `AiProviderProperties.ProviderConfig.type` that already drives client selection. This keeps the dispatch consistent with the rest of the codebase and avoids a new enum.

### Decision 2: Strategies live in `service/cache/`

The package mirrors `service/memory/` and `service/ingestion/`. They are stateless beans except for `GeminiPromptCacheStrategy`, which holds an in-memory map of `(systemPromptHash, cachedContentName, expiresAt)` to avoid recreating the `CachedContent` on every call. Eviction is lazy (check `expiresAt` on lookup; recreate on miss).

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

## Spring AI 1.1.x API Survey (to be confirmed during implementation)

The following must be verified against the actual Spring AI 1.1.4 sources during implementation, not assumed:

- **`AnthropicChatOptions`**: check whether `cacheControl` (or similar) is exposed. If yes, set on the outgoing options. If no, register a `RequestResponseAdvisor` that mutates the outgoing JSON to attach `cache_control` to the system block. `design.md` updates with the chosen path during impl.
- **`OpenAiChatOptions`**: no caching knob expected (caching is automatic). Confirm `cached_tokens` is surfaced in `ChatResponse.metadata().getUsage()` or whether we need to read raw provider metadata via `chatResponse.getMetadata().get("usage.prompt_tokens_details.cached_tokens")`.
- **`VertexAiGeminiChatOptions`**: check for `cachedContent` field. If absent, ship `GeminiCachedContentClient` (thin `RestClient`-based wrapper around the Generative Language `cachedContents` REST API) and inject the resource name via an advisor.
- **MiniMax**: shares the OpenAI client adapter; behavior identical.

If any provider's framework support is too thin to wire cleanly, fallback to the raw-HTTP path is acceptable as long as it's documented in `design.md` honestly. We do not promise framework-level support that doesn't exist.

## Configuration

```yaml
app:
  ai:
    prompt-cache:
      enabled: true               # master toggle
      providers:
        anthropic:
          enabled: true
        openai:
          enabled: true
        gemini:
          enabled: true
          cached-content-ttl: PT10M
        minimax:
          enabled: true
        lmstudio:
          enabled: false          # no-op anyway
```

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
