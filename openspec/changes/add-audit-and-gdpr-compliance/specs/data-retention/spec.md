## ADDED Requirements

### Requirement: Scheduled retention prunes Postgres chat data

ascend-ai-agent SHALL run a scheduled retention job that deletes `chat_history` rows older than a configurable window `app.retention.chat-history`. The window SHALL accept a duration or the keep-forever value `forever`. When it is not set, its default SHALL be `forever` when the active module list equals the `personal` preset of `add-deployment-modules`, and `180d` for every other list, the company presets `core` and `company-docs` included. A set value SHALL always win. With `forever` the job SHALL delete no `chat_history` row. The job SHALL be the system task `retention` of `add-shared-scheduler`, with its cron from `app.scheduler.system-tasks.retention.*` (default `0 3 * * *` in `Europe/Warsaw`), and SHALL be run by exactly one agent instance through the shared scheduler, also when more than one agent instance runs. Deletes SHALL run in bounded batches so the job does not hold long table locks. The job SHALL log a per-run summary (rows deleted per table) and expose a Micrometer counter of deleted rows. User facts of `add-agent-soul` SHALL NOT be pruned by it: they are a profile kept until the user deletes them, and that change drops the `user_instructions` table.

#### Scenario: Expired chat rows removed

- **WHEN** the retention job runs while `chat_history` contains rows older and newer than the configured window
- **THEN** only the rows older than the window are deleted from `chat_history`
- **AND** rows within the window are untouched

#### Scenario: Two agent instances delete once

- **WHEN** two agent instances run and the `retention` system task falls due
- **THEN** exactly one instance runs it
- **AND** each expired row is deleted once

#### Scenario: Retention window configurable

- **WHEN** `app.retention.chat-history` is overridden to `30d`
- **THEN** the next run deletes rows older than 30 days rather than the 180-day default

#### Scenario: Personal preset keeps chat history forever by default

- **WHEN** the active module list equals the `personal` preset, `app.retention.chat-history` is not set, and the job runs while `chat_history` holds rows older than 180 days
- **THEN** no `chat_history` row is deleted

#### Scenario: Company preset keeps chat history 180 days by default

- **WHEN** the active module list equals the `company-docs` preset, `app.retention.chat-history` is not set, and the job runs
- **THEN** `chat_history` rows older than 180 days are deleted

#### Scenario: Keep-forever value set explicitly

- **WHEN** `app.retention.chat-history` is `forever` in a company preset and the job runs
- **THEN** no `chat_history` row is deleted

### Requirement: Retention removes conversations left with no messages

The same nightly job SHALL delete every conversation that has no `chat_history` row left and whose `updated_at` is older than `app.retention.empty-conversation-grace` (default `24h`). It SHALL delete such a conversation through the conversation delete path of `add-chat-streaming-and-conversations`, so the conversation's Redis key, pending approvals, runs, scheduled job links and chat platform binding are handled as in a delete by the user. It SHALL do so also when `app.retention.chat-history` is `forever`. The per-run summary SHALL count the deleted conversations.

#### Scenario: Conversation emptied by retention is removed

- **WHEN** the job deletes the last `chat_history` rows of a conversation and the conversation's `updated_at` is older than 24 hours
- **THEN** the same run deletes the conversation
- **AND** `GET /api/v1/conversations` of its user no longer lists it

#### Scenario: New empty conversation is kept

- **WHEN** a user created a conversation one hour ago and has sent no message in it, and the job runs
- **THEN** the conversation is kept

#### Scenario: Empty conversations are removed also when chat history is kept forever

- **WHEN** `app.retention.chat-history` is `forever` and a conversation with no messages was last updated three days ago, and the job runs
- **THEN** the conversation is deleted

### Requirement: Audit log rows have their own retention window

Audit rows SHALL be retained for a separately configured window `app.retention.audit-log` (default `730d` in every deployment, whatever the preset) and deleted by the same scheduled job through the audit table's sanctioned retention path (the only delete path the append-only trigger permits besides erasure pseudonymization).

#### Scenario: Audit retention independent of chat retention

- **WHEN** `app.retention.chat-history` is `180d` and `app.retention.audit-log` is `730d` and the job runs
- **THEN** audit rows between 180 and 730 days old survive while chat rows of the same age are deleted

### Requirement: Retention matrix is documented

`docs/COMPLIANCE.md` SHALL contain a retention matrix listing every user-data store and its bound: Postgres chat data (`app.retention.chat-history`, default `forever` in the `personal` preset and 180d in the company presets), empty conversations (deleted by the same job after `app.retention.empty-conversation-grace`, default 24h), Postgres audit log (`app.retention.audit-log`, default 730d), Redis chat cache (existing `app.memory.chat-history.ttl`), Loki logs (`LOKI_RETENTION_PERIOD`, default 2160h), Prometheus metrics (`PROMETHEUS_RETENTION_TIME`, default 72h), Tempo traces (`TEMPO_BLOCK_RETENTION`, default 2160h, owner decision 65.21 of 2026-10-04), and the stores bounded only by erasure (Floci `knowledge-base` documents, Qdrant vectors, AscendMemory memories, Keycloak user records, retained until deleted or erased), plus the ascend-ocr `ocr-results` bucket, bounded by ascend-ocr's own `OCR_JOB_RETENTION_SECONDS`. It SHALL also list the bounds the agent changes set: owner notifications (30 days, `add-shared-scheduler`), final scheduled jobs (30 days, `add-scheduled-tasks`), `self_review` rows (90 days, `retention.reviews`) and `self_change` rows (365 days, `retention.changes`) deleted by the system task `self-improvement-retention` of `add-self-improvement`, temporary downloads (24 hours after the last download, the retention sweep inside ascend-web-hunter of `add-file-download`), kept files (until deleted), crawl results in `web-hunter-crawls` (7 days, `CRAWL_JOB_RETENTION_SECONDS` of `enhance-web-search-crawl-at-scale`, default 604800, which also bounds the crawl job records, crawl progress and recrawl state), and user facts (kept until the user deletes them or erasure removes them). The export archives SHALL be cleaned up by the system task `export-archive-cleanup` of `add-shared-scheduler` after their configured window.

#### Scenario: Matrix present and complete

- **WHEN** `docs/COMPLIANCE.md` is read
- **THEN** it contains a table naming each store above with its retention bound, the controlling configuration property or config file, and the default value
