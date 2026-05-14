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

- **Code (new)**:
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/properties/ChatHistoryCompactionProperties.java`
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/memory/ChatHistoryCompactionService.java`
- **Code (modified)**:
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/memory/PersistentChatMemory.java` — inject the compaction service, call `compactionService.maybeCompact(conversationId, provider, model)` after the persistence side-effects in `add(...)`. Add an idempotency helper that recognises the `[Conversation summary]` marker so the read path can render summaries cleanly.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/repository/ChatHistoryRepository.java` + `model/ChatHistory.java` — a new repo method `replaceRangeWithSummary(userId, deleteBeforeId, summaryText)` plus an entity flag (or role marker) so the summary survives a Redis flush.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/dto/PromptRequest.java` (or wherever the inbound prompt DTO lives) — two new optional fields `compactionProvider` and `compactionModel`.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/controller/PromptController.java` and the service that hands a `PromptContext` down — propagate the overrides into `ChatHistoryCompactionService`.
  - `AscendAgent/src/main/resources/application.yaml` — new `app.memory.chat-history.compaction` block with the documented defaults.
- **APIs**: `/api/v1/ai/prompt` gains two backward-compatible optional fields. Existing callers see no behaviour change.
- **Tests**: `ChatHistoryCompactionPropertiesTest` row in `PropertiesTest`, dedicated `ChatHistoryCompactionServiceTest` (trigger thresholds, idempotency, model override resolution, short-circuit when both backends off), parameterized integration coverage via Testcontainers for the Redis/Postgres replace-with-summary path.
- **Dependencies**: no new dependencies. The compaction model is invoked via the existing `ChatModelResolver` / Spring AI client beans.
- **Operational**: cost-wise compaction is a net win past ~20 turns even after paying for the cheap-model call. Latency-wise compaction is async and out of the user's turn — the only observable effect for callers is that long sessions stop ballooning input token counts. Operators get a new banner line `Chat History Compaction: [Enabled/Disabled] (trigger: <N> turns / <P>% context)` for visibility.
- **Migration**: pure additive. Default `enabled: true` is safe because the per-provider compaction model defaults are conservative (cheapest variant per provider) and the trigger fires only after a session has clearly outgrown raw retention.
