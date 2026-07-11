## ADDED Requirements

### Requirement: Tenant entity and persistence

The agent SHALL persist tenants in a `tenants` table created via a Liquibase changelog in `AscendAgent/src/main/resources/db/changelog/`. Each tenant row SHALL have at minimum an `id` (the tenant identifier, primary key), a human-readable `display_name`, and a `created_at` timestamp. Tenant identifiers SHALL match `[a-z0-9-]{1,64}`; the agent SHALL reject any tenant id outside this format at the trust boundary so tenant ids are safe to embed verbatim in Redis keys, S3 key prefixes, Qdrant payload values, and composite AscendMemory user ids.

#### Scenario: Tenants table exists after migration

- **WHEN** AscendAgent boots against a fresh database
- **THEN** Liquibase creates the `tenants` table with `id`, `display_name`, and `created_at` columns
- **AND** the reserved `default` tenant row exists

#### Scenario: Malformed tenant id rejected

- **WHEN** a request arrives whose resolved tenant claim is `Acme Corp!` (uppercase, space, punctuation)
- **THEN** the request is rejected with a client error
- **AND** no tenant-scoped operation executes with that value

### Requirement: Tenant context resolved from the JWT tenant claim, fail-closed

The agent SHALL resolve the current tenant for every request from the JWT `tenant` claim delivered by the `add-auth-and-identity` change, exposed to services through a single request-scoped accessor. Every tenant-scoped operation (Qdrant search, MinIO upload/scan/presign, chat history read/write, user-instruction read/write, AscendMemory call) SHALL require a resolved tenant id. When no tenant is resolved, the operation SHALL fail with an error; it SHALL NOT fall back to an unfiltered query, a shared key, or the `default` tenant.

#### Scenario: Authenticated request carries tenant context

- **WHEN** a request authenticated with a JWT whose `tenant` claim is `acme` reaches `POST /api/v1/ai/prompt`
- **THEN** every downstream tenant-scoped operation for that request uses tenant id `acme`

#### Scenario: Missing tenant context fails closed

- **WHEN** a tenant-scoped service method is invoked while no tenant is resolved for the current request
- **THEN** the operation throws an error surfaced as HTTP 401/403 at the web layer
- **AND** no Qdrant, MinIO, Redis, Postgres, or AscendMemory access is performed for that operation

#### Scenario: Forged tenant form field has no effect

- **WHEN** a caller authenticated as tenant `acme` sends a request body or form field claiming tenant `globex`
- **THEN** all tenant-scoped operations still execute against `acme`
- **AND** no `globex` data is read or written

### Requirement: Default-tenant migration for existing deployments

The upgrade path SHALL map all pre-existing data to the reserved `default` tenant. The Liquibase changelog SHALL backfill `tenant_id = 'default'` on all existing `chat_history` and `user_instructions` rows before tightening the columns to `NOT NULL`. A one-shot, idempotent migration task SHALL stamp `tenant_id = 'default'` on all existing Qdrant points in both collections, create a keyword payload index on `tenant_id` per collection, and move existing MinIO objects from `markdown/` and `documents/` to `tenant/default/markdown/` and `tenant/default/documents/`.

#### Scenario: Postgres rows backfilled at boot

- **WHEN** the new changelog runs against a database containing pre-tenant `chat_history` rows
- **THEN** every existing row has `tenant_id = 'default'`
- **AND** the columns are `NOT NULL` afterwards

#### Scenario: Pre-existing documents retrievable by the default tenant after migration

- **WHEN** the one-shot migration task has completed and a user of tenant `default` sends a prompt matching a pre-migration document
- **THEN** RAG retrieval returns chunks from that document

#### Scenario: Migration task is idempotent

- **WHEN** the one-shot migration task is interrupted and re-run
- **THEN** already-stamped points and already-moved objects are skipped
- **AND** the end state is identical to a single uninterrupted run
