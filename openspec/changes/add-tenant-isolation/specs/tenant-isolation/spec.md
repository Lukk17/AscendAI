## ADDED Requirements

### Requirement: Tenant entity and persistence

The agent SHALL persist tenants in a `tenants` table created via a Flyway versioned SQL migration in `apps/ascend-agent/src/main/resources/db/migration/`. Each tenant row SHALL have at minimum an `id` (the tenant identifier, primary key), a human-readable `display_name`, and a `created_at` timestamp. Tenant identifiers SHALL match `[a-z0-9-]{1,64}`; the agent SHALL reject any tenant id outside this format at the trust boundary so tenant ids are safe to embed verbatim in Redis keys, S3 key prefixes, Qdrant payload values, principal identifiers, and composite AscendMemory user ids.

#### Scenario: Tenants table exists after migration

- **WHEN** ascend-ai-agent boots against a fresh database
- **THEN** Flyway creates the `tenants` table with `id`, `display_name`, and `created_at` columns
- **AND** the reserved `default` tenant row exists

#### Scenario: Malformed tenant id rejected

- **WHEN** a request arrives whose resolved tenant claim is `Acme Corp!` (uppercase, space, punctuation)
- **THEN** the request is rejected with HTTP 403 as `application/problem+json`
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

Principals SHALL use the `namespace:type:id` format owned by `add-auth-and-identity`, capped at 128 characters. A list SHALL carry at most the configured cap of principals (setting `app.ingestion.acl.max-principals`, environment variable `APP_INGESTION_ACL_MAXPRINCIPALS`, default 64), and a producer that would exceed the cap SHALL fail that source loudly and SHALL NOT write a truncated list, because a truncated allow list denies access silently and the symptom is indistinguishable from a retrieval bug.

#### Scenario: Access-list fields present on every written chunk

- **WHEN** any ingestion producer writes a chunk for tenant `acme`
- **THEN** the resulting Qdrant point payload carries `acl`, `acl_source`, `acl_version`, and `acl_synced_at`
- **AND** `acl_version` equals the hash of the sorted `acl` list

#### Scenario: Over-cap access list fails the source

- **WHEN** the cap is the default 64 and a source's captured permission list contains 65 principals
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

The agent SHALL ensure at startup a keyword payload index on `tenant_id` and a keyword payload index on `acl` in every Qdrant collection it uses (`ascendai-768` and `ascendai-1536`). Both indexes are mandatory and SHALL be created in the same startup step, so a deployment cannot end up with one axis indexed and the other evaluated by walking the collection. A missing index SHALL be created and logged at INFO, and the agent SHALL refuse to start when it cannot create one.

#### Scenario: Both indexes exist after startup

- **WHEN** the agent has started against a collection
- **THEN** the collection reports a keyword payload index on `tenant_id`
- **AND** the collection reports a keyword payload index on `acl`

#### Scenario: Missing index is created at startup

- **WHEN** the agent starts against a collection where only the `tenant_id` index exists
- **THEN** the agent creates the `acl` index
- **AND** one INFO line names the collection and the created index

### Requirement: Tenant context and principal set resolved per request, fail-closed

The agent SHALL resolve, for every request, both the current tenant (from the JWT `tenant` claim) and the caller's principal set (resolved by `add-auth-and-identity` from the token's Keycloak group claim), each exposed to services through a single request-scoped accessor. Every tenant-scoped operation (Qdrant search, the object store (Floci) upload/scan/presign, chat history read/write, AscendMemory call, and every read and write of the tables, folders and buckets this capability lists) SHALL require a resolved tenant id, and every access-scoped operation (Qdrant search and source presigning) SHALL additionally require a resolved principal set.

When either is unresolved, the operation SHALL fail with an error. It SHALL NOT fall back to an unfiltered query, a query filtered on one axis only, a shared key, or the `default` tenant. An empty resolved principal set is distinct from an unresolved one: an empty set is a valid answer that legitimately matches nothing, while an unresolved set is a failure that SHALL throw.

#### Scenario: Authenticated request carries tenant context

- **WHEN** a request authenticated with a JWT whose `tenant` claim is `acme` reaches `POST /api/v1/ai/prompt`
- **THEN** every downstream tenant-scoped operation for that request uses tenant id `acme`

#### Scenario: Missing tenant context fails closed

- **WHEN** a tenant-scoped service method is invoked while no tenant is resolved for the current request
- **THEN** the operation throws an error surfaced as HTTP 401 as `application/problem+json` at the web layer
- **AND** no Qdrant, the object store (Floci), Redis, Postgres, or AscendMemory access is performed for that operation

#### Scenario: Missing principal set fails closed

- **WHEN** a similarity search or a source presign is attempted while the tenant is resolved but the caller's principal set is unresolved
- **THEN** the operation throws an error surfaced as HTTP 403 as `application/problem+json` at the web layer
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

### Requirement: Documents registry and OCR results are tenant-scoped

The `documents` registry table that `add-document-management-api` introduced SHALL carry `tenant_id VARCHAR(64) NOT NULL` with a foreign key to `tenants(id)`, its `object_key` SHALL start with `tenant/{tenantId}/`, and every read, list, update and delete through the document management API SHALL filter on the caller's tenant. A document id that exists under another tenant SHALL be answered as not found. OCR results that ascend-ocr writes to its own `ocr-results` bucket SHALL be fetched by the agent only for jobs it submitted for the caller's tenant, and the agent SHALL record the tenant of every OCR job it submits so a result link is never handed to a caller of another tenant.

#### Scenario: Another tenant's document is not found

- **WHEN** a caller of tenant `globex` reads, deletes or re-indexes a document whose `documents` row carries `tenant_id = 'acme'`
- **THEN** the response is 404
- **AND** the row, its object and its Qdrant points are unchanged

#### Scenario: Document list is per tenant

- **WHEN** a caller of tenant `acme` lists documents
- **THEN** every returned row carries `tenant_id = 'acme'`

#### Scenario: An OCR result of another tenant is not handed out

- **WHEN** an OCR job was submitted by the agent for tenant `acme` and a caller of tenant `globex` asks for its result
- **THEN** the agent answers not found and issues no presigned link to the `ocr-results` object

### Requirement: Reserved default tenant, and isolation starts from empty stores

The Flyway migration SHALL create the reserved `default` tenant row. `chat_history`, the one tenant-owned table that predates the tenant rule, SHALL get its `tenant_id` column in the same migration with the column default `default` while the column is added, and the column SHALL keep no default afterwards. Rows of the earlier changes already carry `default` and SHALL NOT be changed. Tenant isolation SHALL start from empty stores (owner answer 88.1 of 2026-10-08, which supersedes answer 72.2 of 2026-10-06): the owner starts from clean stores after these changes are built, so the change SHALL have no backfill, no readiness hold and no data move, and SHALL NOT convert a Redis chat key, a Qdrant point, an object or an AscendMemory entry written before it. A record written before the change in the old shape is not supported: a Qdrant point without `tenant_id` and `acl` matches no search filter, so nobody retrieves it, and the presign guard refuses an object key outside `tenant/{tenantId}/`. The data that exists in the development stores today is disposable and out of scope (owner answer 73.1 of 2026-10-06): the change SHALL NOT depend on it.

The personal deployment SHALL run as tenant `default` through the same tenant resolution as any other tenant, never as a fallback when no tenant is resolved. Rows and folders that the changes landing before this one wrote with tenant `default` already belong to that tenant and are not changed.

#### Scenario: Insert without a tenant is refused

- **WHEN** the migration has run and a `chat_history` row is inserted without `tenant_id`
- **THEN** the insert is rejected by the `NOT NULL` constraint

#### Scenario: Existing chat history belongs to the default tenant

- **WHEN** the migration runs on a database that already holds `chat_history` rows of the personal deployment
- **THEN** every one of those rows reads `tenant_id = 'default'`

#### Scenario: The change starts from empty stores

- **WHEN** the agent starts with the change applied against an empty Redis, empty collections, empty buckets and empty AscendMemory collections
- **THEN** the agent reports ready once Flyway and the payload indexes are done, with no backfill step
- **AND** a document uploaded afterwards by a caller of tenant `default` is stored under `tenant/default/` and retrieved by that caller

#### Scenario: A point without a tenant is not retrieved

- **WHEN** a collection holds a point without `tenant_id` and `acl`, and a caller of tenant `default` holding `tenant:everyone:default` sends a prompt that matches it
- **THEN** RAG retrieval returns no chunk of that point

### Requirement: Tenant-scoped tables of the agent's own features

Every tenant-scoped table of the personal, base and web-hunter changes, which all land before this change, SHALL carry `tenant_id VARCHAR(64) NOT NULL` with a foreign key to `tenants(id)`, the foreign key added by this change's own Flyway migration with no backfill. The tables are, by name: `conversations`, `documents`, `document_index_state`, `ingestion_runs`, `owner_notification`, `owner_notification_delivery`, `subagent_run`, `sandbox_workspace`, `approval_rule`, `approval_request`, `connector`, `connector_credential`, `connector_sync_run`, `connector_sync_file_outcome`, `connector_sync_cursor`, `obsidian_vault_file`, `channel_link`, `channel_pairing`, `channel_conversation`, `channel_inbound_message`, `channel_outbox`, `coding_project`, `coding_run`, `scheduled_job`, `scheduled_job_firing`, `self_review`, `self_change`, `self_check_case`, `self_capability_use`, `integration`, `integration_version`, `integration_destination` and `integration_credential`. Among them are `owner_notification` (`add-shared-scheduler`), `subagent_run` (`add-agent-subagents`), `sandbox_workspace` (`add-agent-sandbox`), `approval_rule` and `approval_request` (`add-action-approvals`). Every repository query on them SHALL filter on the caller's tenant, and an id that exists under another tenant SHALL be answered as not found. `user_instructions` is not among the tenant-scoped tables, because `add-agent-soul` drops it.

#### Scenario: A row of another tenant is not found

- **WHEN** a caller of tenant `globex` reads a subagent run, an owner notification or an approval whose row carries `tenant_id = 'acme'`
- **THEN** the response is 404
- **AND** the row is unchanged

#### Scenario: An unknown tenant is refused by the foreign key

- **WHEN** a row is inserted into `subagent_run` with a `tenant_id` that has no `tenants` row
- **THEN** the insert is rejected by the foreign key

### Requirement: Tenant folders under the agent home and one tenant seam

Below the agent home root `app.agent-home`, each tenant's files SHALL live in its own folder `tenants/<tenantId>/`: skills written by the agent or by an owner in `skills/`, subagent definitions in `.claude/agents/`, the personality in `soul/` and each user's facts in `users/<userKey>/`, each its own git repository. Skills in the read-only folders SHALL stay global. Capability index entries SHALL carry the tenant id, every capability index search SHALL go through the one tenant-filtered search method `TenantFilteredVectorSearch.search` with no second call site, and a search SHALL never return an entry of another tenant. The tenant SHALL come from the one seam `TenantContext.currentTenantId()` of `add-keycloak-login`, which carries the tenant that the claim-reading implementation registered by `add-auth-and-identity` resolved, and which SHALL fail closed when no tenant is resolved, for skills, subagent definitions, personality and user facts reads and writes as for every other store. This change SHALL NOT add or change a tenant seam.

#### Scenario: A tenant's skill is invisible to another tenant

- **WHEN** a caller of tenant `acme` writes a skill
- **THEN** it is stored under `tenants/acme/skills/`
- **AND** a caller of tenant `globex` can neither read it nor find it through `skill_search`

#### Scenario: Personality and user facts fail closed

- **WHEN** a personality or user facts read is attempted while no tenant is resolved
- **THEN** the operation throws an error
- **AND** no file under `tenants/` is read or written

### Requirement: Other buckets keep the tenant prefix

The `sandbox-output` bucket of `add-agent-sandbox` SHALL keep every object under `tenant/<tenantId>/sandbox-output/`, and the agent SHALL refuse to read or hand out an object of that bucket outside the caller's tenant prefix.

#### Scenario: A sandbox archive of another tenant is not handed out

- **WHEN** a caller of tenant `globex` asks for a sandbox output archive stored under `tenant/acme/sandbox-output/`
- **THEN** the agent answers not found and issues no link to it

### Requirement: Worker threads bind the tenant first

Every background worker that acts for a tenant SHALL bind the tenant stored on its row with `TenantContext.runAs` of `add-keycloak-login` before any other step, clear it at the end, and fail closed when it cannot bind it. This covers the run threads of `add-agent-subagents`, which bind the caller's tenant, every scheduler thread of `add-shared-scheduler` that runs work of one tenant, and the workers of the stores listed below. A worker SHALL NOT fall back to the `default` tenant.

#### Scenario: A subagent run works in its caller's tenant

- **WHEN** a caller of tenant `acme` starts a background subagent run
- **THEN** every store access of that run uses tenant `acme`

#### Scenario: A worker that cannot bind its tenant does no work

- **WHEN** a scheduler execution for a tenant cannot bind that tenant's `TenantContext`
- **THEN** the execution performs no store access
- **AND** it does not run as tenant `default`

### Requirement: Stores of the other personal and web-hunter changes

The personal and web-hunter changes below land before this one and SHALL keep their stores under the rules of this capability from their first day, as tenant `default` until this change lands:

- `add-openclaw-plugin-host`: `channel_link`, `channel_pairing`, `channel_conversation`, `channel_inbound_message` and `channel_outbox` SHALL carry `tenant_id VARCHAR(64) NOT NULL` with the foreign key to `tenants(id)` added by this change's migration, and every query SHALL filter on it. An identity resolved from a chat platform link SHALL be held to the same fail-closed rule as a token identity, and a bot account with no configured tenant SHALL be refused.
- `add-file-download` and `add-download-ingestion`: the `web-hunter-downloads` bucket SHALL keep every object under `tenant/{tenantId}/downloads/` or `tenant/{tenantId}/files/`, the agent (`add-download-ingestion`) SHALL pass the caller's tenant to ascend-web-hunter, and a download id of another tenant SHALL be answered as not found.
- `enhance-web-search-crawl-at-scale`: the crawl results bucket `web-hunter-crawls` SHALL keep every object under `tenant/<tenantId>/`, followed by `CRAWL_RESULT_S3_PREFIX`, the job record, the frontier keys and the recrawl state SHALL carry the tenant, the agent SHALL pass the caller's tenant to ascend-web-hunter, and a crawl job of another tenant SHALL be answered as not found.
- `add-scheduled-tasks`: `scheduled_job.tenant_id` and `scheduled_job_firing.tenant_id` SHALL carry foreign keys to `tenants(id)`, added by this change's migration with no backfill, and the scheduler thread of a firing SHALL bind the job's tenant with `TenantContext.runAs` before any other step.
- `add-self-improvement`: `self_review`, `self_change`, `self_check_case` and `self_capability_use` SHALL carry `tenant_id` with the foreign key to `tenants(id)` added by this change's migration, `TenantContext.currentTenantId()` SHALL fail closed for them, and the scheduler threads of `self-review/<reviewId>` and `self-improvement-tenant-review/<tenantId>` SHALL bind the row's tenant before any other step.
- `add-coding-agent-delegation`: `coding_project` and `coding_run` SHALL carry `tenant_id VARCHAR(64) NOT NULL` with foreign keys to `tenants(id)` added by this change's migration, and every query SHALL filter on it. Project folders SHALL live only under `tenants/<tenantId>/projects/` of the coding project area, and run results only under the prefix `tenant/<tenantId>/coding/` of the `coding-output` bucket. A call with no resolved tenant SHALL be refused through `TenantContext.currentTenantId()`, and a coding run thread and each approval handler SHALL bind the row's tenant before any other step.
- `add-self-built-integrations`: every integration table SHALL carry `tenant_id VARCHAR(64) NOT NULL` with the foreign key to its parent integration added by that change's own migration and the foreign key to `tenants(id)` added by this change's migration, and every query SHALL filter on it. The source repository SHALL live only under `tenants/<tenantId>/integrations/`, build reports only under the prefix `tenant/<tenantId>/integration-builds/` of the `coding-output` bucket, and every runner object of an integration SHALL carry the tenant label. A call with no resolved tenant SHALL be refused through `TenantContext.currentTenantId()`, and the system task `integration-reconcile` SHALL bind the tenant of each integration row before any other step.

No personal, base or web-hunter change SHALL add a foreign key to `tenants(id)`. This change's own Flyway migration SHALL add the foreign key to `tenants(id)` on every tenant-scoped table that exists when it lands, listed by name in the requirement on the tables of the agent's own features.

#### Scenario: This change links the tables of the earlier changes

- **WHEN** this change's migration has run on a database where `add-scheduled-tasks` already created `scheduled_job` and `scheduled_job_firing`
- **THEN** both tables carry a foreign key from `tenant_id` to `tenants(id)`
- **AND** an insert into either with a `tenant_id` that has no `tenants` row is rejected

#### Scenario: A download of another tenant is not found

- **WHEN** a caller of tenant `globex` asks for a download id of tenant `acme`
- **THEN** the answer is not found

#### Scenario: A crawl job of another tenant is not found

- **WHEN** a caller of tenant `globex` asks for a crawl job of tenant `acme`
- **THEN** the answer is not found
- **AND** no object under `tenant/acme/` in `web-hunter-crawls` is read

#### Scenario: A coding run of another tenant is not found

- **WHEN** a caller of tenant `globex` asks for a coding run of tenant `acme`
- **THEN** the answer is not found
- **AND** no folder under `tenants/acme/projects/` and no object under `tenant/acme/coding/` is read

#### Scenario: Unknown tenant refused by the coding tables

- **WHEN** a `coding_project` row is inserted with a tenant id that has no row in `tenants`
- **THEN** the insert fails on the foreign key `coding_project_tenant_fk`

#### Scenario: Another tenant's coding result

- **WHEN** a caller of tenant `globex` reads the result of a coding run of tenant `acme`
- **THEN** the answer is 404 with an RFC 7807 problem body
- **AND** `coding_projects` of `globex` does not list the project of that run

#### Scenario: Pairing code from another tenant

- **WHEN** a user of tenant `globex` redeems a channel pairing code created for tenant `acme`
- **THEN** the response is 404 with `code` `channel_pairing_not_found` and no link is created

#### Scenario: Another tenant's scheduled job is hidden

- **WHEN** an `ADMIN` of tenant `globex` reads, changes or cancels a scheduled job of tenant `acme`
- **THEN** the response is 404 and the job is unchanged

#### Scenario: Another tenant's self-improvement changes are invisible

- **WHEN** an `ADMIN` of tenant `acme` lists self-improvement changes
- **THEN** no change of tenant `default` is in the list

#### Scenario: A bot account with no tenant is refused

- **WHEN** a message arrives for a bot account of `add-openclaw-plugin-host` with no configured tenant
- **THEN** the message is refused
- **AND** no tenant-scoped store is read or written for it

### Requirement: The capability index searches only through the tenant-filtered search method

`CapabilityIndex.search` of `add-agent-skills` SHALL search only through the one tenant-filtered search method, `TenantFilteredVectorSearch.search`, with the target `CAPABILITIES` and the type, provider and entry key filter as the narrowing conjunct, and SHALL hold no call of `VectorStore.similaritySearch` of its own. A refusal of that method because no tenant is resolved SHALL count as a failed query and SHALL never widen the search.

#### Scenario: The capability search uses the one tenant-filtered search method

- **WHEN** a request of tenant `globex` runs `skill_search`
- **THEN** the vector query is issued by `TenantFilteredVectorSearch.search` with the target `CAPABILITIES`, its filter joining `scope == 'global' OR tenant == 'globex'` with the type, provider and entry key filter
- **AND** no class of the capability index calls `VectorStore.similaritySearch`

### Requirement: Tenant isolation is covered by end-to-end tests across every store

The ascend-ai-agent e2e suite SHALL check both isolation axes against the live stack with the e2e users of two tenants, `e2e-acme` and `e2e-globex`, for every store a caller can reach: the object store, Qdrant, Redis chat history, Postgres chat history and conversations, AscendMemory, the documents registry, and the tenant stores of the agent changes. The OCR result refusal is proved by its integration test only (owner answer 91.3 of 2026-10-08). A check that HTTP status, response body or persisted state can show SHALL be a deterministic Bruno test with no chat model. A check whose request is a chat turn SHALL assert only `sources`, statuses and persisted state where the model's text is not the result under test.

#### Scenario: Two tenants upload the same file in the live stack

- **WHEN** the ingestion spec uploads one canary file as `e2e-acme` and as `e2e-globex`
- **THEN** the object store holds two objects under `tenant/e2e-acme/` and `tenant/e2e-globex/`
- **AND** every Qdrant point carries its own tenant and the five access-list fields

#### Scenario: Retrieval refuses both axes in the live stack

- **WHEN** the retrieval spec prompts with `attachSources=true` as a caller of the other tenant, and as a caller of the same tenant outside the chunk's access list
- **THEN** both receive no source and no presigned URL for the canary object
- **AND** a caller inside the access list receives the source with a URL that answers 200

#### Scenario: Agent stores answer not found across tenants

- **WHEN** an `e2e-globex` caller reads, renames or deletes a conversation, document, skill, subagent definition or personality of `e2e-acme`
- **THEN** each answer is 404 or the `e2e-globex` default
- **AND** the `e2e-acme` object is unchanged afterwards

#### Scenario: Chat history and memory keys carry the tenant

- **WHEN** the AI-run chat and memory spec sends one turn as `e2e-user-acme`
- **THEN** Redis holds `chat:e2e-acme:<conversationId>`, the `chat_history` rows carry `tenant_id` `e2e-acme`, and the AscendMemory points carry `user_id` `e2e-acme:<sub>`
