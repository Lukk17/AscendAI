## 1. Configuration properties class

- [ ] 1.1 Create `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/properties/ChatHistoryProperties.java` with `@ConfigurationProperties(prefix = "app.memory.chat-history")` and fields: `int maxSize`, `Duration ttl = Duration.ofHours(24)`, nested `Redis redis` (with `boolean enabled = true`), nested `Postgres postgres` (with `boolean enabled = true`). Provide getters/setters; mirror the `IngestionUploadProperties` style.
- [ ] 1.2 Verify `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/AscendAgentApp.java` still has `@ConfigurationPropertiesScan` (yes — added in earlier bug-fix sprint). The new class binds automatically.
- [ ] 1.3 Update `AscendAgent/src/main/resources/application.yaml` under `app.memory.chat-history`: add `redis.enabled: true` and `postgres.enabled: true` with inline comments explaining the trade-off (both off = semantic memory only). Keep existing `max-size` and `ttl` keys.

## 2. PersistentChatMemory refactor

- [ ] 2.1 Replace the three `@Value` fields (`maxSize`, `ttl`) in `PersistentChatMemory` with a single constructor-injected `ChatHistoryProperties chatHistoryProperties` (Lombok `@RequiredArgsConstructor` already in place). Read `maxSize` / `ttl` / `redis.enabled` / `postgres.enabled` through the properties bean.
- [ ] 2.2 Add `@PostConstruct` method `logToggleState()` that emits `log.info("[PersistentChatMemory] Chat history backends - Redis: [{}], Postgres: [{}]", redisFlag, postgresFlag)` at startup.
- [ ] 2.3 Update `get(String conversationId, int lastN)`:
    - If both flags are false → return `Collections.emptyList()` immediately (no log, no work).
    - Guard the Redis cache lookup branch with `if (chatHistoryProperties.getRedis().isEnabled())`.
    - Guard the Postgres hydrate fallback with `if (chatHistoryProperties.getPostgres().isEnabled())`.
    - Guard the Redis-hydrate-after-Postgres step with both flags being true (no point hydrating Redis if it's disabled).
- [ ] 2.4 Update `add(String conversationId, List<Message> messages)`:
    - Wrap the `redisTemplate.opsForList().rightPush(...)` / `trim(...)` / `expire(...)` block in `if (chatHistoryProperties.getRedis().isEnabled())`.
    - Wrap the `persistToDb(...)` call in `if (chatHistoryProperties.getPostgres().isEnabled())`.
    - When both are false, the method returns without doing any work (no exception).
- [ ] 2.5 Leave `clear(String conversationId)` unchanged — it always attempts `redisTemplate.delete(key)` (idempotent, cheap, protects against runtime flag flips leaving stale data).

## 3. Startup banner update

- [ ] 3.1 Inject `ChatHistoryProperties` into `StartupLogConfig` (constructor add).
- [ ] 3.2 In `onReadinessChange`, add a banner line `Chat History: Redis [{}], Postgres [{}]` formatted as `[Enabled]` / `[Disabled]` matching the existing status-marker convention. Place it under the `Infrastructure:` block, after `AscendMemory`.

## 4. Tests

- [ ] 4.1 Add `chatHistoryProperties_DefaultsAndSetters` to `AscendAgent/src/test/java/com/lukk/ascend/ai/agent/config/properties/PropertiesTest.java` — assert defaults (`maxSize` default if any, `ttl=PT24H`, `redis.enabled=true`, `postgres.enabled=true`), exercise all setters and nested getters.
- [ ] 4.2 Extend `AscendAgent/src/test/java/com/lukk/ascend/ai/agent/memory/PersistentChatMemoryExtraTest.java` with a parameterized test method `get_RespectsBackendToggles_ForAllFourCombinations`:
    - `(redis=on, postgres=on)` → existing happy path still works.
    - `(redis=on, postgres=off)` → Postgres hydrate skipped, Redis-only path used.
    - `(redis=off, postgres=on)` → Redis call never made, Postgres read direct, no hydrate.
    - `(redis=off, postgres=off)` → `Collections.emptyList()` returned, neither backend touched (`verify(redisTemplate, never())`, `verify(repository, never())`).
- [ ] 4.3 Add a similar parameterized test `add_RespectsBackendToggles_ForAllFourCombinations` covering `add(...)` write paths, with `verify(redisTemplate.opsForList(), never()).rightPush(...)` and `verify(repository, never()).save(...)` on the "both off" row.
- [ ] 4.4 Add `clear_AlwaysAttemptsRedisDelete` confirming `redisTemplate.delete(key)` is called even when `redis.enabled=false` (per design Decision 4).
- [ ] 4.5 Update existing `PersistentChatMemoryExtraTest` tests that use `ReflectionTestUtils.setField(memory, "maxSize", ...)` / `"ttl"` to instead set the field on a real `ChatHistoryProperties` instance injected via `@Spy` (mirrors the `IngestionUploadProperties` test pattern from commit 511470e).
- [ ] 4.6 Update `IngestionEndToEndIT` / `BackingServicesIT` / `StartupBannerIT` only if they assert chat-history banner content (StartupBannerIT does — extend its banner-structure regex to accept the new `Chat History:` line).
- [ ] 4.7 Run `./gradlew test` — all unit tests green.
- [ ] 4.8 Run `./gradlew integrationTest` — all ITs green.
- [ ] 4.9 Run `./gradlew jacocoTestReport` — `memory` package coverage stays at 100% / 88% branch or better.

## 5. Documentation

- [ ] 5.1 Update `docs/DEPLOYMENT.md` with a short section "Chat history backends" describing the two flags, the four combinations, and the semantic-memory-only mode trade-off.
- [ ] 5.2 Update `AscendAgent/README.md` configuration table with the two new keys.
- [ ] 5.3 No new ADR required — design.md captures the rationale and the change is operator-facing only.

## 6. Verification

- [ ] 6.1 Smoke test: with both flags `true`, run a two-turn conversation, confirm Redis key `chat:<userId>` is populated and Postgres `chat_history` table grows by 2 rows per turn (1 user + 1 assistant).
- [ ] 6.2 Smoke test: with `redis.enabled=false, postgres.enabled=true`, repeat — Redis key remains absent, Postgres rows grow.
- [ ] 6.3 Smoke test: with `redis.enabled=true, postgres.enabled=false`, repeat — Redis populated, Postgres row count unchanged.
- [ ] 6.4 Smoke test: with both `false`, repeat — neither backend touched, agent still responds (using only the current turn + semantic memory + system prompt). Confirm agent log shows `Retrieved History | Size: 0` (or a new dedicated log line for the all-off path).
