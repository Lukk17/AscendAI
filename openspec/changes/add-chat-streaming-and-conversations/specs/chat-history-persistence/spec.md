# chat-history-persistence Delta Specification

## MODIFIED Requirements

### Requirement: Redis chat-history honors the configured TTL

`PersistentChatMemory` SHALL apply the configured `app.memory.chat-history.ttl` duration to every Redis key it writes,
so that chat history does not accumulate unbounded in Redis. Redis keys SHALL be per conversation - `chat:<conversationId>`
where `conversationId` is the conversation UUID from the `conversations` table (no longer the raw user id). The TTL
SHALL be refreshed on each write so an active conversation does not expire mid-session. Keys of the form
`chat:<userId>` written before the conversation model SHALL never be read, because no existing chat history is kept.

#### Scenario: TTL applied on first write

- **WHEN** `PersistentChatMemory.add(conversationId, message)` is called for a key `chat:<conversationId>` that does not yet exist
- **THEN** after the write, `redisTemplate.getExpire(key)` returns a value ≤ the configured TTL and > 0

#### Scenario: TTL refreshed on subsequent write

- **WHEN** a second message is added to the same conversation key shortly after the first
- **THEN** `getExpire(key)` is reset to (approximately) the configured TTL

#### Scenario: TTL configurable

- **WHEN** `app.memory.chat-history.ttl` is overridden to `1h`
- **THEN** new entries expire in approximately 1 hour, not 24 hours

#### Scenario: Old per-user key is never read

- **WHEN** a user with a `chat:<userId>` Redis key written before the conversation model (seeded by the test, not taken from a developer store) sends a prompt
- **THEN** the turn is cached under `chat:<conversationId>` for the resolved conversation
- **AND** the history sent to the model holds nothing from the `chat:<userId>` key
