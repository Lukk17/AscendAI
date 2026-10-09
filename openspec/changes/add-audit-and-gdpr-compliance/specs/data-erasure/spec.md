## ADDED Requirements

### Requirement: Per-user erasure endpoint starts an asynchronous job

ascend-ai-agent SHALL expose `DELETE /api/v1/users/{userId}/data` which creates a persisted erasure job and returns HTTP 202 with the job id. The endpoint SHALL be callable by the authenticated user for their own `userId` (self-service) or by a tenant ADMIN for any user of the ADMIN's own tenant. Any other caller, including an ADMIN of another tenant, receives HTTP 403. Job state SHALL be persisted as a row of kind `ERASURE` in the one Postgres job table `data_job` (Flyway migration), which also holds export and tenant delete jobs, so that requests survive restarts and remain reportable after completion. The job SHALL run as one execution of the shared scheduler of `add-shared-scheduler`, so exactly one agent instance runs it while several instances serve the API, and a job whose instance stops SHALL be run again by another instance.

#### Scenario: Self-service erasure accepted

- **WHEN** the authenticated user `frosty` calls `DELETE /api/v1/users/frosty/data`
- **THEN** the response is HTTP 202 with a body containing a job id
- **AND** a `data_job` row of kind `ERASURE` exists with subject `frosty`, `requested_by = frosty`, and status `PENDING` or `RUNNING`

#### Scenario: A job whose instance stops is finished by another instance

- **WHEN** two agent instances run, an erasure job for `frosty` is running on the first, and the first instance stops before the job ends
- **THEN** the second instance runs the job again and it ends `COMPLETED` with zero residue, because every step is a delete-if-exists

#### Scenario: Cross-user erasure by non-admin refused

- **WHEN** authenticated user `frosty` (no ADMIN role) calls `DELETE /api/v1/users/otheruser/data`
- **THEN** the response is HTTP 403 and no erasure job is created

#### Scenario: ADMIN of another tenant refused

- **WHEN** an ADMIN of tenant `globex` calls `DELETE /api/v1/users/frosty/data` for `frosty` of tenant `acme`
- **THEN** the response is HTTP 403 and no erasure job is created

### Requirement: Erasure spans every data store holding subject data

An erasure job for user `{userId}` SHALL delete, recording a per-store outcome and deleted-item count: a) Postgres rows of the user's tenant in `chat_history` and the user's `conversations` rows, plus the store steps a later change registers in the shared store inventory (the `usage_ledger` rows of `add-usage-metering-and-quotas`); b) the Redis keys `chat:{tenantId}:{conversationId}` for each of the user's conversations, and the user's facts folder `<root>/tenants/<tenantId>/users/<userKey>/` of `add-agent-soul` with its history, which replaces the dropped `user_instructions` table and its Redis key; c) objects under `tenant/{tenantId}/` in the Floci `knowledge-base` bucket attributed to the user; d) the results of the user's OCR jobs in the ascend-ocr `ocr-results` bucket, found through the OCR jobs the agent recorded for the tenant; e) Qdrant points of the tenant attributed to the user in both `ascendai-768` and `ascendai-1536` collections; f) AscendMemory memories via `SemanticMemoryClient.wipeUserMemory` for every configured embedding provider, sent under the tenant-qualified id `{tenantId}:{userId}`; g) the user's Keycloak user record in realm `ascend-ai`, which SHALL be disabled and SHALL NOT be deleted: the job sets the account to disabled, ends its active sessions, and clears its personal attributes (first name, last name, email and every custom attribute except `tenant`), so the account can no longer sign in and holds no personal data. User attribution of object-store objects and Qdrant points follows the ownership metadata defined by `add-tenant-isolation`. Data of any other tenant SHALL be untouched. Each step SHALL be idempotent (delete-if-exists) so a job can be safely re-run.

#### Scenario: Zero residue after completed job

- **WHEN** an erasure job for user `frosty` completes with status `COMPLETED`
- **THEN** Postgres contains no `chat_history` or `conversations` rows for `frosty` in tenant `acme`
- **AND** Redis contains no `chat:acme:{conversationId}` key for `frosty`'s conversations
- **AND** the user facts folder of `frosty` under `tenants/acme/users/` no longer exists
- **AND** the Floci `knowledge-base` bucket contains no objects under `tenant/acme/` attributed to `frosty`
- **AND** the `ocr-results` bucket contains no result of an OCR job recorded for `frosty`
- **AND** neither `ascendai-768` nor `ascendai-1536` contains points attributed to `frosty`
- **AND** an AscendMemory search for `acme:frosty` returns no memories for any configured embedding provider
- **AND** `frosty` can no longer obtain a token from Keycloak
- **AND** the Keycloak account of `frosty` still exists, is disabled, and has no first name, last name or email

#### Scenario: Store failure yields PARTIAL, job re-runnable

- **WHEN** the Floci `knowledge-base` step fails during a job while the other stores succeed
- **THEN** the job ends with status `PARTIAL`, the `knowledge-base` step recorded as failed with a failure detail, the other steps recorded as succeeded
- **AND** re-running the job retries all steps without error on the already-erased stores

### Requirement: Erasure covers the stores of the agent changes

An erasure job SHALL also erase the stores the agent changes add, each through the erasure step this change writes on the layout its owning change defines (ruling 13.3 of the dependency fix of 2026-10-05), recorded as its own store step. Every owning change lands before this capability. For a user, the job SHALL delete: the user's `subagent_run` rows (`add-agent-subagents`); the user's `sandbox_workspace` rows and their output archives found through each row's `output_key`, after any open workspace of the user is destroyed (`add-agent-sandbox`); the user's `owner_notification` and `owner_notification_delivery` rows through `OwnerNotificationErasure` (`add-shared-scheduler`); the user's `approval_request` rows, setting `created_by` of the user's `approval_rule` rows to null (`add-action-approvals`); the user's `channel_link`, `channel_pairing` and `channel_outbox` rows, queuing one `purge` row per removed link so the host deletes OpenClaw's session data of those accounts (`add-openclaw-plugin-host`); the user's `coding_project` and `coding_run` rows, the `tenant/<tenantId>/coding/<runId>/` objects of the `coding-output` bucket and the project folders the user created, after stopping their runs (`add-coding-agent-delegation`); the user's `scheduled_job` rows with their firings and the matching `scheduler_execution` rows through `ScheduledJobErasure` (`add-scheduled-tasks`); the user's `self_review` rows, clearing the memory text and replacing the reason with a fixed erased text in the user's `self_change` rows (`add-self-improvement`); and SHALL set `created_by` of the user's integrations to null (`add-self-built-integrations`). A per user job SHALL delete no skill, no subagent definition, no download and no crawl result of `enhance-web-search-crawl-at-scale`, because those belong to the tenant and hold no user id.

#### Scenario: A user's agent data is erased and the tenant's shared data stays

- **WHEN** an erasure job for `frosty` of tenant `acme` completes with status `COMPLETED`
- **THEN** no `subagent_run`, `sandbox_workspace`, `approval_request`, `owner_notification`, `channel_link`, `channel_pairing`, `channel_outbox`, `coding_project`, `coding_run`, `scheduled_job` or `self_review` row of `frosty` remains
- **AND** `created_by` of every `approval_rule` row and every integration `frosty` created is null
- **AND** the skills and subagent definitions of tenant `acme` are unchanged

#### Scenario: Erased user has no notifications left

- **WHEN** user `u1` is erased
- **THEN** no notification or delivery row of `u1` from `add-shared-scheduler` remains, and another user's notifications stay

#### Scenario: User erasure of self-improvement records

- **WHEN** user `u1` is erased
- **THEN** no self-improvement review of `u1` remains and no change record of `u1` holds a memory text or the original reason

### Requirement: Tenant erasure and export cover the tenant's skills

The agent SHALL offer the tenant erasure job an operation that deletes the tenant skills folder `tenants/<tenantId>/skills/` under the writable root, git history included, removes the tenant folder `tenants/<tenantId>/` when nothing else is left in it, and deletes every capability index entry of that tenant, of every type (`skill`, `subagent`, `tool`), in every collection and for every provider, and reports how many skills it removed, without touching any other tenant's skills folder or index entries, any read-only folder, or any global index entry. It SHALL offer the tenant export job an operation that adds the tenant's skill folders at their newest commit and a git bundle of the tenant's repository to the export archive. Erasure of a single user SHALL delete no skill.

#### Scenario: Tenant erasure of skills

- **WHEN** the erasure job for tenant `acme` runs
- **THEN** `<writable root>/tenants/acme/skills` no longer exists
- **AND** the capability index holds no entry with tenant `acme`, of any type
- **AND** `<writable root>/tenants/globex/skills`, its index entries, every read-only folder and every global index entry are unchanged
- **AND** the job's per store counts include the number of skills removed

#### Scenario: Tenant export of skills

- **WHEN** the export job for tenant `acme` runs
- **THEN** the archive holds every `acme` skill folder as of its newest commit and a git bundle from which the full history of `acme` can be cloned

### Requirement: Erasure and export reach the user facts

The agent SHALL provide per user erasure that deletes the user's whole user facts folder of `add-agent-soul`, history included, and per tenant erasure that deletes the tenant's `soul/` and `users/` folders and then the tenant folder `tenants/<tenantId>/` only when nothing else is left in it. Neither SHALL delete or change the tenant's `skills/` or `.claude/agents/` folders, which their own erasure removes, and neither SHALL touch any other user's or tenant's repository or rewrite any history. Per user export SHALL provide the user's file at its newest commit. These SHALL be part of the tenant and user erasure and export jobs.

#### Scenario: Erasing one user's facts

- **WHEN** user erasure runs for `frosty` of tenant `default`
- **THEN** `frosty`'s folder no longer exists
- **AND** the personality repository and every other user's repository are unchanged

#### Scenario: Erasing a tenant leaves the other folders

- **WHEN** tenant erasure runs for tenant `acme` while `tenants/acme/skills/` still exists
- **THEN** `tenants/acme/soul/` and `tenants/acme/users/` no longer exist
- **AND** `tenants/acme/skills/` and the tenant folder `tenants/acme/` still exist

### Requirement: Integrations of add-self-built-integrations are erased and exported

Tenant erasure SHALL delete every integration of the tenant of `add-self-built-integrations` with its container, gateway, proxy, network, images, credential routes, tool reviews (rules of kind `integration_tool_review` in `approval_rule`), remembered egress rules and pending approvals, plus the whole integration repository of the tenant and its build reports. User export SHALL list the integrations the user's conversations built. Tenant export SHALL hold everything tenant erasure removes except what is built from the repository: every integration row of the tenant with its versions, destinations, credentials without any secret value and tool reviews (exported with the tenant's `approval_rule` rows), the integration repository folder as its files at the newest commit plus a `git bundle`, and every build report under `tenant/<tenantId>/integration-builds/`. Images and runner objects SHALL NOT be exported. User erasure SHALL set the creating user of those integrations to null.

#### Scenario: Tenant erasure of integrations

- **WHEN** tenant `a` is erased
- **THEN** its integration repository folder, integration rows, gateway credentials, images and runner objects are gone, and no other tenant's integration changed

#### Scenario: Tenant export matches tenant erasure for integrations

- **WHEN** tenant `a`, which has one integration with two versions and one build report, is exported
- **THEN** the export holds every integration row of `a`, the files and a `git bundle` of its integration repository and the build report
- **AND** it holds no secret value, no image and no runner object

### Requirement: Erasure never deletes a file in an Obsidian vault folder

An erasure job SHALL erase `obsidian_vault_file` rows together with their connector, and SHALL NEVER delete a file in a vault folder or its volume, because a deletion there is a deletion on every one of the owner's devices once the sync client runs.

#### Scenario: Tenant erasure leaves the vault files byte-identical

- **WHEN** a tenant erasure job runs for a tenant with an `OBSIDIAN` connector
- **THEN** the tenant's `obsidian_vault_file` rows, landed objects, chunks and registry rows are gone
- **AND** every file in the vault folder is byte-identical to what it was before the job

### Requirement: Erasure job status endpoint

ascend-ai-agent SHALL expose `GET /api/v1/users/{userId}/data/erasure/{jobId}` returning the job's status (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `PARTIAL`), per-store outcomes with deleted-item counts, and request/completion timestamps. Authorization matches the erasure endpoint (self or ADMIN).

#### Scenario: Status shows per-store counts

- **WHEN** the requester polls the status endpoint after the job finishes
- **THEN** the response is HTTP 200 listing each store step with its outcome and deleted-item count, plus `requested_at` and `completed_at`

### Requirement: Erasure completion is audited and audit rows are pseudonymized, not deleted

Each erasure job SHALL synchronously record `ERASURE_REQUESTED` on acceptance and `ERASURE_COMPLETED` on termination (carrying final status and per-store counts) through the audit-logging capability. Audit rows referencing the erased subject SHALL survive erasure with the subject pseudonymized: `actor` (and `resource_id` where it equals the subject id) is rewritten to `pseudo:` followed by the HMAC-SHA256 of the subject id keyed with a server-side pepper held only in configuration, truncated to 16 hex characters. The original subject id SHALL NOT remain anywhere in `audit_log` after job completion.

#### Scenario: Audit trail survives, subject unreadable

- **WHEN** an erasure job for `frosty` completes
- **THEN** `audit_log` still contains the rows previously recorded for `frosty`'s actions, with `actor` values of the form `pseudo:<16 hex chars>`
- **AND** the string `frosty` appears in no `audit_log` row
- **AND** an `ERASURE_COMPLETED` row exists whose `details` include the per-store deleted counts

### Requirement: Per-tenant erasure job

A tenant ADMIN SHALL be able to start an erasure job covering their own entire tenant via `DELETE /api/v1/admin/tenants/{tenantId}/data`, and an ADMIN whose tenant differs from `{tenantId}` SHALL receive HTTP 403, using the same job machinery, store coverage, status endpoint, and audit semantics as per-user erasure, with tenant attribution supplied by `add-tenant-isolation`. The tenant job additionally covers tenant-shared data that is not attributed to a single user: the `documents`, `document_index_state`, and `ingestion_runs` registry rows (owned by `add-document-management-api`) and the connector configuration, sync-run, delta-token and stored credential rows (owned by `add-connector-framework`) for the tenant, alongside every user's per-user data. It also covers the tenant data of the agent changes: the skills folder `tenants/<tenantId>/skills/` with its history and every capability index entry of the tenant (`SkillTenantStore.deleteTenant`, `add-agent-skills`); the definitions folder `tenants/<tenantId>/.claude/agents/` with its git repository, then `.claude/` when nothing else is left in it, and every `subagent_run` row of the tenant (`SubagentDefinitionStore.deleteTenant`, `add-agent-subagents`); the `soul/` and `users/` folders (`SoulTenantStore.deleteTenant`, `add-agent-soul`, whose personality proposals are `approval_request` rows of kind `personality_change`, erased with the approval tables); every `sandbox_workspace` row and every object under `tenant/<tenantId>/sandbox-output/` in the `sandbox-output` bucket (`add-agent-sandbox`); the tenant's notifications (`add-shared-scheduler`); both approval tables' rows (`add-action-approvals`); the `obsidian_vault_file` rows (`add-obsidian-vault`); every channel row of the tenant with every account purged (`add-openclaw-plugin-host`); every object under `tenant/{tenantId}/downloads/` and `tenant/{tenantId}/files/` in `web-hunter-downloads` and the Redis keys `download_index:{tenantId}`, `kept_index:{tenantId}` and `download_budget:{tenantId}:*`, through `DELETE /api/v2/web/downloads/{id}` and `DELETE /api/v2/web/downloads/kept/{id}` for each listed id (`add-file-download`); the crawl data of the tenant through one call to the erase endpoint `DELETE /api/v1/crawl/data` that this change adds to ascend-web-hunter with the header `X-Ascend-Tenant`, which cancels every `waiting` or `running` crawl job of the tenant and then deletes every object under `tenant/<tenantId>/` in the crawl results bucket `web-hunter-crawls`, the crawl progress, the recrawl state and the job records of the tenant, while the agent SHALL NOT read or delete an object in `web-hunter-crawls` with its own storage client (`enhance-web-search-crawl-at-scale`); every coding row, object and project folder and the folder `tenants/<tenantId>/` of the coding area (`add-coding-agent-delegation`); the tenant's scheduled jobs and their executions (`add-scheduled-tasks`); every `self_review`, `self_change`, `self_check_case` and `self_capability_use` row (`add-self-improvement`); and every integration with its runner objects, rows, repository folder and build reports, listing the variable names of the erased integrations in the job result (`add-self-built-integrations`). The tenant folder `tenants/<tenantId>/` SHALL be removed only when nothing else is left in it. Branches already pushed to GitHub are outside the system and are not touched.

#### Scenario: Tenant offboarding

- **WHEN** an ADMIN calls `DELETE /api/v1/admin/tenants/acme/data` and the job completes
- **THEN** no data attributed to tenant `acme` (any of its users or its shared resources) remains in any store step the job covers
- **AND** the job status endpoint reports per-store outcomes, and `ERASURE_REQUESTED` / `ERASURE_COMPLETED` audit rows exist

#### Scenario: Tenant erasure removes the crawl results of the tenant

- **WHEN** tenant `acme` has one running crawl job and one succeeded crawl job, tenant `globex` has one succeeded crawl job, and an ADMIN of `acme` runs tenant erasure for `acme` to `COMPLETED`
- **THEN** the running job of `acme` reads state `cancelled`
- **AND** `web-hunter-crawls` holds no object under `tenant/acme/`, and ascend-web-hunter holds no crawl job record, crawl progress or recrawl state of `acme`
- **AND** the agent made the deletion through `DELETE /api/v1/crawl/data` with `X-Ascend-Tenant: acme` and called no storage operation on `web-hunter-crawls` itself
- **AND** every object under `tenant/globex/` in `web-hunter-crawls` is unchanged

### Requirement: Tenant deletion is erase-then-deprovision

ascend-ai-agent SHALL expose `DELETE /api/v1/admin/tenants/{tenantId}` to `PLATFORM_ADMIN` only. Deleting a tenant SHALL proceed in order: suspend the tenant through the lifecycle service of `add-tenant-administration`, run the per-tenant erasure job to zero residue, disable the Keycloak users whose `tenant` attribute equals the tenant id and clear their personal attributes without deleting them, then remove the `tenants` row. If the erasure job ends `PARTIAL` or `FAILED`, the delete SHALL stop before removing users or the row and report the job id. Each step SHALL record an `ADMIN_OPERATION` audit row. User removal of `add-tenant-administration` SHALL offer to chain the per-user erasure job, and SHALL still disable the Keycloak account and never delete it.

#### Scenario: Delete erases before deprovisioning

- **WHEN** a `PLATFORM_ADMIN` deletes tenant `acme`
- **THEN** the tenant is suspended, its data is erased across all stores, its Keycloak users are disabled and not deleted, and the `tenants` row is deleted
- **AND** audit rows record the suspend, erasure, and deprovision steps

#### Scenario: Delete stops on incomplete erasure

- **WHEN** the erasure job for tenant `acme` ends with status `PARTIAL`
- **THEN** the Keycloak users and the `tenants` row of `acme` remain
- **AND** the response names the erasure job id

#### Scenario: Remove with data erasure

- **WHEN** a tenant `ADMIN` removes a user requesting data removal
- **THEN** the Keycloak account is disabled and still exists
- **AND** a per-user erasure job is started for that user

### Requirement: Erasure, export and retention are covered by end-to-end tests against the live stack

The ascend-ai-agent e2e suite SHALL check user erasure and user and tenant export against the live stack with deterministic Bruno tests and direct store queries, with no AI model. The specs SHALL seed every store a subject can hold data in, SHALL keep a control subject of another tenant, and SHALL assert per-store emptiness, archive content, Keycloak account state and audit rows, never a log line. Tenant erasure through `DELETE /api/v1/admin/tenants/{tenantId}/data` and the retention task SHALL be proved by their integration tests, and the same tenant erasure walk SHALL also run end to end inside the tenant delete of the company audit rows spec, because a separate e2e spec of them would only repeat those tests (owner answer 91.3 of 2026-10-08).

#### Scenario: User erasure leaves zero residue in the live stack

- **WHEN** the user erasure spec seeds `e2e-erasure-acme` and `e2e-erasure-globex` in every store and `e2e-erasure-acme` erases its own data
- **THEN** the job status reaches `COMPLETED` and every store holds nothing of `e2e-erasure-acme`
- **AND** every store of `e2e-erasure-globex` is unchanged, and the Keycloak account of `e2e-erasure-acme` is disabled, never deleted

#### Scenario: Export holds what erasure would remove

- **WHEN** the export spec exports the seeded subject and downloads the archive
- **THEN** the manifest lists every store of the shared store inventory
- **AND** the archive holds the canary document with bytes equal to the fixture

#### Scenario: Tenant delete runs the tenant erasure walk in the live stack

- **WHEN** the company audit rows spec deletes its suspended tenant as `PLATFORM_ADMIN`
- **THEN** the answer is 202 with a job id whose status reaches `COMPLETED`
- **AND** the tenant then answers 404 and its administrator's Keycloak account is disabled, never deleted
