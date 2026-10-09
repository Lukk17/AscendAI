## ADDED Requirements

### Requirement: The connector framework is part of the core document search

The connector framework SHALL be part of the core document search (`rag`), which is always on and is not a module. The connector API, the orchestrator, the `connector-sync` task and the `connector-freshness-check` system task SHALL carry no `@ConditionalOnModule`, SHALL exist whatever `ASCEND_MODULES` holds, and SHALL NOT be guarded by a tenant module grant. A connector type that needs a switchable module of `add-deployment-modules` SHALL carry that module's `@ConditionalOnModule`. With that module not in `ASCEND_MODULES` the type SHALL NOT exist, and a create of a connector of that type SHALL answer HTTP 400 with an RFC 7807 problem detail whose `code` is `validation`.

#### Scenario: Framework exists without any switchable module

- **WHEN** the agent starts with an `ASCEND_MODULES` that holds no switchable module
- **THEN** `GET /api/v1/connectors` called by an ADMIN answers 200
- **AND** both `connector-sync` and `connector-freshness-check` are registered on the shared scheduler

#### Scenario: Type of a switchable module that is off

- **WHEN** a connector type carries `@ConditionalOnModule("web-search")`, the agent runs without `web-search` in `ASCEND_MODULES`, and an ADMIN creates a connector of that type
- **THEN** the response status is 400 with `code` `validation`

### Requirement: Connector configuration is persisted per tenant

The agent SHALL persist connector configurations in PostgreSQL via a Flyway versioned SQL migration. Each configuration SHALL carry: connector type, display name, a credentials reference (an opaque handle into the encrypted credential store, never the secret material itself), a provider-specific source scope (e.g., site/drive/folder identifiers), a sync schedule (a five-field cron expression and a time zone, validated by the shared `CronRule` of `add-shared-scheduler`), a maximum sync age, an enabled flag, the timestamp of the last successful sync, a stale flag, and the owning tenant. All connector reads and writes SHALL be scoped to the caller's tenant. A configuration whose maximum sync age is not greater than the interval its cron schedule fires on, measured as `CronRule`'s shortest gap between the next firings in the connector's time zone, SHALL be rejected at write time.

Each connector type SHALL declare whether it needs a credential and whether its schedule comes from the connector's own cron or from a named system task of `add-shared-scheduler`. For a type that needs no credential, the credentials reference SHALL be empty and the framework SHALL NOT resolve one. For a type whose schedule comes from a system task, a create or update that carries a cron SHALL be rejected, no per connector sync execution SHALL exist, and the maximum sync age SHALL be measured against the shortest gap of that system task's cron. Every rejected configuration SHALL answer HTTP 400 with an RFC 7807 problem detail whose `code` is `validation`.

#### Scenario: Connector created and persisted

- **WHEN** an ADMIN creates a connector of a type that needs a credential, with a display name, a credential, a source scope and a cron schedule
- **THEN** a connector row exists in PostgreSQL carrying those fields and the caller's tenant
- **AND** the row contains a credentials reference, not the client secret

#### Scenario: Tenant cannot see another tenant's connectors

- **WHEN** an ADMIN of tenant A lists connectors while tenant B also has connectors configured
- **THEN** the response contains only tenant A's connectors

#### Scenario: Maximum sync age below the schedule interval is rejected

- **WHEN** an ADMIN creates or updates a connector whose maximum sync age is shorter than or equal to the interval its cron schedule fires on
- **THEN** the request is rejected with HTTP 400, a problem detail with `code` `validation` and a `detail` naming both values
- **AND** no connector row is created or modified

#### Scenario: Cron schedule is evaluated in the connector's time zone

- **WHEN** an ADMIN creates a connector with the cron `0 6 * * *` and the time zone `Europe/Warsaw`
- **THEN** its next scheduled sync is at 06:00 Warsaw time
- **AND** a cron with six fields or an unknown time zone is rejected with HTTP 400 and `code` `validation`

#### Scenario: A connector type that needs no credential is created without one

- **WHEN** an ADMIN creates a connector of a type that declares it needs no credential, for example `OBSIDIAN`
- **THEN** the connector row is created with an empty credentials reference
- **AND** no sync run of that connector resolves a credential

#### Scenario: A cron is refused for a type whose schedule comes from a system task

- **WHEN** an ADMIN creates or updates a connector of a type whose schedule comes from a system task, for example `OBSIDIAN`, and the request carries a cron
- **THEN** the request is rejected with HTTP 400 and `code` `validation`
- **AND** no connector row is created or modified and no sync execution exists for it

### Requirement: Connector endpoints require the ADMIN role in the security filter chain

The agent SHALL add a row requiring the `ADMIN` role for every path under `/api/v1/connectors` to the authorization matrix of `add-keycloak-login`. That matrix leaves every path it does not name at merely authenticated, so without this row any authenticated caller reaches the connector surface. The rule SHALL live in the same filter chain configuration as the rest of the matrix rather than in method annotations, so that one place answers which roles reach which paths. An unauthenticated caller SHALL receive HTTP 401 with an RFC 7807 problem detail whose `code` is `unauthorized`, and an authenticated caller holding only the `USER` role SHALL receive HTTP 403 with `code` `forbidden`, on every connector path including the sync trigger and the run-history reads.

#### Scenario: USER is refused every connector path

- **WHEN** a caller holding a valid token with only the `USER` role calls any path under `/api/v1/connectors`, including a sync trigger and a run-history read
- **THEN** the response status is 403 with `code` `forbidden`
- **AND** no connector data, credentials reference, or source scope appears in the response body

#### Scenario: Unauthenticated caller is refused before authorization

- **WHEN** any path under `/api/v1/connectors` is called with no `Authorization` header in the secured posture
- **THEN** the response status is 401

#### Scenario: The rule is visible in the filter chain

- **WHEN** the security filter chain is inspected for the paths it authorizes
- **THEN** `/api/v1/connectors/**` appears there with an `ADMIN` requirement
- **AND** no connector endpoint relies on a method-level annotation as its only authorization check

### Requirement: Connector CRUD API restricted to ADMIN

The agent SHALL expose a connector management REST API under `/api/v1/connectors` supporting: create, list, get, update, disable, delete, trigger-sync-now, and get sync history. Every endpoint SHALL require the ADMIN role (as defined by `add-keycloak-login` and enforced by the matrix row above). Callers without it SHALL receive HTTP 403. Credential material SHALL be write-only: accepted on create/update, never returned by any read endpoint. Run history SHALL expose counters, per-file actions, and storage keys, and SHALL NOT expose any principal identifier.

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
- **THEN** each outcome carries its action, source path, and object key
- **AND** no principal identifier appears in the response body

#### Scenario: Disable stops future syncs

- **WHEN** an ADMIN disables a connector
- **THEN** its `connector-sync` execution on the shared scheduler is removed in the same transaction and no scheduled sync run starts for it
- **AND** its configuration and sync history remain readable

#### Scenario: Delete removes configuration but not ingested documents

- **WHEN** an ADMIN deletes a connector that has previously synced documents
- **THEN** its configuration, sync cursors, and run history are removed
- **AND** the documents it ingested remain in object storage and Qdrant, retrievable by callers of the owning tenant

### Requirement: Scheduled incremental sync runs per enabled connector

The agent SHALL run an incremental sync for each enabled connector according to its cron schedule in its time zone. Each enabled connector whose type takes its schedule from the connector's own cron SHALL have exactly one execution `connector-sync/<connectorId>` on the shared scheduler of `add-shared-scheduler`, and creating, updating, enabling, disabling and deleting a connector SHALL create, reschedule or remove that execution in the same transaction as the connector row. A due connector SHALL be run by exactly one agent instance through the shared scheduler, so that concurrent agent instances execute at most one sync run per connector per due tick. At most one run of a connector SHALL be in progress at any time. Each run SHALL fetch only content changes since the connector's persisted content cursor. The content cursor SHALL advance only after the run completes, so a failed run retries the same change window. A run with trigger `SCHEDULED`, `MANUAL` or `EVENT` that completes with status `SUCCEEDED` or `PARTIAL` SHALL record the time of that completion as the connector's last successful sync. No other run SHALL move that timestamp.

A run that starts without a request, of a connector type that belongs to a switchable module, SHALL first check that the connector's tenant holds that module's grant, and SHALL be skipped with the reason `module_denied` when it does not, recording no run and leaving the last successful sync unchanged. A run of a core connector type SHALL NOT check any module grant.

#### Scenario: Due connector syncs once

- **WHEN** a connector's schedule comes due while two agent instances are running
- **THEN** exactly one sync run is recorded for that tick

#### Scenario: Failed run does not advance the cursor

- **WHEN** a sync run fails after fetching changes but before completing
- **THEN** the persisted content cursor still holds its pre-run value
- **AND** the next run re-fetches the same change window
- **AND** the connector's last successful sync timestamp is unchanged

#### Scenario: Connector change and its execution commit together

- **WHEN** an ADMIN changes a connector's cron and the transaction that saves the connector row rolls back
- **THEN** the connector's `connector-sync` execution keeps its previous next time

#### Scenario: Sync for a tenant without the module grant is skipped

- **WHEN** the `connector-sync` execution of a connector whose type carries `@ConditionalOnModule("web-search")` fires and the connector's tenant does not hold the module grant `web-search`
- **THEN** no sync run starts and no run record is written
- **AND** the skip is logged with the reason `module_denied`

### Requirement: Manual sync trigger

The agent SHALL allow an ADMIN to trigger an immediate sync run for a connector via the API. A manual trigger SHALL be rejected with HTTP 409 and an RFC 7807 problem detail whose `code` is `connector_run_in_progress` while a run for the same connector is already in progress. An unknown connector id, or one of another tenant, SHALL answer HTTP 404 with `code` `not_found`.

#### Scenario: Trigger-sync-now starts a run

- **WHEN** an ADMIN calls the trigger-sync-now endpoint for an idle, enabled connector
- **THEN** a sync run starts and is recorded with trigger type `MANUAL`

#### Scenario: Concurrent trigger rejected

- **WHEN** an ADMIN triggers a sync while a run for that connector is in progress
- **THEN** the agent returns HTTP 409 with `code` `connector_run_in_progress`
- **AND** no second run is started

### Requirement: Event and scheduled starts during a run queue one follow-up run

The agent SHALL accept the run trigger `EVENT` for a change a connector itself noticed at its source. When an `EVENT` trigger or a `SCHEDULED` start finds a run of the same connector in progress, it SHALL NOT start a second run and SHALL NOT answer 409. It SHALL mark the connector dirty, and exactly one follow-up run SHALL start when the run in progress ends, whatever that run's status. The manual trigger SHALL keep its 409. Whether a run is in progress SHALL be decided by a lock in PostgreSQL that every agent instance sees, never by the memory of one instance: a session advisory lock in the two-key form whose class key is `AdvisoryLockClass.CONNECTOR_RUN` (value 1) and whose second key is derived from the connector id, and a `RUNNING` run left by an instance that stopped SHALL be closed as `FAILED` with the error summary `interrupted` instead of blocking the connector.

#### Scenario: A start on a second instance during a run starts no second run

- **WHEN** a connector's run is in progress on one agent instance and an `EVENT` start for it arrives on another instance
- **THEN** no second run starts on either instance
- **AND** exactly one follow-up run starts when the first run ends

#### Scenario: A run of a stopped instance does not block the connector

- **WHEN** the agent instance running a connector's run stops before the run ends, and a manual trigger for that connector arrives on another instance
- **THEN** the left `RUNNING` record is closed as `FAILED` with the error summary `interrupted`
- **AND** the manual trigger starts a new run instead of answering 409

#### Scenario: Several events during a run cause one follow-up run

- **WHEN** three `EVENT` triggers arrive for a connector while one of its runs is in progress
- **THEN** no second run starts while that run is in progress
- **AND** exactly one follow-up run starts when it ends

#### Scenario: A scheduled start during a run causes one follow-up run

- **WHEN** a `SCHEDULED` start arrives for a connector while a `MANUAL` run of it is in progress
- **THEN** exactly one follow-up run with trigger `SCHEDULED` starts when the manual run ends

### Requirement: Sync-run history with per-file outcomes

The agent SHALL persist one record per sync run: trigger type (`SCHEDULED`, `MANUAL`, `EVENT`, `FRESHNESS_CHECK`), status (`RUNNING`, `SUCCEEDED`, `PARTIAL`, `FAILED`), start/finish timestamps, and counters for added / updated / deleted / skipped / failed files, and one record per touched file with its source path, action, resulting object key, and a failure reason where applicable. The per-file action set SHALL be `ADDED`, `UPDATED`, `DELETED`, `SKIPPED`, `FAILED`. History SHALL be readable via the API per connector.

#### Scenario: Run outcome recorded

- **WHEN** a sync run lands two new files, updates one, and skips one disallowed type
- **THEN** the run record shows status `SUCCEEDED` with counters added=2, updated=1, skipped=1
- **AND** four per-file outcome records exist, the skipped one carrying its reason

#### Scenario: Per-file failure does not hide the rest

- **WHEN** one file in a batch fails to download and the others succeed
- **THEN** the run completes with status `PARTIAL`
- **AND** the failed file's outcome record carries the failure reason while the successful files' records show their object keys

### Requirement: Connectors land bytes and reuse the existing ingestion pipeline

A connector SHALL deliver documents by writing the source file's bytes to object storage under the tenant prefix that the `TenantPrefixResolver` port answers for the connector's tenant (markdown into the markdown folder, everything else into the documents folder, matching the upload controller's routing) and then triggering the existing bucket-scan ingestion for the affected prefix. Connectors SHALL NOT parse, chunk, or embed content themselves, and SHALL NOT write to the vector store by any route.

Before the object storage write, connector-fetched files SHALL pass the same filename sanitization and sniffed-MIME allowlist checks (`app.ingestion.upload.allowed-mime-types`) that govern manual uploads. Object keys SHALL include a sanitized source-relative path segment so distinct source files cannot collide on a shared leaf name. A connector MAY supply the object key segment for a landed file instead. The framework SHALL keep the tenant prefix and the markdown or documents folder it chooses, SHALL put the connector's segment below that folder, and SHALL refuse a segment that would leave it.

Before the ingestion run starts, the framework SHALL register each landed file in the document registry of `add-document-management-api` with the `source_type` (of the form `connector:<name>`), the `origin_uri` and the connector id that the connector supplies.

#### Scenario: Synced file flows through the existing pipeline

- **WHEN** a connector sync fetches a new PDF from the source
- **THEN** the PDF bytes are written to object storage under the tenant's documents prefix
- **AND** the existing ingestion scan indexes it into Qdrant through the standard parse path
- **AND** no chunk for that PDF was written to Qdrant by the connector itself

#### Scenario: Landed file is registered with the connector's values

- **WHEN** an `OBSIDIAN` connector lands a note and supplies `source_type` `connector:obsidian`, an `origin_uri` and its connector id
- **THEN** the document registry row for that object key carries exactly those three values
- **AND** every chunk of the indexed note carries `source_type` `connector:obsidian` and that `connector_id`

#### Scenario: Connector-chosen key segment stays inside the framework's folder

- **WHEN** a connector supplies the key segment `obsidian/<connectorId>/<hash>-note.md` for a markdown file of tenant `acme`
- **THEN** the object is written under tenant `acme`'s prefix, in its markdown folder, at that segment
- **AND** a segment holding `..` is refused and the file's outcome is `FAILED` with the reason

#### Scenario: Disallowed type is skipped before storage

- **WHEN** a connector sync encounters a source file whose sniffed MIME type is not in the allowlist
- **THEN** no object storage write and no Qdrant write occur for that file
- **AND** the file's outcome record shows `SKIPPED` with the disallowed type as reason

#### Scenario: The framework holds no vector-store handle

- **WHEN** the connector framework's interfaces and orchestrator are inspected
- **THEN** neither exposes a vector store nor an embedding client
- **AND** every chunk that exists for a connector-landed document was produced by the existing ingestion pipeline

### Requirement: Chunks of a connector document carry its connector id

The framework SHALL add the nullable column `connector_id` to the `documents` registry table with an index, SHALL set it when it registers a landed file, and SHALL add `connector_id` to every chunk of a document whose registry row has one, through every ingestion run of that document. A document without a connector SHALL carry no `connector_id` key on its chunks. Every RAG collection SHALL have a keyword payload index on `connector_id`.

#### Scenario: Connector document

- **WHEN** an `OBSIDIAN` connector lands a note and a bucket scan indexes it
- **THEN** every chunk of the note carries that connector's `connector_id`
- **AND** the registry row keeps `source_type` `connector:obsidian`

#### Scenario: Upload

- **WHEN** a file is uploaded through `POST /api/v1/ingestion/upload` and indexed
- **THEN** none of its chunks carries a `connector_id` key

#### Scenario: Payload index

- **WHEN** the agent has started
- **THEN** every RAG collection has a keyword payload index on `connector_id`

### Requirement: Deduplication for connector-landed objects uses the document registry ETag

Deduplication for a connector-landed object SHALL be the document registry ETag comparison from add-document-management-api: the bucket scan compares the stored object's ETag with `document_index_state.etag` for the target collection. A connector SHALL NOT introduce a marker or dedup store of its own. An object whose bytes are unchanged since the previous run SHALL be skipped without re-parsing, re-chunking, or re-embedding. An object whose bytes changed SHALL be re-indexed.

#### Scenario: Unchanged file is a no-op

- **WHEN** a sync re-lands a file whose bytes are identical to the object already in object storage
- **THEN** the object's ETag equals the registry ETag and re-indexing is skipped
- **AND** the Qdrant chunk count and point identifiers for that source are unchanged
- **AND** the file's outcome record shows `SKIPPED`

#### Scenario: Changed file is re-indexed

- **WHEN** a file's bytes change at the source
- **THEN** the object's ETag differs from the registry ETag and the file is re-parsed, re-chunked, and re-embedded
- **AND** the file's outcome record shows `UPDATED`

### Requirement: Sync freshness check

The agent SHALL run a scheduled check, the system task `connector-freshness-check` of `add-shared-scheduler`, that compares each enabled connector's last successful sync against its configured maximum sync age and marks a connector that has exceeded it as stale. The stale flag SHALL be returned by the connector read and list endpoints, and the time since each connector's last successful sync SHALL be exposed as a metric. A successful sync SHALL clear the flag. The check SHALL be run by exactly one agent instance through the shared scheduler so that concurrent agent instances do not act on one connector twice, and it SHALL record a run with trigger type `FRESHNESS_CHECK` only when a connector's stale state changes.

The check SHALL NOT write to object storage, SHALL NOT write to the vector store, and SHALL NOT call the source, so that it stays able to report an outage in the very machinery that failed. A `FRESHNESS_CHECK` run SHALL NOT move the connector's last successful sync timestamp, so a check can never clear the condition it exists to report.

#### Scenario: Silently stopped connector becomes visible

- **WHEN** a connector has completed no successful sync for longer than its maximum sync age
- **THEN** the connector reads as stale on the connector read and list endpoints
- **AND** its time-since-last-successful-sync metric exceeds the maximum sync age
- **AND** one run with trigger type `FRESHNESS_CHECK` is recorded for the transition

#### Scenario: The check changes no document

- **WHEN** the freshness check marks a connector stale
- **THEN** every document that connector landed still exists in object storage
- **AND** every chunk of those documents still carries its text and its metadata keys
- **AND** a caller of the owning tenant still retrieves those documents

#### Scenario: Healthy connector is never marked stale

- **WHEN** a connector completes a successful sync on its schedule and that schedule fires more often than its maximum sync age
- **THEN** the connector never reads as stale
- **AND** no `FRESHNESS_CHECK` run is recorded for it

#### Scenario: Recovery clears the flag

- **WHEN** a stale connector completes a successful sync
- **THEN** the stale flag is cleared in that run
- **AND** one `FRESHNESS_CHECK` run records the transition back

### Requirement: Deletion propagation

When a sync detects that a previously synced file was removed at the source, the agent SHALL remove the corresponding stored object and its Qdrant chunks during that run, using the single-document deletion path owned by `add-document-management-api`. The deletion SHALL be recorded as a per-file outcome with action `DELETED`.

#### Scenario: Source deletion removes stored object and chunks

- **WHEN** a file that was synced in an earlier run is deleted at the source and the next sync runs
- **THEN** the stored object for that file no longer exists
- **AND** Qdrant contains no chunks whose source metadata references it
- **AND** the run's history shows a `DELETED` outcome for that file

#### Scenario: Deletion of a never-synced file is ignored

- **WHEN** the source reports a deletion for an item the connector never landed (e.g., filtered out by type)
- **THEN** no object storage or Qdrant operation is attempted
- **AND** the run does not fail

### Requirement: The tenant of a connector and the prefix of its objects come from replaceable seams

The tenant of a connector SHALL be taken from `TenantContext.currentTenantId()` when the connector is created and SHALL be stored on its row, and every run SHALL bind the tenant on the row with `TenantContext.runAs` for the whole run, also a run that starts without a request. The object key prefix of a landed file SHALL come from a `TenantPrefixResolver` port. Its default implementation SHALL answer the empty prefix, keeping today's key layout, and SHALL exist only while no other implementation is registered. The framework SHALL NOT build a tenant key segment itself.

#### Scenario: A personal deployment lands at today's key layout

- **WHEN** `TenantContext.currentTenantId()` answers `default` and no other `TenantPrefixResolver` is registered, and a connector lands a markdown file
- **THEN** the connector row carries tenant `default`
- **AND** the object is written under the markdown folder with no tenant segment

#### Scenario: A registered prefix resolver changes the layout without a code change

- **WHEN** a deployment registers a `TenantPrefixResolver` answering `tenant/<tenantId>/` and a connector of tenant `acme` lands a file
- **THEN** the object is written under `tenant/acme/`
- **AND** no class of the framework was edited

### Requirement: Connector credentials sit behind a store port and are encrypted at rest

Connector secret material SHALL be stored only through the `ConnectorCredentialStore` port and SHALL be referenced from connector rows by an opaque handle. The framework SHALL ship a default store, used while no other implementation is registered, that encrypts each secret with AES-256-GCM under a fresh nonce, with the key read from `CONNECTOR_CREDENTIALS_KEY`, and stores the key version with each row. A create or update that carries a credential while no key is configured SHALL be refused with HTTP 503 and the code `unavailable`, and the agent SHALL start without the key when no credential is stored. A credential SHALL be resolved only for its own tenant. Secret values SHALL never appear in application logs at any log level, in sync-run records, or in API responses, including error paths such as failed authentication. Deleting a connector SHALL delete its stored credential.

#### Scenario: Secret absent from persistence and logs

- **WHEN** a connector of a type that needs a credential is created and a sync run subsequently fails authentication against the source
- **THEN** the connector table and sync-run records contain only the credentials reference, and the credential table holds only ciphertext
- **AND** the captured application logs for the whole flow contain no substring of the secret

#### Scenario: No key configured

- **WHEN** no `CONNECTOR_CREDENTIALS_KEY` is set and an `ADMIN` creates a connector that carries a credential
- **THEN** the answer is 503 with `code` `unavailable` and no row is written

#### Scenario: A personal deployment needs no key

- **WHEN** the agent starts with no `CONNECTOR_CREDENTIALS_KEY` and the only connector type in use needs no credential
- **THEN** the agent starts and such a connector is created and synced normally
