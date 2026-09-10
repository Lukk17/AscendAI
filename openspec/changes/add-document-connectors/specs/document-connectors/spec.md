## ADDED Requirements

### Requirement: Connector configuration is persisted per tenant

The agent SHALL persist connector configurations in PostgreSQL via a Liquibase changelog. Each configuration SHALL carry: connector type, display name, a credentials reference (an opaque handle into the encrypted credential store, never the secret material itself), a provider-specific source scope (e.g., site/drive/folder identifiers), a sync schedule (cron expression), a maximum sync age, an enabled flag, the timestamp of the last successful sync, a stale flag, and the owning tenant. All connector reads and writes SHALL be scoped to the caller's tenant. A configuration whose maximum sync age is not greater than the interval its cron schedule fires on SHALL be rejected at write time.

#### Scenario: Connector created and persisted

- **WHEN** an ADMIN creates a SharePoint connector with a display name, credentials reference, site/drive scope, and a cron schedule
- **THEN** a connector row exists in PostgreSQL carrying those fields and the caller's tenant
- **AND** the row contains a credentials reference, not the client secret

#### Scenario: Tenant cannot see another tenant's connectors

- **WHEN** an ADMIN of tenant A lists connectors while tenant B also has connectors configured
- **THEN** the response contains only tenant A's connectors

#### Scenario: Maximum sync age below the schedule interval is rejected

- **WHEN** an ADMIN creates or updates a connector whose maximum sync age is shorter than or equal to the interval its cron schedule fires on
- **THEN** the request is rejected with HTTP 400 and a message naming both values
- **AND** no connector row is created or modified

### Requirement: Connector endpoints require the ADMIN role in the security filter chain

The agent SHALL add a filter-chain rule requiring the `ADMIN` role for every path under `/api/v1/connectors`, alongside the authorization matrix that `add-auth-and-identity` establishes. That matrix leaves every path it does not name at merely authenticated, so without this rule any authenticated caller reaches the connector surface. The rule SHALL live in the same filter chain configuration as the rest of the matrix rather than in method annotations, so that one place answers which roles reach which paths. An unauthenticated caller SHALL receive HTTP 401 and an authenticated caller holding only the `USER` role SHALL receive HTTP 403, on every connector path including the sync trigger and the run-history reads.

#### Scenario: USER is refused every connector path

- **WHEN** a caller holding a valid token with only the `USER` role calls any path under `/api/v1/connectors`, including a sync trigger and a run-history read
- **THEN** the response status is 403
- **AND** no connector data, credentials reference, or source scope appears in the response body

#### Scenario: Unauthenticated caller is refused before authorization

- **WHEN** any path under `/api/v1/connectors` is called with no `Authorization` header in the secured posture
- **THEN** the response status is 401

#### Scenario: The rule is visible in the filter chain

- **WHEN** the security filter chain is inspected for the paths it authorizes
- **THEN** `/api/v1/connectors/**` appears there with an `ADMIN` requirement
- **AND** no connector endpoint relies on a method-level annotation as its only authorization check

### Requirement: Connector CRUD API restricted to ADMIN

The agent SHALL expose a connector management REST API under `/api/v1/connectors` supporting: create, list, get, update, disable, delete, trigger-sync-now, and get sync history. Every endpoint SHALL require the ADMIN role (as defined by `add-auth-and-identity` and enforced by the filter-chain rule above); callers without it SHALL receive HTTP 403. Credential material SHALL be write-only: accepted on create/update, never returned by any read endpoint. Run history SHALL expose counters, per-file actions, and storage keys, and SHALL NOT expose any principal identifier.

#### Scenario: Non-admin rejected

- **WHEN** a caller with only the USER role sends `GET /api/v1/connectors`
- **THEN** the agent returns HTTP 403
- **AND** no connector data is returned

#### Scenario: Secrets never echoed

- **WHEN** an ADMIN creates a connector supplying a client secret and then fetches that connector
- **THEN** the response contains the connector configuration and a credentials reference
- **AND** the client secret value appears nowhere in the response body

#### Scenario: Principal identifiers absent from run history

- **WHEN** an ADMIN fetches the run history for a connector whose last run landed documents
- **THEN** each outcome carries its action, source path, and MinIO key
- **AND** no principal identifier appears in the response body

#### Scenario: Disable stops future syncs

- **WHEN** an ADMIN disables a connector
- **THEN** subsequent scheduler ticks do not start sync runs for it
- **AND** its configuration and sync history remain readable

#### Scenario: Delete removes configuration but not ingested documents

- **WHEN** an ADMIN deletes a connector that has previously synced documents
- **THEN** its configuration, sync cursors, and run history are removed
- **AND** the documents it ingested remain in MinIO and Qdrant, retrievable by the company that owns them

### Requirement: Scheduled incremental sync runs per enabled connector

The agent SHALL run an incremental sync for each enabled connector according to its cron schedule. A due connector SHALL be claimed atomically (database row lock) so that concurrent agent instances execute at most one sync run per connector per due tick. Each run SHALL fetch only content changes since the connector's persisted content cursor; the content cursor SHALL advance only after the run completes, so a failed run retries the same change window. A run with trigger `SCHEDULED` or `MANUAL` that completes with status `SUCCEEDED` or `PARTIAL` SHALL record the time of that completion as the connector's last successful sync. No other run SHALL move that timestamp.

#### Scenario: Due connector syncs once

- **WHEN** a connector's schedule comes due while two agent instances are running
- **THEN** exactly one sync run is recorded for that tick

#### Scenario: Failed run does not advance the cursor

- **WHEN** a sync run fails after fetching changes but before completing
- **THEN** the persisted content cursor still holds its pre-run value
- **AND** the next run re-fetches the same change window
- **AND** the connector's last successful sync timestamp is unchanged

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

The agent SHALL persist one record per sync run: trigger type (`SCHEDULED`, `MANUAL`, `FRESHNESS_CHECK`), status (`RUNNING`, `SUCCEEDED`, `PARTIAL`, `FAILED`), start/finish timestamps, and counters for added / updated / deleted / skipped / failed files, and one record per touched file with its source path, action, resulting MinIO key, and a failure reason where applicable. The per-file action set SHALL be `ADDED`, `UPDATED`, `DELETED`, `SKIPPED`, `FAILED`. History SHALL be readable via the API per connector.

#### Scenario: Run outcome recorded

- **WHEN** a sync run lands two new files, updates one, and skips one disallowed type
- **THEN** the run record shows status `SUCCEEDED` with counters added=2, updated=1, skipped=1
- **AND** four per-file outcome records exist, the skipped one carrying its reason

#### Scenario: Per-file failure does not hide the rest

- **WHEN** one file in a batch fails to download and the others succeed
- **THEN** the run completes with status `PARTIAL`
- **AND** the failed file's outcome record carries the failure reason while the successful files' records show their MinIO keys

### Requirement: Connectors land bytes and reuse the existing ingestion pipeline

A connector SHALL deliver documents by writing the source file's bytes to MinIO under the tenant prefix (markdown into the markdown folder, everything else into the documents folder, matching the upload controller's routing) and then triggering the existing bucket-scan ingestion for the affected prefix. Connectors SHALL NOT parse, chunk, or embed content themselves, and SHALL NOT write to the vector store by any route.

Before the MinIO write, connector-fetched files SHALL pass the same filename sanitization and sniffed-MIME allowlist checks (`app.ingestion.upload.allowed-mime-types`) that govern manual uploads; object keys SHALL include a sanitized source-relative path segment so distinct source files cannot collide on a shared leaf name.

#### Scenario: Synced file flows through the existing pipeline

- **WHEN** a connector sync fetches a new PDF from the source
- **THEN** the PDF bytes are written to MinIO under the tenant's documents prefix
- **AND** the existing ingestion scan indexes it into Qdrant through the standard parse path
- **AND** no chunk for that PDF was written to Qdrant by the connector itself

#### Scenario: Disallowed type is skipped before storage

- **WHEN** a connector sync encounters a source file whose sniffed MIME type is not in the allowlist
- **THEN** no MinIO write and no Qdrant write occur for that file
- **AND** the file's outcome record shows `SKIPPED` with the disallowed type as reason

#### Scenario: The framework holds no vector-store handle

- **WHEN** the connector framework's interfaces and orchestrator are inspected
- **THEN** neither exposes a vector store nor an embedding client
- **AND** every chunk that exists for a connector-landed document was produced by the existing ingestion pipeline

### Requirement: Connector-landed documents are visible to the whole owning company

Every chunk produced from a connector-landed document SHALL carry an access list of exactly `["tenant:everyone:{tenantId}"]` with `acl_source` of `tenant-default`, a matching `acl_version`, and `acl_synced_at` set at ingestion, written by the same ingestion producer default that `add-tenant-isolation` applies to a document with no source-captured list. A connector SHALL NOT compose, assemble, or supply an access list of its own, and SHALL NOT set `acl_source` to a connector name, because no part of that list was decided by the source.

Per-document permissions captured from the source are out of scope for this version. A connector SHALL NOT read item or container permissions from the source, and SHALL NOT request an application permission that exists only to resolve them.

#### Scenario: Synced document is retrievable by a caller in the owning company

- **WHEN** a connector of tenant `acme` lands a document and the ingestion pipeline indexes it
- **THEN** every chunk of that document carries `acl` equal to `["tenant:everyone:acme"]` and `acl_source` of `tenant-default`
- **AND** an authenticated caller of tenant `acme`, whose principal set contains `tenant:everyone:acme`, retrieves that document for a matching prompt

#### Scenario: Synced document is not retrievable across tenants

- **WHEN** a caller of tenant `globex` sends a prompt matching a document synced by a connector of tenant `acme`
- **THEN** no chunk of that document is returned

#### Scenario: The connector produces no access list

- **WHEN** the connector framework and the SharePoint connector are inspected for access-list construction
- **THEN** neither builds a principal string, calls a principal factory, nor sets any of the four access-list metadata keys
- **AND** the only producer of `tenant:everyone:{tenantId}` remains the helper owned by `add-tenant-isolation`

### Requirement: Deduplication for connector-landed objects uses the existing content marker

The ingestion deduplication marker for a connector-landed object SHALL be the existing content-keyed marker, `manual-ingestion:<key>:<etag>`, unchanged in format from the manual upload paths. A connector SHALL NOT introduce a second marker format. An object whose bytes are unchanged since the previous run SHALL be skipped without re-parsing, re-chunking, or re-embedding; an object whose bytes changed SHALL be re-indexed.

#### Scenario: Unchanged file is a no-op

- **WHEN** a sync re-lands a file whose bytes are identical to the object already in MinIO
- **THEN** the deduplication marker matches and re-indexing is skipped
- **AND** the Qdrant chunk count and point identifiers for that source are unchanged
- **AND** the file's outcome record shows `SKIPPED`

#### Scenario: Changed file is re-indexed

- **WHEN** a file's bytes change at the source
- **THEN** the deduplication marker differs and the file is re-parsed, re-chunked, and re-embedded
- **AND** the file's outcome record shows `UPDATED`

#### Scenario: The marker format is unchanged

- **WHEN** a connector-landed object's deduplication marker is compared with the marker a manual upload of the same object would produce
- **THEN** the two strings are byte-identical

### Requirement: Sync freshness check

The agent SHALL run a scheduled check that compares each enabled connector's last successful sync against its configured maximum sync age and marks a connector that has exceeded it as stale. The stale flag SHALL be returned by the connector read and list endpoints, and the time since each connector's last successful sync SHALL be exposed as a metric. A successful sync SHALL clear the flag. The check SHALL be claimed with the same database row lock as a scheduled sync so that concurrent agent instances do not act on one connector twice, and it SHALL record a run with trigger type `FRESHNESS_CHECK` only when a connector's stale state changes.

The check SHALL NOT write to MinIO, SHALL NOT write to the vector store, and SHALL NOT call the source, so that it stays able to report an outage in the very machinery that failed. A `FRESHNESS_CHECK` run SHALL NOT move the connector's last successful sync timestamp, so a check can never clear the condition it exists to report.

#### Scenario: Silently stopped connector becomes visible

- **WHEN** a connector has completed no successful sync for longer than its maximum sync age
- **THEN** the connector reads as stale on the connector read and list endpoints
- **AND** its time-since-last-successful-sync metric exceeds the maximum sync age
- **AND** one run with trigger type `FRESHNESS_CHECK` is recorded for the transition

#### Scenario: The check changes no document

- **WHEN** the freshness check marks a connector stale
- **THEN** every document that connector landed still exists in MinIO
- **AND** every chunk of those documents still carries its text, its access list, and its other metadata keys
- **AND** a caller of the owning company still retrieves those documents

#### Scenario: Healthy connector is never marked stale

- **WHEN** a connector completes a successful sync on its schedule and that schedule fires more often than its maximum sync age
- **THEN** the connector never reads as stale
- **AND** no `FRESHNESS_CHECK` run is recorded for it

#### Scenario: Recovery clears the flag

- **WHEN** a stale connector completes a successful sync
- **THEN** the stale flag is cleared in that run
- **AND** one `FRESHNESS_CHECK` run records the transition back

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

Connector secret material SHALL be stored only in the encrypted credential store (same mechanism family as BYOK keys in `add-usage-metering-and-quotas`), referenced from connector rows by an opaque handle. Secret values SHALL never appear in application logs at any log level, in sync-run records, or in API responses, including error paths such as failed authentication.

#### Scenario: Secret absent from persistence and logs

- **WHEN** a connector is created and a sync run subsequently fails authentication against the source
- **THEN** the connector table and sync-run records contain only the credentials reference
- **AND** the captured application logs for the whole flow contain no substring of the client secret
