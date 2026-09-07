## ADDED Requirements

### Requirement: Tenant entity and persistence

The agent SHALL persist tenants in a `tenants` table created via a Liquibase changelog in `apps/ascend-ai-agent/src/main/resources/db/changelog/`. Each tenant row SHALL have at minimum an `id` (the tenant identifier, primary key), a human-readable `display_name`, and a `created_at` timestamp. Tenant identifiers SHALL match `[a-z0-9-]{1,64}`; the agent SHALL reject any tenant id outside this format at the trust boundary so tenant ids are safe to embed verbatim in Redis keys, S3 key prefixes, Qdrant payload values, principal identifiers, and composite AscendMemory user ids.

#### Scenario: Tenants table exists after migration

- **WHEN** ascend-ai-agent boots against a fresh database
- **THEN** Liquibase creates the `tenants` table with `id`, `display_name`, and `created_at` columns
- **AND** the reserved `default` tenant row exists

#### Scenario: Malformed tenant id rejected

- **WHEN** a request arrives whose resolved tenant claim is `Acme Corp!` (uppercase, space, punctuation)
- **THEN** the request is rejected with a client error
- **AND** no tenant-scoped operation executes with that value

### Requirement: Isolation has two axes, tenant and access list

Isolation in this platform SHALL be enforced on two independent axes, and a chunk is readable only when both permit it.

The tenant axis answers which company owns a chunk and is carried by the `tenant_id` payload field. The access axis answers which people inside that company may read it and is carried by the `acl` payload field. Neither axis substitutes for the other: a caller of the owning tenant is not thereby entitled to every chunk of that tenant, and holding a principal that appears on a chunk of another tenant grants nothing. Every statement of isolation in this capability SHALL be read as covering both axes, and an enforcement point that applies only the tenant predicate SHALL be treated as incomplete rather than as partial progress.

#### Scenario: Both axes required for a read

- **WHEN** a chunk of tenant `acme` carries `acl` of `["local:group:finance"]`
- **THEN** a caller of tenant `globex` holding `local:group:finance` retrieves nothing from it
- **AND** a caller of tenant `acme` holding only `tenant:everyone:acme` retrieves nothing from it
- **AND** a caller of tenant `acme` holding `local:group:finance` retrieves it

### Requirement: Chunk access-list payload contract

Every chunk written to the vector store SHALL carry four access-list payload fields, declared as constants in `IngestionMetadataKeys` alongside `source`, `type`, `title`, and `tenant_id`:

| Field | Type | Meaning |
| :--- | :--- | :--- |
| `acl` | keyword array, indexed | The principals permitted to read this chunk. Empty means nobody. |
| `acl_source` | keyword | Which producer wrote the list: `sharepoint`, `google-drive`, `admin-assignment`, or `tenant-default`. |
| `acl_version` | keyword | A stable hash of the sorted `acl` list, used as the change-detection key. |
| `acl_synced_at` | integer, epoch seconds | When the list was last confirmed against its source. |

Principals SHALL use the `namespace:type:id` format owned by `add-auth-and-identity`, capped at 128 characters. A list SHALL carry at most 64 principals, and a producer that would exceed the cap SHALL fail that source loudly and SHALL NOT write a truncated list, because a truncated allow list denies access silently and the symptom is indistinguishable from a retrieval bug.

#### Scenario: Access-list fields present on every written chunk

- **WHEN** any ingestion producer writes a chunk for tenant `acme`
- **THEN** the resulting Qdrant point payload carries `acl`, `acl_source`, `acl_version`, and `acl_synced_at`
- **AND** `acl_version` equals the hash of the sorted `acl` list

#### Scenario: Over-cap access list fails the source

- **WHEN** a source's captured permission list contains 65 principals
- **THEN** ingestion of that source fails with a cap reason
- **AND** no chunk for that source is written with a truncated list

### Requirement: Tenant-everyone pseudo-group

The agent SHALL define a `tenant:everyone:{tenantId}` pseudo-group for every tenant. It SHALL be present in the principal set of every authenticated caller of that tenant, and it SHALL be writable onto a chunk's `acl` as an explicit, inspectable grant. It is the deliberate way to make a chunk readable by a whole tenant, and it is the floor a caller falls back to when every other source of principals has failed them. Tenant-wide readability SHALL only ever arise from this principal being present on the chunk, never from the absence of an access list.

#### Scenario: Tenant-wide chunk readable by any member of that tenant

- **WHEN** a chunk of tenant `acme` carries `acl` of `["tenant:everyone:acme"]`
- **THEN** any authenticated caller of tenant `acme` retrieves it, whatever other principals they hold
- **AND** no caller of any other tenant retrieves it

#### Scenario: Pseudo-group is tenant-specific

- **WHEN** a caller of tenant `globex` holds `tenant:everyone:globex`
- **THEN** that principal never matches a chunk carrying `tenant:everyone:acme`

### Requirement: Payload indexes on both filter fields

The migration SHALL create a keyword payload index on `tenant_id` and a keyword payload index on `acl` in every Qdrant collection the agent uses (`ascendai-768` and `ascendai-1536`). Both indexes are mandatory and SHALL be created in the same migration step, so a deployment cannot end up with one axis indexed and the other evaluated by walking the collection. A collection missing either index SHALL be reported by the migration task as an incomplete migration.

#### Scenario: Both indexes exist after migration

- **WHEN** the one-shot migration task completes against a collection
- **THEN** the collection reports a keyword payload index on `tenant_id`
- **AND** the collection reports a keyword payload index on `acl`

#### Scenario: Missing index is created and reported

- **WHEN** the migration task runs against a collection where only the `tenant_id` index exists
- **THEN** the task creates the `acl` index
- **AND** the task reports that collection as having been incomplete before the run

### Requirement: Tenant context and principal set resolved per request, fail-closed

The agent SHALL resolve, for every request, both the current tenant (from the JWT `tenant` claim) and the caller's principal set (resolved by `add-auth-and-identity` from the token's group claim or the provider's transitive membership endpoint), each exposed to services through a single request-scoped accessor. Every tenant-scoped operation (Qdrant search, MinIO upload/scan/presign, chat history read/write, user-instruction read/write, AscendMemory call) SHALL require a resolved tenant id, and every access-scoped operation (Qdrant search and source presigning) SHALL additionally require a resolved principal set.

When either is unresolved, the operation SHALL fail with an error. It SHALL NOT fall back to an unfiltered query, a query filtered on one axis only, a shared key, or the `default` tenant. An empty resolved principal set is distinct from an unresolved one: an empty set is a valid answer that legitimately matches nothing, while an unresolved set is a failure that SHALL throw.

#### Scenario: Authenticated request carries tenant context

- **WHEN** a request authenticated with a JWT whose `tenant` claim is `acme` reaches `POST /api/v1/ai/prompt`
- **THEN** every downstream tenant-scoped operation for that request uses tenant id `acme`

#### Scenario: Missing tenant context fails closed

- **WHEN** a tenant-scoped service method is invoked while no tenant is resolved for the current request
- **THEN** the operation throws an error surfaced as HTTP 401/403 at the web layer
- **AND** no Qdrant, MinIO, Redis, Postgres, or AscendMemory access is performed for that operation

#### Scenario: Missing principal set fails closed

- **WHEN** a similarity search or a source presign is attempted while the tenant is resolved but the caller's principal set is unresolved
- **THEN** the operation throws an error surfaced as HTTP 401/403 at the web layer
- **AND** no search is executed and no URL is signed
- **AND** the failure is not degraded into a search filtered by tenant alone

#### Scenario: Empty principal set is not a failure

- **WHEN** a caller's principal set resolves successfully to a set containing only `tenant:everyone:acme`
- **THEN** the search executes with that set
- **AND** it returns only chunks whose `acl` contains `tenant:everyone:acme`

#### Scenario: Forged tenant form field has no effect

- **WHEN** a caller authenticated as tenant `acme` sends a request body or form field claiming tenant `globex`
- **THEN** all tenant-scoped operations still execute against `acme`
- **AND** no `globex` data is read or written

#### Scenario: Forged principal has no effect

- **WHEN** a caller sends a request body, form field, or header naming a group principal it does not hold in its resolved set
- **THEN** the composed filter uses only the resolved principal set
- **AND** no chunk granted solely by the claimed principal is retrieved

### Requirement: Default-tenant migration for existing deployments

The upgrade path SHALL map all pre-existing data to the reserved `default` tenant and SHALL give it an explicit access list in the same step. The Liquibase changelog SHALL backfill `tenant_id = 'default'` on all existing `chat_history` and `user_instructions` rows before tightening the columns to `NOT NULL`.

A one-shot, idempotent migration task SHALL, for all existing points in both collections, stamp `tenant_id = 'default'`, stamp `acl = ["tenant:everyone:default"]` with `acl_source = 'tenant-default'`, a matching `acl_version`, and `acl_synced_at` set to the migration time. The explicit list is mandatory rather than optional: under deny-by-default a point stamped with a tenant and no access list is retrievable by nobody, so a tenant-only backfill would silently make every pre-existing document invisible. Stamping `tenant:everyone:default` reproduces the pre-change behaviour of a single-company deployment deliberately, as a grant visible in the payload, rather than by omission.

The same task SHALL create the keyword payload indexes on `tenant_id` and `acl`, and SHALL move existing MinIO objects from `markdown/` and `documents/` to `tenant/default/markdown/` and `tenant/default/documents/`.

#### Scenario: Postgres rows backfilled at boot

- **WHEN** the new changelog runs against a database containing pre-tenant `chat_history` rows
- **THEN** every existing row has `tenant_id = 'default'`
- **AND** the columns are `NOT NULL` afterwards

#### Scenario: Pre-existing points carry an explicit access list after migration

- **WHEN** the one-shot migration task has completed
- **THEN** every point that existed before the migration has `tenant_id = 'default'` and `acl` equal to `["tenant:everyone:default"]`
- **AND** no point exists carrying a `tenant_id` with an absent or empty `acl`

#### Scenario: Pre-existing documents retrievable by the default tenant after migration

- **WHEN** the one-shot migration task has completed and a user of tenant `default` holding `tenant:everyone:default` sends a prompt matching a pre-migration document
- **THEN** RAG retrieval returns chunks from that document
- **AND** the same retrieval run after the tenant stamp but before the access-list stamp returns nothing, which is why the two stamps are one step

#### Scenario: Migration task is idempotent

- **WHEN** the one-shot migration task is interrupted and re-run
- **THEN** already-stamped points and already-moved objects are skipped
- **AND** the end state is identical to a single uninterrupted run
