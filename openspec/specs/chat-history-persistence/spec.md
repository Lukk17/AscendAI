# chat-history-persistence Specification

## Purpose

Short-term chat history lives in Redis and has to stay bounded there. The configured `app.memory.chat-history.ttl` applies to every key `PersistentChatMemory` writes and is refreshed on each write, so an abandoned conversation ages out while an active one does not expire mid-session. The Postgres archive sits deliberately outside this TTL under a separate retention policy, and the configuration file is required to say so.

## Requirements
### Requirement: Redis chat-history honors the configured TTL

`PersistentChatMemory` SHALL apply the configured `app.memory.chat-history.ttl` duration to every Redis key it writes, so that user chat history does not accumulate unbounded in Redis. The TTL SHALL be refreshed on each write so an active conversation does not expire mid-session.

#### Scenario: TTL applied on first write

- **WHEN** `PersistentChatMemory.add(userId, message)` is called for a key that does not yet exist
- **THEN** after the write, `redisTemplate.getExpire(key)` returns a value ≤ the configured TTL and > 0

#### Scenario: TTL refreshed on subsequent write

- **WHEN** a second message is added to the same conversation key shortly after the first
- **THEN** `getExpire(key)` is reset to (approximately) the configured TTL

#### Scenario: TTL configurable

- **WHEN** `app.memory.chat-history.ttl` is overridden to `1h`
- **THEN** new entries expire in approximately 1 hour, not 24 hours

### Requirement: TTL configuration is documented

The `application.yaml` `app.memory.chat-history` section SHALL include a comment describing the TTL semantics and noting that Postgres long-term history is NOT pruned by this TTL (a separate retention policy applies).

#### Scenario: Comment present in application.yaml

- **WHEN** the file `AscendAgent/src/main/resources/application.yaml` is read
- **THEN** the `chat-history` block contains a comment that describes both the Redis TTL and that Postgres pruning is separate

