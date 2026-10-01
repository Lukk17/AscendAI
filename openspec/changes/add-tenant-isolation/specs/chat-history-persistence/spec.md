## ADDED Requirements

### Requirement: Redis chat-history and instruction keys are tenant-scoped

`PersistentChatMemory` SHALL construct its Redis key as `chat:{tenantId}:{conversationId}` and `UserInstructionService` SHALL construct its key as `user:{tenantId}:{userId}:instructions`, where `{tenantId}` is resolved from the request's tenant context. Reads and writes without a resolved tenant context SHALL fail with an error rather than touching an unscoped key. The `{conversationId}` segment is the `conversations.id` that `add-chat-streaming-and-conversations` introduced, and the tenant segment SHALL sit immediately after the type prefix. A conversation SHALL only be loaded when its `conversations` row carries the caller's tenant.

#### Scenario: Two tenants with the same userId do not share history

- **WHEN** user `frosty` of tenant `acme` and user `frosty` of tenant `globex` each hold a conversation
- **THEN** `acme`'s messages are stored under `chat:acme:{conversationId}` and `globex`'s under `chat:globex:{conversationId}`
- **AND** a history load for one tenant never returns the other tenant's messages

#### Scenario: Instructions isolated per tenant

- **WHEN** user `frosty` of tenant `acme` saves user instructions
- **THEN** the value is written to `user:acme:frosty:instructions`
- **AND** a load for user `frosty` of tenant `globex` returns no instructions

#### Scenario: History access without tenant context fails closed

- **WHEN** chat history is read or written while no tenant is resolved
- **THEN** the operation throws an error
- **AND** no Redis key of the unscoped `chat:{conversationId}` form is created

### Requirement: Postgres chat history and instructions are tenant-scoped

The `conversations`, `chat_history` and `user_instructions` tables SHALL carry a `tenant_id VARCHAR(64) NOT NULL` column added via Liquibase. The `user_instructions` primary key SHALL become the composite `(tenant_id, user_id)`. `chat_history` SHALL be indexed on `(tenant_id, user_id)`, replacing the single-column `user_id` index. The nullable `conversations.tenant_id VARCHAR(255)` column that `add-chat-streaming-and-conversations` shipped SHALL be narrowed to `VARCHAR(64) NOT NULL`, matching `tenants.id`, with a foreign key to `tenants(id)` and an index on `(tenant_id, user_id)`. All repository reads and writes SHALL filter on tenant id as well as on user id or conversation id. A conversation id that exists under another tenant SHALL be answered as not found. Existing rows SHALL be backfilled to `tenant_id = 'default'` by the migration (see the `tenant-isolation` capability).

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
