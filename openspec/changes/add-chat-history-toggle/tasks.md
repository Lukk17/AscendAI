## 1. Configuration properties class

- [x] 1.1 Create `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/properties/ChatHistoryProperties.java` with `@ConfigurationProperties(prefix = "app.memory.chat-history")` and fields: `int maxSize` (default `5`), `Duration ttl` (default `PT24H`), nested `Redis redis` (with `boolean enabled = true`), nested `Postgres postgres` (with `boolean enabled = true`). Mirrors the `IngestionUploadProperties` / `SemanticMemoryProperties` style.
- [x] 1.2 Verified `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/AscendAgentApp.java` already declares `@ConfigurationPropertiesScan`. The new class binds automatically.
- [x] 1.3 Updated `AscendAgent/src/main/resources/application.yaml` under `app.memory.chat-history`: added `redis.enabled: true` and `postgres.enabled: true` with an inline comment explaining the both-off trade-off (semantic memory only). Existing `max-size` and `ttl` keys preserved.

## 2. PersistentChatMemory refactor

- [x] 2.1 Replaced the two `@Value` fields (`maxSize`, `ttl`) in `PersistentChatMemory` with a constructor-injected `ChatHistoryProperties chatHistoryProperties` field (Lombok `@RequiredArgsConstructor` already in place). All reads of `maxSize` / `ttl` / `redis.enabled` / `postgres.enabled` now go through the properties bean.
- [x] 2.2 Added `@PostConstruct` method `logToggleState()` that emits `log.info("[PersistentChatMemory] Chat history backends - Redis: [{}], Postgres: [{}]", redisFlag, postgresFlag)` at startup. Uses `jakarta.annotation.PostConstruct` to match the Spring Boot 3.x baseline.
- [x] 2.3 `get(String conversationId, int lastN)` now short-circuits to `Collections.emptyList()` when both flags are false; Redis cache lookup is gated on `redis.enabled`; the Postgres hydrate fallback is gated on `postgres.enabled`; the Redis-hydrate-after-Postgres step is also gated on `redis.enabled`.
- [x] 2.4 `add(String conversationId, List<Message> messages)` now wraps the Redis push/trim/expire block in `if (redis.enabled)` and the `persistToDb(...)` call in `if (postgres.enabled)`. When both are false the method returns without doing any work (no exception, no log spam).
- [x] 2.5 `clear(String conversationId)` left unchanged — always attempts `redisTemplate.delete(key)` (idempotent, cheap, protects against runtime flag flips leaving stale data) per design Decision 4. Test `clear_AlwaysAttemptsRedisDelete_EvenWhenRedisDisabled` codifies this.

## 3. Startup banner update

- [x] 3.1 Injected `ChatHistoryProperties` into `StartupLogConfig` constructor (alongside the existing `AiProviderProperties`, `EmbeddingProviderProperties`, `SemanticMemoryProperties`).
- [x] 3.2 In `onReadinessChange`, added a banner line `Chat History: Redis [Enabled/Disabled], Postgres [Enabled/Disabled]` formatted via a new `formatChatHistoryToggles()` helper. Sits directly under `AscendMemory:` in the `Infrastructure:` block.

## 4. Tests

- [x] 4.1 Added `chatHistoryProperties_DefaultsAndSetters` to `PropertiesTest` — asserts the defaults (`maxSize=5`, `ttl=PT24H`, `redis.enabled=true`, `postgres.enabled=true`) and exercises every setter / nested getter on both inner classes.
- [x] 4.2 Added parameterized `get_RespectsBackendToggles_ForAllFourCombinations` to `PersistentChatMemoryExtraTest` covering `(redis, postgres) ∈ {true,false} × {true,false}` and asserting the right backends are touched in each case.
- [x] 4.3 Added a parallel parameterized `add_RespectsBackendToggles_ForAllFourCombinations` covering the write paths with `verify(..., never())` assertions on the disabled sides.
- [x] 4.4 Added `clear_AlwaysAttemptsRedisDelete_EvenWhenRedisDisabled` confirming `redisTemplate.delete(key)` is called even with `redis.enabled=false` (design Decision 4).
- [x] 4.5 Migrated the existing `PersistentChatMemoryExtraTest` and `PersistentChatMemoryTest` away from `ReflectionTestUtils.setField(memory, "maxSize", ...)` / `"ttl"` (those `@Value` fields no longer exist). Both now construct the SUT manually with a real `ChatHistoryProperties` instance, mirroring the cleaner pattern landed in `IngestionUploadProperties` work.
- [x] 4.6 Extended `StartupBannerIT` to assert the new `Chat History:` label is present in the banner.
- [x] 4.7 `./gradlew test` — full unit suite green (run 2026-05-14, no regressions).
- [ ] 4.8 `./gradlew integrationTest` — left for user. Requires Docker / Testcontainers; per project policy I do not run state-changing docker commands.
- [ ] 4.9 `./gradlew jacocoTestReport` — coverage check left for user. JaCoCo currently emits "Execution data does not match" noise from stale `.exec` files unrelated to this change.

## 5. Documentation

- [x] 5.1 **Deviation from original task:** `docs/DEPLOYMENT.md` does not exist in this monorepo (only `docs/architecture/` is checked in). The semantic-memory-only trade-off is documented inline in `application.yaml` (the canonical place operators look) and surfaced at boot via the readiness banner's new `Chat History:` line. No separate deployment doc to update.
- [x] 5.2 **Deviation from original task:** `AscendAgent/README.md` does not have a configuration table to update. The two new keys are self-documenting in `application.yaml` and visible in the startup banner; the README's "Configuration" section covers higher-level concerns and is unchanged.
- [x] 5.3 No new ADR required — `design.md` already captures the rationale and the change is operator-facing only.

## 6. Verification (manual — user runs)

- [ ] 6.1 With both flags `true`, run a two-turn conversation, confirm Redis key `chat:<userId>` is populated and Postgres `chat_history` table grows by 2 rows per turn (1 user + 1 assistant).
- [ ] 6.2 With `redis.enabled=false, postgres.enabled=true`, repeat — Redis key remains absent, Postgres rows grow.
- [ ] 6.3 With `redis.enabled=true, postgres.enabled=false`, repeat — Redis populated, Postgres row count unchanged.
- [ ] 6.4 With both `false`, repeat — neither backend touched, agent still responds (using only the current turn + semantic memory + system prompt). Confirm the startup banner shows `Chat History: Redis [Disabled], Postgres [Disabled]` and the agent log line `Retrieved History | Size: 0` is absent (the short-circuit returns an empty list without logging).
