## Why

Long conversations defeat both economics and quality. Every turn the AscendAgent fans out the *entire* chat history to the model — once a session crosses ~20 turns the input bill climbs faster than the response value, and the model's attention starts to drop the middle of the transcript (the well-documented "lost in the middle" effect). Today there is no relief valve: `PersistentChatMemory` only knows how to truncate by `maxSize` (default 5), which keeps cost bounded but throws away the long arc of the conversation entirely. We need a compaction step that preserves the *meaning* of older turns at a fraction of the token cost, runs automatically once a conversation gets long, and lets callers override the compaction model per request (so a cheap default doesn't surprise someone on a high-stakes prompt).

## What Changes

- Add `app.memory.chat-history.compaction.*` config: master `enabled` flag (default `true` but only fires when the toggle path has at least one backend active), trigger thresholds (`turn-trigger` default `20`, `token-trigger` default fraction `0.5` of the resolved provider context window), `keep-recent-turns` (default `8`), `max-summary-tokens` (default `800`), and a per-provider default `compaction-model` map populated with the cheapest sensible variant per provider.
- New `ChatHistoryCompactionProperties` `@ConfigurationProperties` class at prefix `app.memory.chat-history.compaction`, mirroring the `ChatHistoryProperties` style.
- New `ChatHistoryCompactionService` orchestrating: read full history → check trigger → call the cheap compaction model → replace the compacted prefix in both Redis and Postgres with a single `SystemMessage` whose text begins with the literal marker `[Conversation summary]` so the operation is idempotent on subsequent runs.
- Wire compaction into the existing `PersistentChatMemory.add(...)` write path **after** the persistence side-effects, fire-and-forget on the same `@Async` executor already in use for `persistToDb`. A failure in compaction never fails the user's turn.
- Add two new optional fields to the `/api/v1/ai/prompt` request: `compactionProvider` and `compactionModel`. Both default to the configured per-provider entry for the request's primary `provider`. Either or both can override.
- Compaction SHALL short-circuit when both chat-history backends are disabled (there is no history to compact), and SHALL be a no-op when the most recent compaction summary is the only message past `keep-recent-turns` (idempotency).
- Existing `memory-extraction-model` per-provider field stays untouched — compaction model is a separate concern (longer-context summarisation vs. JSON-output extraction); the new `compaction-model` field is parallel to it.

## Capabilities

### New Capabilities

- `chat-history-compaction`: automatic, idempotent, model-driven summarisation of older chat turns when a conversation exceeds a configurable threshold, with per-provider cheap-model defaults and per-request override fields on the prompt API.

### Modified Capabilities

(none — `chat-history-persistence` and `chat-history-persistence-toggle` remain semantically unchanged. Compaction layers on top of the existing add/get contract without altering it.)

## Impact

- **Code (new, as implemented)**:
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/properties/ChatHistoryCompactionProperties.java`
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/memory/ChatHistoryCompactionService.java`
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/memory/CompactionOverride.java` — record threading the per-request override
- **Code (modified, as implemented)**:
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/memory/PersistentChatMemory.java` — constructor now injects `ChatHistoryCompactionService` + `ChatHistoryCompactionProperties`. New 4-arg `add(conversationId, messages, primaryProvider, override)` overload; existing 2-arg form delegates with `null` provider and `CompactionOverride.EMPTY`. Tail-call to `compactionService.maybeCompact(...)` after persistence side-effects, wrapped in try/catch that swallows. Effective Redis trim size auto-computed as `max(maxSize, keepRecentTurns + 1)` when compaction is enabled, so the freshly-written summary survives the next user-turn trim.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/repository/ChatHistoryRepository.java` — added `findAllHistoryOrdered(userId)` for full-conversation reads. Prefix-replacement uses `deleteAllById(...)` + `save(...)` driven from the compaction service inside a `TransactionTemplate.executeWithoutResult` block — a simpler choice than introducing a new repo default method (`replaceRangeWithSummary` from the original sketch is not added; transactional semantics live in the service via Spring's `TransactionTemplate`). No `model/ChatHistory.java` change — the existing `role='system'` + `[Conversation summary]` marker is enough.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/ChatHistoryService.java` — new 5-arg `saveHistory(userId, prompt, response, primaryProvider, override)`; existing 3-arg form delegates.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/AscendChatService.java` — new 9-arg `prompt(...)` overload accepting `CompactionOverride`; older overloads delegate.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/controller/PromptController.java` — two new `@RequestParam`s `compactionProvider` and `compactionModel` (multipart, not JSON — matches the existing PromptController shape). `compactionProvider` validated against `AiProviderProperties.getProviders()` keys; unknown values return HTTP 400. `AiProviderProperties` injected.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/StartupLogConfig.java` — banner gains `Compaction:` line below `Chat History:` showing `[Enabled] (trigger: N turns / P% context, keep: K turns, defaults: ...)` or `[Disabled]`.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/AppConfig.java` — added `@EnableAsync(proxyTargetClass = true)` (latent-bug fix: `@Async` was ignored before this change because no `@EnableAsync` was on the classpath; CGLIB proxies needed because `PersistentChatMemory` is injected as the concrete type for the new 4-arg `add(...)` overload). Added `TransactionTemplate` `@Bean` (Spring Boot doesn't auto-configure it).
  - `AscendAgent/src/main/resources/application.yaml` — new `app.memory.chat-history.compaction` block with documented defaults including `provider-defaults` map.
  - `docker-compose.yaml` + `.env.example` — new `APP_MEMORY_CHATHISTORY_COMPACTION_ENABLED` env knob (boolean only; map stays yaml).
- **APIs**: `/api/v1/ai/prompt` gains two backward-compatible optional fields. Existing callers see no behaviour change.
- **Tests**: `ChatHistoryCompactionPropertiesTest` row in `PropertiesTest`, dedicated `ChatHistoryCompactionServiceTest` (trigger thresholds, idempotency, model override resolution, short-circuit when both backends off), parameterized integration coverage via Testcontainers for the Redis/Postgres replace-with-summary path.
- **Dependencies**: no new dependencies. The compaction model is invoked via the existing `ChatModelResolver` / Spring AI client beans.
- **Operational**: cost-wise compaction is a net win past ~20 turns even after paying for the cheap-model call. Latency-wise compaction is async and out of the user's turn — the only observable effect for callers is that long sessions stop ballooning input token counts. Operators get a new banner line `Compaction: [Enabled/Disabled] (trigger: <N> turns / <P>% context, keep: <K> turns, defaults: ...)` for visibility.

### Implementation deviations (vs. original proposal)

- **`@EnableAsync` was missing** from the codebase — `@Async` annotations (including the existing `persistToDb`) were silently no-ops, running synchronously. This change adds `@EnableAsync(proxyTargetClass = true)` on `AppConfig`. Side-effect: `PersistentChatMemory.persistToDb` becomes actually async. CGLIB proxies (`proxyTargetClass = true`) are required because `PersistentChatMemory` is injected as the concrete type by `ChatHistoryService` for the new 4-arg `add(...)` overload that's not on the `ChatMemory` interface.
- **No `replaceRangeWithSummary` repository default method**. The transactional Postgres write (delete prefix + insert summary) is performed by `ChatHistoryCompactionService` inside `TransactionTemplate.executeWithoutResult`. Cleaner than wiring `@Transactional` on a Spring Data interface default method.
- **`AiProviderProperties.ProviderConfig` has no `contextWindow` field**. The token-trigger calculation uses a hardcoded per-provider context-window map inside the compaction service (`anthropic=200k`, `openai=128k`, `gemini=1M`, `minimax=200k`, `lmstudio=8k`) with `8k` as the safe fallback for unknown providers. Adding a YAML field was deferred to keep the surface change minimal.
- **Effective Redis cap auto-bumps when compaction is enabled** to `max(maxSize, keepRecentTurns + 1)`. With the existing default `chat-history.max-size=5` and the new `keep-recent-turns=8`, a naive trim would drop the freshly-written summary on the next user turn. The new `effectiveCacheSize()` helper resolves this; `maxSize` semantics are unchanged when compaction is disabled.
- **REST shape is multipart `@RequestParam`, not JSON body**. The original design D7 sketched a JSON DTO; the actual `PromptController` is multipart, so the two new fields are `@RequestParam(required=false)`. Behavior is unchanged.
- **Migration**: pure additive. Default `enabled: true` is safe because the per-provider compaction model defaults are conservative (cheapest variant per provider) and the trigger fires only after a session has clearly outgrown raw retention.
