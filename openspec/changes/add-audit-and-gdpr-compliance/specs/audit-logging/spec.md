## ADDED Requirements

### Requirement: Append-only audit_log table records security-relevant events

ascend-ai-agent SHALL persist audit events to a Postgres table `audit_log` created via a Flyway versioned SQL migration, with columns for `occurred_at` (TIMESTAMPTZ), `actor`, `tenant` (nullable), `action`, `resource_type` (nullable), `resource_id` (nullable), `outcome`, `source_ip` (nullable), and a JSONB `details` payload. The table SHALL be append-only: a database-level trigger SHALL reject `UPDATE` and `DELETE` statements, except deletes issued through the retention job's sanctioned path and the pseudonymization rewrite performed by an erasure job.

#### Scenario: Ad-hoc mutation rejected by the database

- **WHEN** an `UPDATE audit_log SET outcome = 'OK'` or a plain `DELETE FROM audit_log` is executed against the database
- **THEN** the statement fails with a database error raised by the append-only trigger
- **AND** the targeted rows are unchanged

#### Scenario: Retention path can delete expired rows

- **WHEN** the retention job deletes audit rows older than the configured retention window through its sanctioned path
- **THEN** the delete succeeds and only rows older than the boundary are removed

### Requirement: Audit events cover the security-relevant action set

The system SHALL record an audit event for each of the following actions, using a closed action vocabulary: `AUTH_TOKEN_REJECTED` (a request bearing an invalid or expired token is rejected at the resource server), `CHAT_PROMPT` (a prompt request is accepted for processing), `DOCUMENT_UPLOADED`, `DOCUMENT_DELETED`, `DOCUMENT_PRESIGN_ISSUED` (a presigned download URL is handed to a caller), `INGESTION_RUN`, `MEMORY_WIPED`, `ERASURE_REQUESTED`, `ERASURE_COMPLETED`, `EXPORT_REQUESTED`, `EXPORT_COMPLETED`, `ADMIN_OPERATION`, and `QUOTA_REJECTED`. Each event SHALL carry the authenticated actor, the tenant when known, the outcome, and the caller's source IP when available. The `QUOTA_REJECTED` event is recorded by the quota-enforcement path of `add-usage-metering-and-quotas`, which lands later, through `AuditEventPort` of `add-deployment-modules`, and stored through this capability's implementation of that port.

Every action in the closed vocabulary SHALL use one naming style: upper case words joined by underscores, the subject first and then the event in the past tense, the style of the actions above, and the stored `action` value SHALL equal the `AuditAction` enum name. The closed vocabulary SHALL also hold the actions of the agent changes, in that style, each recorded by its owning change through `AuditEventPort` of `add-deployment-modules` and stored through this capability's implementation of that port:

- `add-agent-skills`: `SKILL_CREATED`, `SKILL_UPDATED`, `SKILL_DELETED`, `SKILL_REVERTED`, `SKILL_RELOADED`, never with the skill body.
- `add-agent-subagents`: `SUBAGENT_DEFINITION_WRITTEN`, `SUBAGENT_DEFINITION_DELETED`, `SUBAGENT_DEFINITION_REVERTED`, `SUBAGENT_DEFINITION_RELOADED`, `SUBAGENT_RUN_CANCELLED`, never with the definition body, a prompt or a result.
- `add-agent-soul`: `PERSONALITY_REPLACED`, `PERSONALITY_REVERTED`, `PERSONALITY_PROPOSED`, `PERSONALITY_APPROVED`, `PERSONALITY_REJECTED`, `PERSONALITY_EXPIRED`, `USER_FACTS_UPDATED`, `USER_FACTS_REPLACED`, `USER_FACTS_DELETED`, `USER_FACTS_REVERTED`, never with file content.
- `add-action-approvals`: `APPROVAL_REQUESTED`, `APPROVAL_DECIDED`, `APPROVAL_RULE_CHANGED`, `APPROVED_ACTION_EXECUTED`, with details holding the approval id, kind, category, tool name and arguments digest, and never the arguments.
- `add-obsidian-vault`: `OBSIDIAN_NOTE_WRITTEN` with outcome `written`, `approval_pending` or `refused`, with the content's length and SHA-256 and the full note path from the `details` entry `path`, and never the content.
- `add-openclaw-plugin-host`: `CHANNEL_PAIRING_CREATED`, `CHANNEL_LINK_CREATED`, `CHANNEL_LINK_REMOVED`, `CHANNEL_PAIRING_REDEEM_FAILED`, `CHANNEL_MESSAGE_REFUSED`, with details holding the platform, the link id or a hash of the account id and the reason, and never text or a code.
- `add-coding-agent-delegation`: `CODING_RUN_STARTED`, `CODING_RUN_PUBLISHED`, `CODING_PROJECT_CLEANED`, with the run or project id, repository and outcome, and never the task text or the diff.
- `add-scheduled-tasks`: `SCHEDULED_JOB_CREATED`, `SCHEDULED_JOB_UPDATED`, `SCHEDULED_JOB_CANCELLED`, `SCHEDULED_JOB_TRIGGERED`, `SCHEDULED_JOB_FIRED`, never with the prompt or a result.
- `add-self-improvement`: `SELF_IMPROVEMENT_REVIEWED`, `SELF_IMPROVEMENT_CHANGED`, `SELF_IMPROVEMENT_STAGED`, `SELF_IMPROVEMENT_GUARD_REVERTED`, `SELF_IMPROVEMENT_FROZEN`, `SELF_IMPROVEMENT_UNDONE`, `SELF_IMPROVEMENT_CASE_WRITTEN`, never with content.
- `add-self-built-integrations`: `INTEGRATION_BUILD_STARTED`, `INTEGRATION_BUILD_FINISHED`, `INTEGRATION_REGISTERED`, `INTEGRATION_ACTIVATED`, `INTEGRATION_DISABLED`, `INTEGRATION_ENABLED`, `INTEGRATION_ROLLED_BACK`, `INTEGRATION_REMOVED`, `INTEGRATION_TOOL_REVIEWED`, `INTEGRATION_CREDENTIAL_REVOKED`, never with a credential value, the API notes or source text.

#### Scenario: Chat request produces an audit row

- **WHEN** `POST /api/v1/ai/prompt` is processed for an authenticated user
- **THEN** exactly one `audit_log` row with `action = 'CHAT_PROMPT'` exists for that request, with `actor` equal to the authenticated user's identity and `outcome` reflecting success or failure

#### Scenario: Presigned URL issuance is audited

- **WHEN** a prompt with `attachSources=true` causes presigned download URLs for the Floci `knowledge-base` bucket to be generated
- **THEN** an audit row with `action = 'DOCUMENT_PRESIGN_ISSUED'` records the actor and the object keys (as `resource_id` / `details`), one row per issuance batch

#### Scenario: An approval decision is audited without its arguments

- **WHEN** an owner decides an approval of `add-action-approvals` for a tool call
- **THEN** an audit row with `action = 'APPROVAL_DECIDED'` records the approval id, kind, category, tool name and arguments digest
- **AND** no argument value of the tool call appears anywhere in the row

#### Scenario: Rejected token is audited

- **WHEN** a request with an invalid bearer token is rejected by the resource server
- **THEN** an audit row with `action = 'AUTH_TOKEN_REJECTED'` and `outcome = 'DENIED'` records the source IP

#### Scenario: Every action uses the one naming style

- **WHEN** the values of the `AuditAction` enum are listed
- **THEN** every value matches `^[A-Z]+(_[A-Z]+)*$`, and no value contains a dot or a lower case letter

### Requirement: Chat prompt audit events never contain the prompt body

For `CHAT_PROMPT` events, the audit `details` payload SHALL contain the prompt length in characters and the SHA-256 hex digest of the prompt body, and SHALL NOT contain the prompt text itself, any substring of it, or attached document content.

#### Scenario: Details hold length and hash only

- **WHEN** a user submits the prompt `What is the weather in Warsaw?`
- **THEN** the resulting `CHAT_PROMPT` audit row's `details` contains `prompt_length: 30` and the SHA-256 hex digest of the prompt
- **AND** the string `weather in Warsaw` appears nowhere in the row

#### Scenario: Owner decision of an approval is an audit row

- **WHEN** the owner approves a request of `add-action-approvals`
- **THEN** one audit row records the decision with the approval id, the digest, the deciding user and outcome `APPROVED`
- **AND** the row holds no argument text

#### Scenario: An Obsidian note write leaves an audit row without content

- **WHEN** the agent appends to a note of `add-obsidian-vault` inside its agent folder
- **THEN** an audit row with the action `OBSIDIAN_NOTE_WRITTEN`, outcome `written` and the content's SHA-256 exists
- **AND** the appended text appears in no audit field

### Requirement: Audit events are recorded via a service-layer recorder

Audit events SHALL be written through an `AuditRecorder` service (Spring application event published by the instrumented component, persisted by an asynchronous listener), never by writing log lines. A failure to persist an audit event SHALL NOT fail or delay the business operation; it SHALL log at ERROR and increment a Micrometer counter `audit.write.failed`. Erasure-lifecycle events (`ERASURE_REQUESTED`, `ERASURE_COMPLETED`) SHALL be written synchronously within the erasure job's own execution.

#### Scenario: Audit persistence failure does not fail the request

- **WHEN** the audit listener's insert throws (e.g. Postgres briefly unavailable) during a chat request
- **THEN** the chat request still completes with its normal response
- **AND** `audit_write_failed_total` increments by 1

#### Scenario: Recorder is the only write path

- **WHEN** the codebase is inspected for writes to `audit_log`
- **THEN** the only insert path is the `AuditRecorder` listener (plus the Flyway migrations), and no component logs audit information as a substitute for recording it

### Requirement: The audit recorder backs the company audit port

This capability SHALL register an implementation of `AuditEventPort` of `add-deployment-modules` that replaces the default `LogAuditEventPort` and hands every recorded event to `AuditRecorder`, so every event an earlier change records through the port becomes an `audit_log` row with no edit of that change. Every action name recorded through the port SHALL be a value of the closed vocabulary.

#### Scenario: An event recorded through the port becomes a row

- **WHEN** `add-action-approvals` records `APPROVAL_DECIDED` through `AuditEventPort` with this capability deployed
- **THEN** one `audit_log` row with action `APPROVAL_DECIDED`, the tenant, the actor and the outcome exists
- **AND** the default `LogAuditEventPort` bean does not exist

### Requirement: ADMIN-only audit query API with filters and pagination

ascend-ai-agent SHALL expose `GET /api/v1/audit` returning audit rows ordered by `occurred_at` descending, filterable by `actor`, `action`, `outcome`, and a `from`/`to` time window, paginated via `page` and `size` (size capped at 200). The endpoint SHALL require the tenant ADMIN role (from `add-keycloak-login`) and SHALL return only rows of the caller's own tenant, or the `PLATFORM_ADMIN` role of `add-tenant-administration`, which SHALL return rows of every tenant with an optional `tenant` filter. A tenant ADMIN SHALL still receive only rows of their own tenant, whatever `tenant` value they pass. Callers with neither role receive HTTP 403.

#### Scenario: Admin filters by action and time window

- **WHEN** an ADMIN calls `GET /api/v1/audit?action=DOCUMENT_UPLOADED&from=2026-07-01T00:00:00Z&page=0&size=50`
- **THEN** the response is HTTP 200 with a page envelope containing only `DOCUMENT_UPLOADED` rows of the ADMIN's own tenant at or after the `from` instant, newest first

#### Scenario: Non-admin is refused

- **WHEN** an authenticated user without the ADMIN role calls `GET /api/v1/audit`
- **THEN** the response is HTTP 403 and no audit data is returned

#### Scenario: Platform admin filters by tenant

- **WHEN** a `PLATFORM_ADMIN` calls `GET /api/v1/audit?tenant=acme`
- **THEN** the response contains only rows of tenant `acme`

#### Scenario: Tenant admin cannot widen the query

- **WHEN** an `ADMIN` of tenant `acme` calls `GET /api/v1/audit?tenant=globex`
- **THEN** the response contains only rows of tenant `acme`

### Requirement: The audit log is covered by end-to-end tests against the live stack

The ascend-ai-agent e2e suite SHALL check the audit query API, the audited actions that need no chat model and the append-only rule with deterministic Bruno tests and direct database statements. The `CHAT_PROMPT` and `DOCUMENT_PRESIGN_ISSUED` rows SHALL be proved by the audit instrumentation integration test, because an e2e spec of them would only repeat it (owner answer 91.3 of 2026-10-08). Pass criteria SHALL be statuses, response bodies and `audit_log` rows, never a log line.

#### Scenario: Audit query is checked for every caller in the live stack

- **WHEN** the audit query spec calls `GET /api/v1/audit` with no token, a `USER` token, an `ADMIN` token of `e2e-acme` and an `ADMIN` token of `e2e-globex`
- **THEN** the answers are 401, 403, the `e2e-acme` rows newest first, and rows of `e2e-globex` only
- **AND** a `size` above 200 returns at most 200 rows

#### Scenario: The database refuses to change an audit row in the live stack

- **WHEN** the audit query spec runs an `UPDATE` and a `DELETE` on an `audit_log` row through psql
- **THEN** both statements fail with the append-only trigger's error
- **AND** the row count is unchanged

#### Scenario: A chat turn is audited without its body

- **WHEN** the audit instrumentation integration test sends a prompt holding a unique marker
- **THEN** one `CHAT_PROMPT` row holds the prompt length and its SHA-256
- **AND** no `audit_log` row contains the marker
