## ADDED Requirements

### Requirement: Connector configuration is persisted per tenant

The agent SHALL persist connector configurations in PostgreSQL via a Liquibase changelog. Each configuration SHALL carry: connector type, display name, a credentials reference (an opaque handle into the encrypted credential store — never the secret material itself), a provider-specific source scope (e.g., site/drive/folder identifiers), a sync schedule (cron expression), an enabled flag, and the owning tenant. All connector reads and writes SHALL be scoped to the caller's tenant.

#### Scenario: Connector created and persisted

- **WHEN** an ADMIN creates a SharePoint connector with a display name, credentials reference, site/drive scope, and a cron schedule
- **THEN** a connector row exists in PostgreSQL carrying those fields and the caller's tenant
- **AND** the row contains a credentials reference, not the client secret

#### Scenario: Tenant cannot see another tenant's connectors

- **WHEN** an ADMIN of tenant A lists connectors while tenant B also has connectors configured
- **THEN** the response contains only tenant A's connectors

### Requirement: Connector CRUD API restricted to ADMIN

The agent SHALL expose a connector management REST API under `/api/v1/connectors` supporting: create, list, get, update, disable, delete, trigger-sync-now, and get sync history. Every endpoint SHALL require the ADMIN role (as defined by `add-auth-and-identity`); callers without it SHALL receive HTTP 403. Credential material SHALL be write-only: accepted on create/update, never returned by any read endpoint.

#### Scenario: Non-admin rejected

- **WHEN** a caller with only the USER role sends `GET /api/v1/connectors`
- **THEN** the agent returns HTTP 403
- **AND** no connector data is returned

#### Scenario: Secrets never echoed

- **WHEN** an ADMIN creates a connector supplying a client secret and then fetches that connector
- **THEN** the response contains the connector configuration and a credentials reference
- **AND** the client secret value appears nowhere in the response body

#### Scenario: Disable stops future syncs

- **WHEN** an ADMIN disables a connector
- **THEN** subsequent scheduler ticks do not start sync runs for it
- **AND** its configuration and sync history remain readable

#### Scenario: Delete removes configuration but not ingested documents

- **WHEN** an ADMIN deletes a connector that has previously synced documents
- **THEN** its configuration, sync cursors, and run history are removed
- **AND** the documents it ingested remain in MinIO and Qdrant

### Requirement: Scheduled incremental sync runs per enabled connector

The agent SHALL run an incremental sync for each enabled connector according to its cron schedule. A due connector SHALL be claimed atomically (database row lock) so that concurrent agent instances execute at most one sync run per connector per due tick. Each run SHALL fetch only changes since the connector's persisted sync cursor; the cursor SHALL advance only after the run completes, so a failed run retries the same change window.

#### Scenario: Due connector syncs once

- **WHEN** a connector's schedule comes due while two agent instances are running
- **THEN** exactly one sync run is recorded for that tick

#### Scenario: Failed run does not advance the cursor

- **WHEN** a sync run fails after fetching changes but before completing
- **THEN** the persisted sync cursor still holds its pre-run value
- **AND** the next run re-fetches the same change window

### Requirement: Manual sync trigger

The agent SHALL allow an ADMIN to trigger an immediate sync run for a connector via the API. A manual trigger SHALL be rejected with HTTP 409 while a run for the same connector is already in progress.

#### Scenario: Trigger-sync-now starts a run

- **WHEN** an ADMIN calls the trigger-sync-now endpoint for an idle, enabled connector
- **THEN** a sync run starts and is recorded with trigger type `MANUAL`

#### Scenario: Concurrent trigger rejected

- **WHEN** an ADMIN triggers a sync while a run for that connector is in progress
- **THEN** the agent returns HTTP 409
- **AND** no second run is started

### Requirement: Sync-run history with per-file outcomes

The agent SHALL persist one record per sync run — trigger type, status (`RUNNING`, `SUCCEEDED`, `PARTIAL`, `FAILED`), start/finish timestamps, and counters for added/updated/deleted/skipped/failed files — and one record per touched file with its source path, action, resulting MinIO key, and failure reason where applicable. History SHALL be readable via the API per connector.

#### Scenario: Run outcome recorded

- **WHEN** a sync run lands two new files, updates one, and skips one disallowed type
- **THEN** the run record shows status `SUCCEEDED` with counters added=2, updated=1, skipped=1
- **AND** four per-file outcome records exist, the skipped one carrying its reason

#### Scenario: Per-file failure does not hide the rest

- **WHEN** one file in a batch fails to download and the others succeed
- **THEN** the run completes with status `PARTIAL`
- **AND** the failed file's outcome record carries the failure reason while the successful files' records show their MinIO keys

### Requirement: Connectors land bytes in MinIO and reuse the existing ingestion pipeline

A connector SHALL deliver documents by writing the source file's bytes to MinIO under the tenant prefix — markdown into the markdown folder, everything else into the documents folder, matching the upload controller's routing — and then triggering the existing bucket-scan ingestion for the affected prefix. Connectors SHALL NOT parse, chunk, or embed content themselves, and SHALL NOT write to Qdrant directly. Before the MinIO write, connector-fetched files SHALL pass the same filename sanitization and sniffed-MIME allowlist checks (`app.ingestion.upload.allowed-mime-types`) that govern manual uploads; object keys SHALL include a sanitized source-relative path segment so distinct source files cannot collide on a shared leaf name.

#### Scenario: Synced file flows through the existing pipeline

- **WHEN** a connector sync fetches a new PDF from the source
- **THEN** the PDF bytes are written to MinIO under the tenant's documents prefix
- **AND** the existing ingestion scan indexes it into Qdrant through the standard parse path

#### Scenario: Disallowed type is skipped before storage

- **WHEN** a connector sync encounters a source file whose sniffed MIME type is not in the allowlist
- **THEN** no MinIO write and no Qdrant write occur for that file
- **AND** the file's outcome record shows `SKIPPED` with the disallowed type as reason

#### Scenario: Unchanged file re-landed is a no-op

- **WHEN** a sync re-writes a file whose bytes are identical to the object already in MinIO
- **THEN** the existing ETag-based dedup skips re-indexing
- **AND** the Qdrant chunk count for that source is unchanged

### Requirement: Deletion propagation

When a sync detects that a previously synced file was removed at the source, the agent SHALL remove the corresponding MinIO object and its Qdrant chunks during that run, using the single-document deletion path owned by `add-document-management-api`. The deletion SHALL be recorded as a per-file outcome with action `DELETED`.

#### Scenario: Source deletion removes MinIO object and chunks

- **WHEN** a file that was synced in an earlier run is deleted at the source and the next sync runs
- **THEN** the MinIO object for that file no longer exists
- **AND** Qdrant contains no chunks whose source metadata references it
- **AND** the run's history shows a `DELETED` outcome for that file

#### Scenario: Deletion of a never-synced file is ignored

- **WHEN** the source reports a deletion for an item the connector never landed (e.g., filtered out by type)
- **THEN** no MinIO or Qdrant operation is attempted
- **AND** the run does not fail

### Requirement: Connector credentials are encrypted at rest and never logged

Connector secret material SHALL be stored only in the encrypted credential store (same mechanism family as BYOK keys in `add-usage-metering-and-quotas`), referenced from connector rows by an opaque handle. Secret values SHALL never appear in application logs at any log level, in sync-run records, or in API responses — including error paths such as failed authentication.

#### Scenario: Secret absent from persistence and logs

- **WHEN** a connector is created and a sync run subsequently fails authentication against the source
- **THEN** the connector table and sync-run records contain only the credentials reference
- **AND** the captured application logs for the whole flow contain no substring of the client secret
