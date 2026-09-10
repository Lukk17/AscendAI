## ADDED Requirements

### Requirement: Append-only audit_log table records security-relevant events

ascend-ai-agent SHALL persist audit events to a Postgres table `audit_log` created via a Liquibase changelog, with columns for `occurred_at` (TIMESTAMPTZ), `actor`, `tenant` (nullable), `action`, `resource_type` (nullable), `resource_id` (nullable), `outcome`, `source_ip` (nullable), and a JSONB `details` payload. The table SHALL be append-only: a database-level trigger SHALL reject `UPDATE` and `DELETE` statements, except deletes issued through the retention job's sanctioned path and the pseudonymization rewrite performed by an erasure job.

#### Scenario: Ad-hoc mutation rejected by the database

- **WHEN** an `UPDATE audit_log SET outcome = 'OK'` or a plain `DELETE FROM audit_log` is executed against the database
- **THEN** the statement fails with a database error raised by the append-only trigger
- **AND** the targeted rows are unchanged

#### Scenario: Retention path can delete expired rows

- **WHEN** the retention job deletes audit rows older than the configured retention window through its sanctioned path
- **THEN** the delete succeeds and only rows older than the boundary are removed

### Requirement: Audit events cover the security-relevant action set

The system SHALL record an audit event for each of the following actions, using a closed action vocabulary: `AUTH_TOKEN_REJECTED` (a request bearing an invalid or expired token is rejected at the resource server), `CHAT_PROMPT` (a prompt request is accepted for processing), `DOCUMENT_UPLOADED`, `DOCUMENT_DELETED`, `DOCUMENT_PRESIGN_ISSUED` (a presigned download URL is handed to a caller), `INGESTION_RUN`, `MEMORY_WIPED`, `ERASURE_REQUESTED`, `ERASURE_COMPLETED`, `ADMIN_OPERATION`, and `QUOTA_REJECTED`. Each event SHALL carry the authenticated actor, the tenant when known, the outcome, and the caller's source IP when available. The `QUOTA_REJECTED` event is emitted from the quota-enforcement path owned by the `add-usage-metering-and-quotas` change through this capability's recorder.

#### Scenario: Chat request produces an audit row

- **WHEN** `POST /api/v1/ai/prompt` is processed for an authenticated user
- **THEN** exactly one `audit_log` row with `action = 'CHAT_PROMPT'` exists for that request, with `actor` equal to the authenticated user's identity and `outcome` reflecting success or failure

#### Scenario: Presigned URL issuance is audited

- **WHEN** a prompt with `attachSources=true` causes presigned MinIO download URLs to be generated
- **THEN** an audit row with `action = 'DOCUMENT_PRESIGN_ISSUED'` records the actor and the object keys (as `resource_id` / `details`), one row per issuance batch

#### Scenario: Rejected token is audited

- **WHEN** a request with an invalid bearer token is rejected by the resource server
- **THEN** an audit row with `action = 'AUTH_TOKEN_REJECTED'` and `outcome = 'DENIED'` records the source IP

### Requirement: Chat prompt audit events never contain the prompt body

For `CHAT_PROMPT` events, the audit `details` payload SHALL contain the prompt length in characters and the SHA-256 hex digest of the prompt body, and SHALL NOT contain the prompt text itself, any substring of it, or attached document content.

#### Scenario: Details hold length and hash only

- **WHEN** a user submits the prompt `What is the weather in Warsaw?`
- **THEN** the resulting `CHAT_PROMPT` audit row's `details` contains `prompt_length: 30` and the SHA-256 hex digest of the prompt
- **AND** the string `weather in Warsaw` appears nowhere in the row

### Requirement: Audit events are recorded via a service-layer recorder

Audit events SHALL be written through an `AuditRecorder` service (Spring application event published by the instrumented component, persisted by an asynchronous listener), never by writing log lines. A failure to persist an audit event SHALL NOT fail or delay the business operation; it SHALL log at ERROR and increment a Micrometer counter `audit.write.failed`. Erasure-lifecycle events (`ERASURE_REQUESTED`, `ERASURE_COMPLETED`) SHALL be written synchronously within the erasure job's own execution.

#### Scenario: Audit persistence failure does not fail the request

- **WHEN** the audit listener's insert throws (e.g. Postgres briefly unavailable) during a chat request
- **THEN** the chat request still completes with its normal response
- **AND** `audit_write_failed_total` increments by 1

#### Scenario: Recorder is the only write path

- **WHEN** the codebase is inspected for writes to `audit_log`
- **THEN** the only insert path is the `AuditRecorder` listener (plus Liquibase), and no component logs audit information as a substitute for recording it

### Requirement: ADMIN-only audit query API with filters and pagination

ascend-ai-agent SHALL expose `GET /api/v1/audit` returning audit rows ordered by `occurred_at` descending, filterable by `actor`, `action`, `outcome`, and a `from`/`to` time window, paginated via `page` and `size` (size capped at 200). The endpoint SHALL require the ADMIN role (from `add-auth-and-identity`); non-admin callers receive HTTP 403.

#### Scenario: Admin filters by action and time window

- **WHEN** an ADMIN calls `GET /api/v1/audit?action=DOCUMENT_UPLOADED&from=2026-07-01T00:00:00Z&page=0&size=50`
- **THEN** the response is HTTP 200 with a page envelope containing only `DOCUMENT_UPLOADED` rows at or after the `from` instant, newest first

#### Scenario: Non-admin is refused

- **WHEN** an authenticated user without the ADMIN role calls `GET /api/v1/audit`
- **THEN** the response is HTTP 403 and no audit data is returned
