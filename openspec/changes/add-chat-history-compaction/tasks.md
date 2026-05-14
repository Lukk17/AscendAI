## 1. Configuration properties

- [ ] 1.1 Create `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/properties/ChatHistoryCompactionProperties.java` with `@ConfigurationProperties(prefix = "app.memory.chat-history.compaction")` and fields: `boolean enabled` (default `true`), `int turnTrigger` (default `20`), `double tokenTriggerFraction` (default `0.5`), `int keepRecentTurns` (default `8`), `int maxSummaryTokens` (default `800`), `Map<String, String> providerDefaults` (initialised with the five entries listed in design D3).
- [ ] 1.2 Add a `provider-defaults` block to `application.yaml` under `app.memory.chat-history.compaction.*` with the documented defaults (`openai → gpt-4o-mini`, `anthropic → claude-haiku-4-5`, `gemini → gemini-flash-lite-latest`, `minimax → ${MINIMAX_MODEL:MiniMax-M2.7}`, `lmstudio → ${LMSTUDIO_MODEL:meta-llama-3.1-8b-instruct}`). Include inline comments explaining the rationale for each choice.
- [ ] 1.3 Surface the same two env knobs in `docker-compose.yaml` and `.env.example` for parity with the existing chat-history toggles: `APP_MEMORY_CHATHISTORY_COMPACTION_ENABLED=${...:-true}` only — leave the per-provider model map as yaml-only since it is a Map and env-var binding for maps is awkward.
- [ ] 1.4 Add a `chatHistoryCompactionProperties_DefaultsAndSetters` row to `AscendAgent/src/test/java/com/lukk/ascend/ai/agent/config/properties/PropertiesTest.java` asserting every default and exercising every setter.

## 2. Compaction service

- [ ] 2.1 Create `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/memory/ChatHistoryCompactionService.java` with package-private `@Component` and `@Slf4j`. Constructor-inject `ChatHistoryCompactionProperties`, `ChatHistoryRepository`, `StringRedisTemplate`, `ObjectMapper`, `ChatHistoryProperties`, and the existing `ChatModelResolver` (or whatever bean today selects a provider's `ChatClient` — find it in `service/`).
- [ ] 2.2 Define a package-private record `CompactionOverride(String provider, String model)` used to thread per-request overrides from the controller through to the service.
- [ ] 2.3 Implement `void maybeCompact(String conversationId, String primaryProvider, CompactionOverride override)`:
    - Early-return when `!properties.isEnabled()`.
    - Early-return when both `chatHistoryProperties.getRedis().isEnabled()` and `chatHistoryProperties.getPostgres().isEnabled()` are false.
    - Load the full history (Postgres preferred, fall back to Redis if only Redis is enabled — reuse `PersistentChatMemory.get(...)` semantics via a package-private read-only method or a dedicated repository call).
    - Compute `triggered = (turns(history) >= turnTrigger) OR (estimateTokens(history) >= tokenTriggerFraction × contextWindow(primaryProvider))`.
    - If `!triggered`, return.
    - If the first message is already a `[Conversation summary]` SystemMessage AND `turns(history) - 1 < turnTrigger`, return (idempotency).
    - Compute `prefixCount = turns(history) - keepRecentTurns` (and clamp to ≥ 1 to avoid zero-work compaction).
    - Resolve `(compactionProvider, compactionModel)` per design D3, given `primaryProvider` and `override`.
    - Build the LLM prompt from the literal template constant in design D4. Include the prefix turns as the data to summarise.
    - Invoke the resolved chat client. Tag the call with a request-source attribute `"compaction"` if `StartupLogConfig` / observability cares (out of scope for this change but harmless to set).
    - Post-validate the output per the "Summary format and length cap" spec requirement (auto-prepend marker, reject oversize).
    - On success, call the new repository method `replacePrefixWithSummary(...)` (Postgres) and issue the Redis `LTRIM` / `LPUSH` / `EXPIRE` sequence (Redis) — each gated on the respective toggle.
    - Wrap everything in a `try`/`catch (Exception)` that logs at WARN with the conversation id and swallows.
- [ ] 2.4 Annotate `maybeCompact(...)` with `@Async` so it runs on the same executor that already serves `persistToDb`. Confirm `@EnableAsync` is already present somewhere in the config layer (it is — `persistToDb` is `@Async` today).
- [ ] 2.5 Add a private `int estimateTokens(List<Message> messages)` helper using the `(string-length / 4)` heuristic. Add a private `int contextWindow(String provider)` helper that resolves the provider's context window from `AiProviderProperties` (fall back to a sane default like `8192` for `lmstudio`-style locals when not explicitly configured — log at DEBUG on the fallback).
- [ ] 2.6 Add the literal prompt template as a `private static final String SUMMARISER_INSTRUCTION` constant near the top of the service, exactly matching the template in design D4.

## 3. Repository / model changes

- [ ] 3.1 Extend `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/repository/ChatHistoryRepository.java` with a transactional default method `replacePrefixWithSummary(String userId, String summaryContent, int prefixCount)` that:
    - Selects the IDs of the oldest `prefixCount` rows for that `userId` (ordered ascending by `created_at`).
    - Deletes those rows.
    - Inserts one new row with `role='system'`, `content=summaryContent`, `created_at=LocalDateTime.now()`.
    - Annotate the method `@Transactional` so the delete + insert are atomic per conversation.
- [ ] 3.2 Decide whether `ChatHistory.role='system'` alone is enough to distinguish a compaction summary from a regular system message, or whether to add a `boolean compacted` column. Recommend the former (no schema change) and rely on the `[Conversation summary]` content marker. Confirm in implementation; if the latter is chosen, add a Liquibase changelog under `db/changelog/`.

## 4. PersistentChatMemory integration

- [ ] 4.1 Inject `ChatHistoryCompactionService` and the inbound `CompactionOverride` (threaded via a `ThreadLocal` or, cleaner, by passing the override on `add(...)` and changing the call sites). Prefer the explicit parameter approach — `add(conversationId, messages, primaryProvider, override)` overload — to keep state out of `ThreadLocal`. Keep the old two-arg `add(...)` as a delegating overload that passes `null` provider / override for non-prompt callers.
- [ ] 4.2 At the tail of `add(...)`, after the existing Redis push and `persistToDb` calls, invoke `compactionService.maybeCompact(conversationId, primaryProvider, override)`. The call is `@Async` so it does not block. Skip the call entirely when both backends are disabled (which currently short-circuits earlier — confirm the gate location).
- [ ] 4.3 Update the read path `get(...)` to be aware that messages whose text begins with `[Conversation summary]` and whose `role` is `system` should still be returned as `SystemMessage` (they already are — assert via test).

## 5. REST DTO and controller

- [ ] 5.1 Locate the existing prompt request DTO (likely `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/dto/PromptRequest.java`; if it does not exist as a record / DTO, audit `PromptController` for the request signature). Add two optional fields `String compactionProvider`, `String compactionModel`. For a multipart form variant, declare them as `@RequestParam(required = false)`.
- [ ] 5.2 In `PromptController` (or the equivalent), build a `CompactionOverride` value object from the inbound fields and thread it into the existing chat-service call path so it ultimately reaches `PersistentChatMemory.add(...)`.
- [ ] 5.3 Validate `compactionProvider` at the boundary: if non-null and not a key in `AiProviderProperties.getProviders()`, return HTTP 400 with a message naming the offending field. Reuse the existing exception handler if one is in place; otherwise add a `MethodArgumentNotValidException` shape.

## 6. Startup banner

- [ ] 6.1 Inject `ChatHistoryCompactionProperties` into `StartupLogConfig` (constructor add).
- [ ] 6.2 Add a `formatCompactionState()` helper that emits either `[Disabled]` or `[Enabled] (trigger: X turns / Y% context, keep: Z turns, defaults: openai=..., anthropic=..., ...)` and wire it into the Infrastructure block of the banner directly under the `Chat History:` line.
- [ ] 6.3 Extend `AscendAgent/src/test/java/com/lukk/ascend/ai/agent/integration/StartupBannerIT.java` to assert the new `Chat History Compaction:` label.

## 7. Tests

- [ ] 7.1 Add `ChatHistoryCompactionServiceTest` covering:
    - Trigger fires on turn-count threshold.
    - Trigger fires on token-budget threshold even when turn-count is below the cap.
    - Idempotency: re-running on an already-summarised history with no new turns past the trigger is a no-op (no LLM call).
    - Idempotency: running on an already-summarised history WITH new turns past the trigger calls the LLM once and yields one merged summary.
    - Override resolution: all four cases from design D3 (no overrides, both overrides, provider-only, model-only).
    - Marker auto-prepend when the LLM output omits it.
    - Oversize rejection when the LLM output exceeds `1.5 × maxSummaryTokens`.
    - Compaction LLM exception is swallowed and logged at WARN; `maybeCompact(...)` returns normally.
    - Both backends disabled → no LLM call.
    - Redis-only and Postgres-only paths each touch only their backend.
- [ ] 7.2 Extend `PersistentChatMemoryExtraTest` with one test asserting `add(...)` invokes `compactionService.maybeCompact(...)` (via a verify-only mock) after the persistence side-effects and never before. Add a second test asserting that exception thrown by `maybeCompact(...)` does NOT propagate out of `add(...)`.
- [ ] 7.3 Add a Testcontainers IT (under `integration/`) that:
    - Seeds 25 raw turns into a fresh user.
    - Calls `PersistentChatMemory.add(...)` with one more turn.
    - Waits for the `@Async` compaction to complete (poll Postgres for the summary row up to 5 s).
    - Asserts Postgres contains exactly `1 + 8 = 9` rows for the user: one `role='system'` row whose content starts with `[Conversation summary]`, plus the 8 most-recent raw turns.
    - Asserts the Redis list contains the same 9 items in the same order.
- [ ] 7.4 Add a controller-level test in the existing prompt-controller test class confirming that an unknown `compactionProvider` value yields HTTP 400 and a clear error message.
- [ ] 7.5 `./gradlew test` — full unit suite green.
- [ ] 7.6 `./gradlew integrationTest` — full IT suite green.
- [ ] 7.7 `./gradlew jacocoTestReport` — `memory` package coverage stays ≥ the pre-change baseline.

## 8. Documentation

- [ ] 8.1 Update the `app.memory.chat-history` block comment in `application.yaml` to mention compaction and link operators to `app.memory.chat-history.compaction.*`.
- [ ] 8.2 Brief mention in `AscendAgent/AGENTS.md` "Code Conventions" or a new "Memory subsystem" subsection: chat history → toggle → compaction.
- [ ] 8.3 No new ADR required — `design.md` captures the rationale and the change is operator-facing only.

## 9. Verification (manual — user runs)

- [ ] 9.1 Smoke test: with defaults, run a 25-turn conversation against `provider=anthropic`. Confirm that turn 21 triggers compaction async; within 5 s after that turn, Postgres `chat_history` for the user has been replaced down to 9 rows (1 summary + 8 raw) and the summary row's content begins with `[Conversation summary]`.
- [ ] 9.2 Smoke test: same conversation length but pass `compactionProvider=openai`, `compactionModel=gpt-4o-mini`. Confirm via DEBUG logs that the OpenAI client (not Anthropic) was invoked for the compaction call.
- [ ] 9.3 Smoke test: set `app.memory.chat-history.compaction.enabled=false`. Run a 30-turn conversation; confirm no compaction fires (no summary row, history grows raw).
- [ ] 9.4 Smoke test: with both `redis.enabled=false` and `postgres.enabled=false`, send a 30-turn conversation; confirm no compaction LLM call is dispatched (logs are silent).
- [ ] 9.5 Restart and read the banner — confirm the new `Chat History Compaction:` line is present with the right values.

## 10. Rollback (documentation only)

- [ ] 10.1 Document in `design.md` (already present) the operator rollback: set `enabled: false`, redeploy. To purge written summaries, run `DELETE FROM chat_history WHERE content LIKE '[Conversation summary]%';`.
