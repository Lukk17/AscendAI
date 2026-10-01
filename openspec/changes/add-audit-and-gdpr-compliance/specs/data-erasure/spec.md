## ADDED Requirements

### Requirement: Per-user erasure endpoint starts an asynchronous job

ascend-ai-agent SHALL expose `DELETE /api/v1/users/{userId}/data` which creates a persisted erasure job and returns HTTP 202 with the job id. The endpoint SHALL be callable by the authenticated user for their own `userId` (self-service) or by a tenant ADMIN for any user of the ADMIN's own tenant. Any other caller, including an ADMIN of another tenant, receives HTTP 403. Job state SHALL be persisted in a Postgres `erasure_job` table (Liquibase changelog) so that requests survive restarts and remain reportable after completion.

#### Scenario: Self-service erasure accepted

- **WHEN** the authenticated user `frosty` calls `DELETE /api/v1/users/frosty/data`
- **THEN** the response is HTTP 202 with a body containing a job id
- **AND** an `erasure_job` row exists with subject `frosty`, `requested_by = frosty`, and status `PENDING` or `RUNNING`

#### Scenario: Cross-user erasure by non-admin refused

- **WHEN** authenticated user `frosty` (no ADMIN role) calls `DELETE /api/v1/users/otheruser/data`
- **THEN** the response is HTTP 403 and no erasure job is created

#### Scenario: ADMIN of another tenant refused

- **WHEN** an ADMIN of tenant `globex` calls `DELETE /api/v1/users/frosty/data` for `frosty` of tenant `acme`
- **THEN** the response is HTTP 403 and no erasure job is created

### Requirement: Erasure spans every data store holding subject data

An erasure job for user `{userId}` SHALL delete, recording a per-store outcome and deleted-item count: a) Postgres rows of the user's tenant in `chat_history`, `user_instructions`, the user's `conversations` rows, and the user's `usage_ledger` rows owned by the `add-usage-metering-and-quotas` capability; b) the Redis keys `chat:{tenantId}:{conversationId}` for each of the user's conversations and `user:{tenantId}:{userId}:instructions`; c) objects under `tenant/{tenantId}/` in the Floci `knowledge-base` bucket attributed to the user; d) the results of the user's OCR jobs in the ascend-ocr `ocr-results` bucket, found through the OCR jobs the agent recorded for the tenant; e) Qdrant points of the tenant attributed to the user in both `ascendai-768` and `ascendai-1536` collections; f) AscendMemory memories via `SemanticMemoryClient.wipeUserMemory` for every configured embedding provider, sent under the tenant-qualified id `{tenantId}:{userId}`; g) the user's Keycloak user record in realm `ascend-ai`, so that the account can no longer sign in and its personal attributes are removed (whether this deletes or disables the account is an owner decision not taken yet). User attribution of object-store objects and Qdrant points follows the ownership metadata defined by `add-tenant-isolation`. Data of any other tenant SHALL be untouched. Each step SHALL be idempotent (delete-if-exists) so a job can be safely re-run.

#### Scenario: Zero residue after completed job

- **WHEN** an erasure job for user `frosty` completes with status `COMPLETED`
- **THEN** Postgres contains no `chat_history`, `conversations`, `user_instructions`, or `usage_ledger` rows for `frosty` in tenant `acme`
- **AND** Redis contains no `chat:acme:{conversationId}` key for `frosty`'s conversations and no `user:acme:frosty:instructions` key
- **AND** the Floci `knowledge-base` bucket contains no objects under `tenant/acme/` attributed to `frosty`
- **AND** the `ocr-results` bucket contains no result of an OCR job recorded for `frosty`
- **AND** neither `ascendai-768` nor `ascendai-1536` contains points attributed to `frosty`
- **AND** an AscendMemory search for `acme:frosty` returns no memories for any configured embedding provider
- **AND** `frosty` can no longer obtain a token from Keycloak

#### Scenario: Store failure yields PARTIAL, job re-runnable

- **WHEN** the Floci `knowledge-base` step fails during a job while the other stores succeed
- **THEN** the job ends with status `PARTIAL`, the `knowledge-base` step recorded as failed with a failure detail, the other steps recorded as succeeded
- **AND** re-running the job retries all steps without error on the already-erased stores

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

A tenant ADMIN SHALL be able to start an erasure job covering their own entire tenant via `DELETE /api/v1/tenants/{tenantId}/data`, and an ADMIN whose tenant differs from `{tenantId}` SHALL receive HTTP 403, using the same job machinery, store coverage, status endpoint, and audit semantics as per-user erasure, with tenant attribution supplied by `add-tenant-isolation`. The tenant job additionally covers tenant-shared data that is not attributed to a single user: the `documents`, `document_index_state`, and `ingestion_runs` registry rows (owned by `add-document-management-api`) and the connector configuration, sync-run, and delta-token rows (owned by `add-document-connectors`) for the tenant, alongside every user's per-user data. Where a sibling change is not yet implemented, its tables are absent and that store step is a no-op; where it is present, the step SHALL cover it.

#### Scenario: Tenant offboarding

- **WHEN** an ADMIN calls `DELETE /api/v1/tenants/acme/data` and the job completes
- **THEN** no data attributed to tenant `acme` (any of its users or its shared resources) remains in any store step the job covers
- **AND** the job status endpoint reports per-store outcomes, and `ERASURE_REQUESTED` / `ERASURE_COMPLETED` audit rows exist
