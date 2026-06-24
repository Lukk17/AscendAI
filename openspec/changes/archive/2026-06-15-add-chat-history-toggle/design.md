## Context

`PersistentChatMemory` is a dual-layer chat-history store: Redis (`opsForList().rightPush` + `expire`) acts as the hot cache for the last N turns; Postgres (`ChatHistoryRepository.save`, async) acts as the long-term archive. On a read, Redis is checked first; on miss, Postgres is queried via `findRecentHistory`, hydrated back into Redis with the configured `app.memory.chat-history.ttl`, and returned to the caller.

Today both layers are mandatory at compile time — there's no operator switch to run with neither, or with only one. Production scenarios that warrant a switch:

1. **Privacy-sensitive deployments.** Operators want the agent to retain no per-user transcript on disk. Semantic memory (Qdrant, via AscendMemory) abstracts facts (not raw messages) and is acceptable; raw turn-by-turn history is not.
2. **Ephemeral / CI runs.** Postgres archive growth is noise; Redis-only is faster and self-prunes via TTL.
3. **Diagnostic isolation.** Toggle the layers independently to attribute hot-cache vs. archive bugs.

Existing related work landed on this branch: `IngestionUploadProperties` (511470e) is the template for binding a YAML scalar/list/group to a `@ConfigurationProperties` class. `app.memory.chat-history.ttl` is already bound via `@Value` in `PersistentChatMemory`; consolidating to a properties class is a natural extension.

## Goals / Non-Goals

**Goals:**
- Independent on/off flags per backend (`redis.enabled`, `postgres.enabled`), both defaulting to `true` so current behavior is preserved.
- Each flag gates BOTH the write and the read code paths for its backend — half-gates (write-only / read-only) are out of scope and would create state divergence.
- When both flags are off, `get(...)` returns an empty `List<Message>` and `add(...)` is a no-op. The agent still sees semantic memory items (those come from `SemanticMemoryClient`, a separate path).
- One `ChatHistoryProperties` `@ConfigurationProperties` class binds all `app.memory.chat-history.*` keys (`maxSize`, `ttl`, `redis.enabled`, `postgres.enabled`). Replaces the three scattered `@Value` annotations in `PersistentChatMemory`.
- Unit tests cover all four flag combinations.

**Non-Goals:**
- Per-user or per-conversation toggling. Flags are global.
- Replacing the chat-history backends themselves (Redis or Postgres). Out of scope.
- Pruning Postgres archive at runtime. Separate concern.
- Migrating semantic memory wiring. Already covered by the `add-observability` and `add-prompt-caching` proposals.

## Decisions

**Decision 1 — One `@ConfigurationProperties` class vs. three `@Value` fields.**
Adopt `ChatHistoryProperties` at prefix `app.memory.chat-history`. Reasons: (a) the in-flight bug-fix work (`IngestionUploadProperties`, 511470e) already proved `@Value` + colon-default does not bind YAML lists reliably — even though this case is scalars, consistency across config classes is worth it; (b) one bean is easier to mock in tests than three `ReflectionTestUtils.setField` calls; (c) future flags (e.g. `app.memory.chat-history.compression.enabled`) fall in for free.

Alternative considered: keep `@Value` annotations and add two new ones. Rejected — repeats the same anti-pattern Bug-X+1 is fixing elsewhere.

**Decision 2 — Where to short-circuit in `get(...)`.**
At the top of the method, after computing `key`:
- If `redis.enabled` is false, skip the `redisTemplate.opsForList().range(...)` branch entirely.
- If `postgres.enabled` is false, skip the `repository.findRecentHistory(...)` branch and the subsequent Redis hydrate.
- If both are false, return `Collections.emptyList()` early — no log, no work.

Alternative considered: wrap each backend in a no-op `ChatMemoryBackend` interface, inject two implementations, switch at config time. Rejected — over-engineering for a two-flag scenario; the `if (props.getRedis().isEnabled())` guards are six lines total and unambiguous.

**Decision 3 — Where to short-circuit in `add(...)`.**
Same approach: guard `rightPush` + `expire` + `trim` with `redis.enabled`; guard the `persistToDb` call with `postgres.enabled`. When both are false, `add(...)` becomes a no-op (no exception, no log spam at INFO — DEBUG only).

**Decision 4 — Behavior on `clear(...)` when Redis is disabled.**
Always attempt `redisTemplate.delete(key)` — it's idempotent and cheap. Skipping it on `redis.enabled=false` could leave stale data if an operator flips the flag at runtime. Costs nothing to always try.

**Decision 5 — Logging level for the "both disabled" state.**
INFO once at startup via `@PostConstruct` on `PersistentChatMemory` so operators see the configuration plainly in the startup banner. After that, DEBUG only — INFO every turn would flood production logs.

## Risks / Trade-offs

- **[Risk] Operator flips both flags off and the model loses turn coherence within a single session.** → Mitigation: document the trade-off in `application.yaml` inline comment and `docs/DEPLOYMENT.md`. The startup banner's INFO line makes the configuration visible.
- **[Risk] Test combinatorics — four flag pairs × four operations (`get`/`add`/`clear`/`get(conversationId)`).** → Mitigation: parameterized JUnit test with a `@MethodSource` enumerating the matrix; reuse the existing `PersistentChatMemoryExtraTest` style.
- **[Trade-off] `add(...)` becomes effectively silent when both disabled.** Callers that depended on a `ServiceException` for a no-op write will see a no-op instead. → Mitigation: no callers rely on this semantically; `AscendChatService` calls `add(...)` fire-and-forget. Verified by grep.
- **[Risk] Stale data on flag flip from `true` → `false` at runtime.** → Mitigation: out of scope. Flag changes require app restart. Document.

## Migration Plan

Pure additive change with backward-compatible defaults. No migration step. Deploy the binary, optionally set the new yaml keys, restart.

Rollback: revert the deploy. Nothing to undo on Redis or Postgres state.
