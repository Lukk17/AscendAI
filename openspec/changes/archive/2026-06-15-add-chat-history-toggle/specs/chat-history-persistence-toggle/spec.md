## ADDED Requirements

### Requirement: Independent chat-history backend toggles

The agent SHALL bind two independent configuration flags — `app.memory.chat-history.redis.enabled` and `app.memory.chat-history.postgres.enabled` — via a `@ConfigurationProperties` class named `ChatHistoryProperties` at prefix `app.memory.chat-history`. Both flags MUST default to `true` so that existing deployments observe unchanged behavior on upgrade.

#### Scenario: Defaults preserve current behavior
- **WHEN** the operator deploys the new build with no changes to `application.yaml`
- **THEN** `ChatHistoryProperties.getRedis().isEnabled()` returns `true`
- **AND** `ChatHistoryProperties.getPostgres().isEnabled()` returns `true`
- **AND** `PersistentChatMemory` writes to and reads from both backends exactly as before

#### Scenario: Operator can disable each backend independently
- **WHEN** the operator sets `app.memory.chat-history.redis.enabled=false` and leaves Postgres enabled
- **THEN** the agent skips all Redis interactions on `get`, `add`, and the cache-hydrate step after a Postgres read
- **AND** Postgres reads and writes continue to function normally

### Requirement: Read path honors both flags

`PersistentChatMemory.get(conversationId, lastN)` and `PersistentChatMemory.get(conversationId)` SHALL gate the Redis cache lookup on `redis.enabled` and the Postgres hydrate fallback on `postgres.enabled`. When both flags are `false`, both methods SHALL return `Collections.emptyList()` without contacting any backend.

#### Scenario: Redis disabled, Postgres enabled — reads from Postgres only
- **WHEN** a caller invokes `get("frosty", 10)`
- **AND** `redis.enabled=false`, `postgres.enabled=true`
- **THEN** `redisTemplate.opsForList().range(...)` is NOT called
- **AND** `ChatHistoryRepository.findRecentHistory(...)` IS called
- **AND** the returned list reflects Postgres content
- **AND** no Redis hydrate step is attempted

#### Scenario: Redis enabled, Postgres disabled — Redis-only with no archive fallback
- **WHEN** a caller invokes `get("frosty", 10)`
- **AND** `redis.enabled=true`, `postgres.enabled=false`
- **AND** the Redis list at key `chat:frosty` is empty
- **THEN** `ChatHistoryRepository.findRecentHistory(...)` is NOT called
- **AND** the returned list is empty

#### Scenario: Both disabled — empty list, no backend contact
- **WHEN** a caller invokes `get("frosty", 10)` or `get("frosty")`
- **AND** both `redis.enabled=false` and `postgres.enabled=false`
- **THEN** no Redis call is made
- **AND** no Postgres call is made
- **AND** the method returns `Collections.emptyList()`

### Requirement: Write path honors both flags

`PersistentChatMemory.add(conversationId, messages)` SHALL gate `redisTemplate.opsForList().rightPush(...)`, `trim(...)`, and `expire(...)` on `redis.enabled`, and gate the call to `persistToDb(...)` on `postgres.enabled`. When both flags are `false`, `add(...)` SHALL be a no-op (no exception thrown, no INFO log per call).

#### Scenario: Both disabled — add is a no-op
- **WHEN** a caller invokes `add("frosty", List.of(userMessage, assistantMessage))`
- **AND** both `redis.enabled=false` and `postgres.enabled=false`
- **THEN** `redisTemplate` is not invoked
- **AND** `repository.save(...)` is not invoked (directly or via `@Async persistToDb`)
- **AND** no exception is thrown

#### Scenario: Postgres disabled — Redis writes, no archive
- **WHEN** a caller invokes `add("frosty", List.of(msg))`
- **AND** `redis.enabled=true`, `postgres.enabled=false`
- **THEN** `redisTemplate.opsForList().rightPush(...)` is called once
- **AND** `redisTemplate.expire(...)` is called with the configured TTL
- **AND** `persistToDb(...)` is NOT called
- **AND** `repository.save(...)` is NOT called

### Requirement: Startup banner reports backend toggle state

The startup readiness banner emitted by `StartupLogConfig` SHALL include a line reporting which chat-history backends are enabled, so operators can verify their configuration without reading runtime DEBUG logs.

#### Scenario: Banner reports backend state
- **WHEN** the application boots with `redis.enabled=false`, `postgres.enabled=false`
- **THEN** the startup banner contains a line of the form `Chat History: Redis [Disabled], Postgres [Disabled]`
- **AND** the line appears alongside the other infrastructure status markers

### Requirement: Semantic memory is unaffected by chat-history flags

The agent's semantic memory pipeline (via `SemanticMemoryClient` → AscendMemory → Qdrant) SHALL function identically regardless of the chat-history toggle state. Memory retrieval and insertion in the system-prompt assembly path MUST NOT depend on `ChatHistoryProperties`.

#### Scenario: Semantic memory still injects facts when both chat-history flags are off
- **WHEN** a user with stored semantic memory items sends a prompt
- **AND** both `redis.enabled=false` and `postgres.enabled=false`
- **THEN** the assembled `SystemMessage` still includes the `User memory (may be relevant):` block with the user's facts
- **AND** the agent log line `Assembled SystemMessage ... SemanticMemory: YES (N items)` still appears
