## ADDED Requirements

### Requirement: Redis chat-history keys are tenant-scoped

`PersistentChatMemory` SHALL construct its Redis key as `chat:{tenantId}:{conversationId}`, where `{tenantId}` is resolved from the request's tenant context. User instructions have no Redis key to scope, because `add-agent-soul` removes `UserInstructionService` and its key `user:{userId}:instructions` before this change. Reads and writes without a resolved tenant context SHALL fail with an error rather than touching an unscoped key. The `{conversationId}` segment is the `conversations.id` that `add-chat-streaming-and-conversations` introduced, and the tenant segment SHALL sit immediately after the type prefix. A conversation SHALL only be loaded when its `conversations` row carries the caller's tenant.

#### Scenario: Two tenants with the same userId do not share history

- **WHEN** user `frosty` of tenant `acme` and user `frosty` of tenant `globex` each hold a conversation
- **THEN** `acme`'s messages are stored under `chat:acme:{conversationId}` and `globex`'s under `chat:globex:{conversationId}`
- **AND** a history load for one tenant never returns the other tenant's messages

#### Scenario: History access without tenant context fails closed

- **WHEN** chat history is read or written while no tenant is resolved
- **THEN** the operation throws an error
- **AND** no Redis key of the unscoped `chat:{conversationId}` form is created

### Requirement: Postgres chat history is tenant-scoped

The `conversations` and `chat_history` tables SHALL carry a `tenant_id VARCHAR(64) NOT NULL` column. `chat_history`, which predates the tenant rule, SHALL get the column through this change's Flyway versioned SQL migration, with every existing row backfilled with `default`, and SHALL be indexed on `(tenant_id, user_id)`, replacing the single-column `user_id` index. `conversations.tenant_id VARCHAR(64) NOT NULL`, which `add-chat-streaming-and-conversations` already creates, SHALL get a foreign key to `tenants(id)` and an index on `(tenant_id, user_id)`. `user_instructions` is not changed, because `add-agent-soul` drops it. All repository reads and writes SHALL filter on tenant id as well as on user id or conversation id. A conversation id that exists under another tenant SHALL be answered as not found. After the migration the columns SHALL have no default, so every later insert names its tenant (see the `tenant-isolation` capability).

#### Scenario: History rows written with tenant id

- **WHEN** a user of tenant `acme` completes a chat turn with Postgres persistence enabled
- **THEN** the persisted `chat_history` rows have `tenant_id = 'acme'`

#### Scenario: Postgres hydration filters by tenant

- **WHEN** Redis is empty and history is hydrated from Postgres for user `frosty` of tenant `acme`
- **THEN** only rows with `tenant_id = 'acme'` and `user_id = 'frosty'` are loaded
- **AND** rows for user `frosty` of any other tenant are excluded

#### Scenario: A conversation of another tenant is not found

- **WHEN** a caller of tenant `globex` requests a conversation whose `conversations` row carries `tenant_id = 'acme'`
- **THEN** the response is 404
- **AND** no message of that conversation is returned and no Redis key under `chat:globex:` is created for it
