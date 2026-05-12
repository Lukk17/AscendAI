## Why

Right now AscendAgent always writes turn-by-turn chat history to both Redis (hot cache, TTL'd) and Postgres (archive) via `PersistentChatMemory`. There's no way to opt out per backend. Two real scenarios this blocks: (1) privacy-sensitive deployments that want zero on-disk transcript retention and rely solely on Qdrant semantic memory for cross-turn continuity; (2) ephemeral dev/CI runs where the Postgres `chat_message` archive is dead weight. A pair of independent toggles lets operators run the agent in semantic-memory-only mode without code changes.

## What Changes

- Add `app.memory.chat-history.redis.enabled` (default `true`) — gates BOTH writes (`rightPush` + `expire`) AND reads (cache hit) on the Redis hot layer.
- Add `app.memory.chat-history.postgres.enabled` (default `true`) — gates BOTH the async DB persist call AND the cache-miss Postgres hydrate fallback.
- When both flags are `false`, `PersistentChatMemory.get(...)` returns an empty list and `add(...)` becomes a no-op. The agent still receives semantic memory items from AscendMemory (Qdrant) in the assembled system prompt, so cross-turn recall continues via that path.
- New `ChatHistoryProperties` `@ConfigurationProperties` class under `config/properties/` (mirrors the `IngestionUploadProperties` pattern landed in 511470e).
- Unit tests cover all four flag combinations on `PersistentChatMemoryExtraTest` plus a new test class if needed.
- `application.yaml` documents the trade-off inline.

No breaking changes: defaults preserve current behavior.

## Capabilities

### New Capabilities
- `chat-history-persistence-toggle`: independent enable/disable flags for each chat-history backend (Redis cache and Postgres archive), with documented behavior when both are off.

### Modified Capabilities
<!-- None — no existing OpenSpec specs in openspec/specs/ that describe the current chat-history persistence as a requirement. The behavior was implicit. -->

## Impact

- **Code**: `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/memory/PersistentChatMemory.java`, new `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/properties/ChatHistoryProperties.java`, `AscendAgent/src/main/resources/application.yaml`.
- **Tests**: `AscendAgent/src/test/java/com/lukk/ascend/ai/agent/memory/PersistentChatMemoryExtraTest.java` extended, possibly a new `ChatHistoryToggleTest`, plus a row in `PropertiesTest` for the new properties class.
- **APIs**: No HTTP surface change. Behavior change is internal to chat-history assembly.
- **Dependencies**: No new dependencies.
- **Operational**: Operators flipping both flags off run with reduced cross-turn coherence — the model sees only the current user message, the system prompt, and semantic-memory items. This is by design; document the trade-off in `application.yaml` and `docs/DEPLOYMENT.md`.
