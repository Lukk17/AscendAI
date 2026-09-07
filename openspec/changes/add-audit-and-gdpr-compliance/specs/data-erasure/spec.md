## ADDED Requirements

### Requirement: Per-user erasure endpoint starts an asynchronous job

ascend-ai-agent SHALL expose `DELETE /api/v1/users/{userId}/data` which creates a persisted erasure job and returns HTTP 202 with the job id. The endpoint SHALL be callable by the authenticated user for their own `userId` (self-service) or by an ADMIN for any user; any other caller receives HTTP 403. Job state SHALL be persisted in a Postgres `erasure_job` table (Liquibase changelog) so that requests survive restarts and remain reportable after completion.

#### Scenario: Self-service erasure accepted

- **WHEN** the authenticated user `frosty` calls `DELETE /api/v1/users/frosty/data`
- **THEN** the response is HTTP 202 with a body containing a job id
- **AND** an `erasure_job` row exists with subject `frosty`, `requested_by = frosty`, and status `PENDING` or `RUNNING`

#### Scenario: Cross-user erasure by non-admin refused

- **WHEN** authenticated user `frosty` (no ADMIN role) calls `DELETE /api/v1/users/otheruser/data`
- **THEN** the response is HTTP 403 and no erasure job is created

### Requirement: Erasure spans all five data stores

An erasure job for user `{userId}` SHALL delete, recording a per-store outcome and deleted-item count: a) Postgres rows in `chat_history`, `user_instructions`, the user's `conversations` rows (owned by `add-chat-streaming-and-conversations`), and the per-user usage rows owned by the `add-usage-metering-and-quotas` capability; b) Redis chat-history keys for the user's conversations (`chat:` prefix); c) MinIO objects in the `knowledge-base` bucket attributed to the user; d) Qdrant points attributed to the user in both `ascendai-768` and `ascendai-1536` collections; e) AscendMemory memories via `SemanticMemoryClient.wipeUserMemory` for every configured embedding provider. User attribution of MinIO objects and Qdrant points follows the ownership metadata defined by `add-tenant-isolation`. Each step SHALL be idempotent (delete-if-exists) so a job can be safely re-run.

#### Scenario: Zero residue after completed job

- **WHEN** an erasure job for user `frosty` completes with status `COMPLETED`
- **THEN** Postgres contains no `chat_history`, `user_instructions`, or usage rows for `frosty`
- **AND** Redis contains no `chat:` keys for `frosty`'s conversations
- **AND** the MinIO `knowledge-base` bucket contains no objects attributed to `frosty`
- **AND** neither `ascendai-768` nor `ascendai-1536` contains points attributed to `frosty`
- **AND** an AscendMemory search for `frosty` returns no memories for any configured embedding provider

#### Scenario: Store failure yields PARTIAL, job re-runnable

- **WHEN** the MinIO step fails during a job while the other stores succeed
- **THEN** the job ends with status `PARTIAL`, the MinIO step recorded as failed with a failure detail, the other steps recorded as succeeded
- **AND** re-running the job retries all steps without error on the already-erased stores

### Requirement: Erasure job status endpoint

ascend-ai-agent SHALL expose `GET /api/v1/users/{userId}/data/erasure/{jobId}` returning the job's status (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `PARTIAL`), per-store outcomes with deleted-item counts, and request/completion timestamps. Authorization matches the erasure endpoint (self or ADMIN).

#### Scenario: Status shows per-store counts

- **WHEN** the requester polls the status endpoint after the job finishes
- **THEN** the response is HTTP 200 listing each of the five stores with its outcome and deleted-item count, plus `requested_at` and `completed_at`

### Requirement: Erasure completion is audited and audit rows are pseudonymized, not deleted

Each erasure job SHALL synchronously record `ERASURE_REQUESTED` on acceptance and `ERASURE_COMPLETED` on termination (carrying final status and per-store counts) through the audit-logging capability. Audit rows referencing the erased subject SHALL survive erasure with the subject pseudonymized: `actor` (and `resource_id` where it equals the subject id) is rewritten to `pseudo:` followed by the HMAC-SHA256 of the subject id keyed with a server-side pepper held only in configuration, truncated to 16 hex characters. The original subject id SHALL NOT remain anywhere in `audit_log` after job completion.

#### Scenario: Audit trail survives, subject unreadable

- **WHEN** an erasure job for `frosty` completes
- **THEN** `audit_log` still contains the rows previously recorded for `frosty`'s actions, with `actor` values of the form `pseudo:<16 hex chars>`
- **AND** the string `frosty` appears in no `audit_log` row
- **AND** an `ERASURE_COMPLETED` row exists whose `details` include the per-store deleted counts

### Requirement: Per-tenant erasure job

An ADMIN SHALL be able to start an erasure job covering an entire tenant via `DELETE /api/v1/tenants/{tenantId}/data`, using the same job machinery, store coverage, status endpoint, and audit semantics as per-user erasure, with tenant attribution supplied by `add-tenant-isolation`. The tenant job additionally covers tenant-shared data that is not attributed to a single user: the `documents`, `document_index_state`, and `ingestion_runs` registry rows (owned by `add-document-management-api`) and the connector configuration, sync-run, and delta-token rows (owned by `add-document-connectors`) for the tenant, alongside every user's per-user data. Where a sibling change is not yet implemented, its tables are absent and that store step is a no-op; where it is present, the step SHALL cover it.

#### Scenario: Tenant offboarding

- **WHEN** an ADMIN calls `DELETE /api/v1/tenants/acme/data` and the job completes
- **THEN** no data attributed to tenant `acme` (any of its users or its shared resources) remains in any of the five stores
- **AND** the job status endpoint reports per-store outcomes, and `ERASURE_REQUESTED` / `ERASURE_COMPLETED` audit rows exist
