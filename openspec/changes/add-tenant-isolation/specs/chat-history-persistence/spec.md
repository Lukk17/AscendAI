## ADDED Requirements

### Requirement: Redis chat-history and instruction keys are tenant-scoped

`PersistentChatMemory` SHALL construct its Redis key as `chat:{tenantId}:{userId}` and `UserInstructionService` SHALL construct its key as `user:{tenantId}:{userId}:instructions`, where `{tenantId}` is resolved from the request's tenant context. Reads and writes without a resolved tenant context SHALL fail with an error rather than touching an unscoped key. The key layout SHALL keep the tenant segment immediately after the type prefix so the final segment can later become a `conversationId` without changing tenant scoping.

#### Scenario: Two tenants with the same userId do not share history

- **WHEN** user `frosty` of tenant `acme` and user `frosty` of tenant `globex` each hold a conversation
- **THEN** `acme`'s messages are stored under `chat:acme:frosty` and `globex`'s under `chat:globex:frosty`
- **AND** a history load for one tenant never returns the other tenant's messages

#### Scenario: Instructions isolated per tenant

- **WHEN** user `frosty` of tenant `acme` saves user instructions
- **THEN** the value is written to `user:acme:frosty:instructions`
- **AND** a load for user `frosty` of tenant `globex` returns no instructions

#### Scenario: History access without tenant context fails closed

- **WHEN** chat history is read or written while no tenant is resolved
- **THEN** the operation throws an error
- **AND** no Redis key of the legacy `chat:{userId}` form is created

### Requirement: Postgres chat history and instructions are tenant-scoped

The `chat_history` and `user_instructions` tables SHALL carry a `tenant_id VARCHAR(64) NOT NULL` column added via Liquibase. The `user_instructions` primary key SHALL become the composite `(tenant_id, user_id)`. `chat_history` SHALL be indexed on `(tenant_id, user_id)`, replacing the single-column `user_id` index. All repository reads and writes SHALL filter on both tenant id and user id. Existing rows SHALL be backfilled to `tenant_id = 'default'` by the migration (see the `tenant-isolation` capability).

#### Scenario: History rows written with tenant id

- **WHEN** a user of tenant `acme` completes a chat turn with Postgres persistence enabled
- **THEN** the persisted `chat_history` rows have `tenant_id = 'acme'`

#### Scenario: Postgres hydration filters by tenant

- **WHEN** Redis is empty and history is hydrated from Postgres for user `frosty` of tenant `acme`
- **THEN** only rows with `tenant_id = 'acme'` and `user_id = 'frosty'` are loaded
- **AND** rows for user `frosty` of any other tenant are excluded
