## ADDED Requirements

### Requirement: Scheduled retention prunes Postgres chat data

AscendAgent SHALL run a scheduled retention job that deletes `chat_history` and `user_instructions` rows older than a configurable window `app.retention.chat-history` (default `180d`). Deletes SHALL run in bounded batches so the job does not hold long table locks. The job SHALL log a per-run summary (rows deleted per table) and expose a Micrometer counter of deleted rows.

#### Scenario: Expired chat rows removed

- **WHEN** the retention job runs while `chat_history` contains rows older and newer than the configured window
- **THEN** only the rows older than the window are deleted from `chat_history` and `user_instructions`
- **AND** rows within the window are untouched

#### Scenario: Retention window configurable

- **WHEN** `app.retention.chat-history` is overridden to `30d`
- **THEN** the next run deletes rows older than 30 days rather than the 180-day default

### Requirement: Audit log rows have their own retention window

Audit rows SHALL be retained for a separately configured window `app.retention.audit-log` (default `730d`) and deleted by the same scheduled job through the audit table's sanctioned retention path (the only delete path the append-only trigger permits besides erasure pseudonymization).

#### Scenario: Audit retention independent of chat retention

- **WHEN** `app.retention.chat-history` is `180d` and `app.retention.audit-log` is `730d` and the job runs
- **THEN** audit rows between 180 and 730 days old survive while chat rows of the same age are deleted

### Requirement: Retention matrix is documented

`docs/COMPLIANCE.md` SHALL contain a retention matrix listing every user-data store and its bound: Postgres chat data (`app.retention.chat-history`, default 180d), Postgres audit log (`app.retention.audit-log`, default 730d), Redis chat cache (existing `app.memory.chat-history.ttl`), Loki logs (168h), Prometheus metrics (72h), Tempo traces (168h), and the stores bounded only by erasure (MinIO documents, Qdrant vectors, AscendMemory memories — retained until deleted or erased).

#### Scenario: Matrix present and complete

- **WHEN** `docs/COMPLIANCE.md` is read
- **THEN** it contains a table naming each store above with its retention bound, the controlling configuration property or config file, and the default value
