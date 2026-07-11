# chat-history-persistence Delta Specification

## MODIFIED Requirements

### Requirement: Redis chat-history honors the configured TTL

`PersistentChatMemory` SHALL apply the configured `app.memory.chat-history.ttl` duration to every Redis key it writes,
so that chat history does not accumulate unbounded in Redis. Redis keys SHALL be per conversation — `chat:<conversationId>`
where `conversationId` is the conversation UUID from the `conversations` table (no longer the raw user id). The TTL
SHALL be refreshed on each write so an active conversation does not expire mid-session. Legacy `chat:<userId>` keys
written before the conversation model SHALL NOT be migrated or refreshed; they age out under their existing TTL while
reads under the new per-conversation key hydrate from Postgres.

#### Scenario: TTL applied on first write

- **WHEN** `PersistentChatMemory.add(conversationId, message)` is called for a key `chat:<conversationId>` that does not yet exist
- **THEN** after the write, `redisTemplate.getExpire(key)` returns a value ≤ the configured TTL and > 0

#### Scenario: TTL refreshed on subsequent write

- **WHEN** a second message is added to the same conversation key shortly after the first
- **THEN** `getExpire(key)` is reset to (approximately) the configured TTL

#### Scenario: TTL configurable

- **WHEN** `app.memory.chat-history.ttl` is overridden to `1h`
- **THEN** new entries expire in approximately 1 hour, not 24 hours

#### Scenario: Legacy per-user key is left to expire

- **WHEN** a user with a pre-migration `chat:<userId>` Redis key sends a prompt after the conversation model ships
- **THEN** the turn is cached under `chat:<conversationId>` for the resolved conversation
- **AND** the legacy `chat:<userId>` key is neither read, refreshed, nor deleted by the write path
