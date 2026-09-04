## ADDED Requirements

### Requirement: Connector configuration is persisted per tenant

The agent SHALL persist connector configurations in PostgreSQL via a Liquibase changelog. Each configuration SHALL carry: connector type, display name, a credentials reference (an opaque handle into the encrypted credential store, never the secret material itself), a provider-specific source scope (e.g., site/drive/folder identifiers), a sync schedule (cron expression), a permission confirmation interval, an access-list maximum age, an enabled flag, and the owning tenant. All connector reads and writes SHALL be scoped to the caller's tenant. A configuration whose access-list maximum age is not greater than its permission confirmation interval SHALL be rejected at write time.

#### Scenario: Connector created and persisted

- **WHEN** an ADMIN creates a SharePoint connector with a display name, credentials reference, site/drive scope, and a cron schedule
- **THEN** a connector row exists in PostgreSQL carrying those fields and the caller's tenant
- **AND** the row contains a credentials reference, not the client secret

#### Scenario: Tenant cannot see another tenant's connectors

- **WHEN** an ADMIN of tenant A lists connectors while tenant B also has connectors configured
- **THEN** the response contains only tenant A's connectors

#### Scenario: Maximum age below the confirmation interval is rejected

- **WHEN** an ADMIN creates or updates a connector whose access-list maximum age is shorter than or equal to its permission confirmation interval
- **THEN** the request is rejected with HTTP 400 and a message naming both values
- **AND** no connector row is created or modified

### Requirement: Connector CRUD API restricted to ADMIN

The agent SHALL expose a connector management REST API under `/api/v1/connectors` supporting: create, list, get, update, disable, delete, trigger-sync-now, and get sync history. Every endpoint SHALL require the ADMIN role (as defined by `add-auth-and-identity`); callers without it SHALL receive HTTP 403. Credential material SHALL be write-only: accepted on create/update, never returned by any read endpoint. Captured principal lists SHALL NOT appear in any connector API response. Run history SHALL expose access-list versions and counters only.

#### Scenario: Non-admin rejected

- **WHEN** a caller with only the USER role sends `GET /api/v1/connectors`
- **THEN** the agent returns HTTP 403
- **AND** no connector data is returned

#### Scenario: Secrets never echoed

- **WHEN** an ADMIN creates a connector supplying a client secret and then fetches that connector
- **THEN** the response contains the connector configuration and a credentials reference
- **AND** the client secret value appears nowhere in the response body

#### Scenario: Principal lists absent from run history

- **WHEN** an ADMIN fetches the run history for a connector whose last run wrote access lists
- **THEN** each outcome carries the access-list version that was written
- **AND** no principal identifier from any captured list appears in the response body

#### Scenario: Disable stops future syncs

- **WHEN** an ADMIN disables a connector
- **THEN** subsequent scheduler ticks do not start sync runs for it
- **AND** its configuration and sync history remain readable

#### Scenario: Delete removes configuration but not ingested documents

- **WHEN** an ADMIN deletes a connector that has previously synced documents
- **THEN** its configuration, sync cursors, item access-list records, and run history are removed
- **AND** the documents it ingested remain in MinIO and Qdrant

### Requirement: Scheduled incremental sync runs per enabled connector

The agent SHALL run an incremental sync for each enabled connector according to its cron schedule. A due connector SHALL be claimed atomically (database row lock) so that concurrent agent instances execute at most one sync run per connector per due tick. Each run SHALL fetch only content changes since the connector's persisted content cursor; the content cursor SHALL advance only after the run completes, so a failed run retries the same change window.

#### Scenario: Due connector syncs once

- **WHEN** a connector's schedule comes due while two agent instances are running
- **THEN** exactly one sync run is recorded for that tick

#### Scenario: Failed run does not advance the cursor

- **WHEN** a sync run fails after fetching changes but before completing
- **THEN** the persisted content cursor still holds its pre-run value
- **AND** the next run re-fetches the same change window

### Requirement: Sync cursor carries permission confirmation state separately from content progress

The connector's persisted cursor SHALL carry a permission confirmation timestamp alongside its content cursor value, and the two SHALL advance independently. The permission confirmation timestamp SHALL advance only for items whose permissions were actually read from the source during a run, and SHALL NOT advance because a content delta returned no changes. A run in which permission capture failed for every due item SHALL leave the permission confirmation timestamp unchanged even when the content half of the run succeeded.

#### Scenario: Empty content delta does not advance permission confirmation

- **WHEN** a sync run receives a content delta containing no changes and reads no permissions because none were due
- **THEN** the content cursor advances to the new delta token
- **AND** the permission confirmation timestamp is unchanged

#### Scenario: Permission capture failure leaves confirmation unchanged

- **WHEN** a sync run lands content successfully but every permission read against the source fails
- **THEN** the run ends with status `PARTIAL`
- **AND** the permission confirmation timestamp holds its pre-run value

#### Scenario: Confirmed items advance the timestamp

- **WHEN** a sync run confirms permissions for every item due for confirmation in the connector's scope
- **THEN** the permission confirmation timestamp advances to that run's confirmation time
- **AND** each confirmed item's stored access-list synced-at value equals that time

### Requirement: Manual sync trigger

The agent SHALL allow an ADMIN to trigger an immediate sync run for a connector via the API, in either of two modes: a full sync covering content and permissions, or a permissions-only sync that confirms access lists across the connector's scope and applies payload-only updates without fetching or re-landing content. A manual trigger SHALL be rejected with HTTP 409 while a run for the same connector is already in progress.

#### Scenario: Trigger-sync-now starts a run

- **WHEN** an ADMIN calls the trigger-sync-now endpoint for an idle, enabled connector
- **THEN** a sync run starts and is recorded with trigger type `MANUAL`

#### Scenario: Permissions-only trigger refreshes lists without re-landing content

- **WHEN** an ADMIN triggers a permissions-only sync after a group's access was revoked at the source and no file content changed
- **THEN** the affected documents' chunks carry the new access list and a new access-list version
- **AND** no object in MinIO is rewritten and no chunk is re-embedded
- **AND** a caller holding only the revoked group's principal no longer retrieves those chunks

#### Scenario: Concurrent trigger rejected

- **WHEN** an ADMIN triggers a sync while a run for that connector is in progress
- **THEN** the agent returns HTTP 409
- **AND** no second run is started

### Requirement: Sync-run history with per-file outcomes

The agent SHALL persist one record per sync run: trigger type (`SCHEDULED`, `MANUAL`, `PERMISSION_SWEEP`), status (`RUNNING`, `SUCCEEDED`, `PARTIAL`, `FAILED`), start/finish timestamps, and counters for added / updated / permissions-updated / deleted / skipped / failed files, and one record per touched file with its source path, action, resulting MinIO key, the access-list version written by that outcome, and a failure reason where applicable. The per-file action set SHALL be `ADDED`, `UPDATED`, `PERMISSIONS_UPDATED`, `DELETED`, `SKIPPED`, `FAILED`. History SHALL be readable via the API per connector.

#### Scenario: Run outcome recorded

- **WHEN** a sync run lands two new files, updates one, and skips one disallowed type
- **THEN** the run record shows status `SUCCEEDED` with counters added=2, updated=1, skipped=1
- **AND** four per-file outcome records exist, the skipped one carrying its reason

#### Scenario: Permission-only run is not reported as an indexing run

- **WHEN** a run changes only the access list of three documents and indexes nothing
- **THEN** the run record shows permissions-updated=3 with added=0 and updated=0
- **AND** each of the three per-file outcomes has action `PERMISSIONS_UPDATED` and carries the new access-list version

#### Scenario: Per-file failure does not hide the rest

- **WHEN** one file in a batch fails to download and the others succeed
- **THEN** the run completes with status `PARTIAL`
- **AND** the failed file's outcome record carries the failure reason while the successful files' records show their MinIO keys

### Requirement: Connectors land bytes and an access list, and reuse the existing ingestion pipeline

A connector SHALL deliver documents by writing the source file's bytes to MinIO under the tenant prefix (markdown into the markdown folder, everything else into the documents folder, matching the upload controller's routing), together with the item's captured access list, and then triggering the existing bucket-scan ingestion for the affected prefix so that every chunk produced from that item carries the `acl`, `acl_source`, `acl_version`, and `acl_synced_at` metadata keys defined by `add-tenant-isolation`. Connectors SHALL NOT parse, chunk, or embed content themselves.

Connectors SHALL NOT write to the vector store directly, with one carve-out: the payload-only access-list update path defined below MAY set exactly the four access-list metadata keys on points that already exist for a given source. That path SHALL NOT create points, SHALL NOT delete points, SHALL NOT alter any other payload key, SHALL NOT trigger embedding, and SHALL carry the same tenant predicate as every other vector-store operation.

Before the MinIO write, connector-fetched files SHALL pass the same filename sanitization and sniffed-MIME allowlist checks (`app.ingestion.upload.allowed-mime-types`) that govern manual uploads; object keys SHALL include a sanitized source-relative path segment so distinct source files cannot collide on a shared leaf name.

#### Scenario: Synced file flows through the existing pipeline carrying its access list

- **WHEN** a connector sync fetches a new PDF from the source and captures its access list
- **THEN** the PDF bytes are written to MinIO under the tenant's documents prefix
- **AND** the existing ingestion scan indexes it into Qdrant through the standard parse path
- **AND** every chunk written for that PDF carries the captured `acl`, an `acl_source` naming the connector, the `acl_version` for that list, and an `acl_synced_at` equal to the capture time

#### Scenario: Disallowed type is skipped before storage

- **WHEN** a connector sync encounters a source file whose sniffed MIME type is not in the allowlist
- **THEN** no MinIO write and no Qdrant write occur for that file
- **AND** the file's outcome record shows `SKIPPED` with the disallowed type as reason

#### Scenario: Bytes are never landed without an access list

- **WHEN** access-list capture fails for an item whose bytes were already downloaded during the run
- **THEN** ingestion is not triggered for that item and no chunk for it exists in Qdrant
- **AND** the item's outcome record shows `FAILED` with the capture reason

#### Scenario: Payload-only path cannot alter anything but the access-list keys

- **WHEN** a payload-only access-list update runs against a document whose chunks carry `source`, `type`, `title`, and `tenant_id`
- **THEN** those four keys hold their pre-update values on every chunk of that document
- **AND** the point identifiers for that document are unchanged
- **AND** the chunk count for that document is unchanged

#### Scenario: Unchanged file with an unchanged access list is a no-op

- **WHEN** a sync re-lands a file whose bytes are identical to the object already in MinIO and whose captured access list produces the same access-list version as the stored one
- **THEN** the deduplication key matches and re-indexing is skipped
- **AND** the Qdrant chunk count for that source is unchanged
- **AND** the file's outcome record shows `SKIPPED`

### Requirement: Access-list capture for every in-scope item

For every item it lands, a connector SHALL capture the set of principals permitted to read that item and SHALL express them in the `namespace:type:id` principal format owned by `add-auth-and-identity`, produced through that change's typed factory. The captured list SHALL be sorted and SHALL name groups only. A permission granted to an individual person SHALL NOT be expanded into the list.

Capture SHALL read the item's effective permissions from the source. It SHALL NOT infer permissions from the content change feed, and it SHALL NOT treat an item's absence from that feed as evidence that its permissions are unchanged.

A capture that fails, returns a permission collection the connector cannot interpret, or returns a permission entry naming an identity the connector cannot map into a known principal namespace SHALL fail that item with outcome `FAILED` and a capture reason. An empty access list that the source genuinely reported SHALL be written as an empty list with outcome `ADDED` or `PERMISSIONS_UPDATED`, and SHALL NOT be recorded as a capture failure.

#### Scenario: Access list captured and written on first sync

- **WHEN** a connector performs its first sync of a folder shared with two groups
- **THEN** every chunk of every document in that folder carries exactly those two group principals in `acl`
- **AND** each principal matches the `namespace:type:id` format

#### Scenario: Permissions are read from the source, not from the change feed

- **WHEN** an item's sharing changes at the source and the source's content change feed does not report that item as changed
- **THEN** the next run in which that item's confirmation is due reads its permissions from the source
- **AND** the item's outcome is `PERMISSIONS_UPDATED` with the new access-list version

#### Scenario: Unmappable identity fails the item

- **WHEN** an item's permission collection contains an entry naming an identity the connector cannot map into a known principal namespace
- **THEN** the item's outcome is `FAILED` with a capture reason naming the unmappable entry class
- **AND** no chunk for that item carries a partial access list

#### Scenario: Genuinely empty list is not a failure

- **WHEN** the source reports that no group may read an item
- **THEN** the item's chunks carry an empty `acl` and the run records the item as succeeded
- **AND** the outcome is not `FAILED`

### Requirement: Container-level permission inheritance during capture

Capture SHALL read permissions at container level and apply the container's list to the items that inherit it, issuing a per-item permission read only for an item the source marks as carrying permissions of its own and for an item whose permission confirmation is due. Each stored item access-list record SHALL name the container its list was inherited from, or record that the list is the item's own. A change to a container's permissions SHALL invalidate every item recorded as inheriting from it, and each such item SHALL receive a payload-only access-list update in that run.

#### Scenario: First full enumeration does not read permissions per item

- **WHEN** a connector performs its first full enumeration of a drive containing one folder and 500 inheriting documents
- **THEN** the number of permission reads issued against the source is bounded by the number of containers plus the number of uniquely-shared items, and does not scale with the 500 inheriting documents
- **AND** every one of the 500 documents' chunks carries the folder's captured access list

#### Scenario: Uniquely-shared item is read individually

- **WHEN** an item's permission collection contains an entry the source does not mark as inherited
- **THEN** that item's permissions are read individually
- **AND** its stored access-list record marks the list as the item's own rather than inherited

#### Scenario: Container revocation fans out to inheriting items

- **WHEN** a group's access to a folder is revoked at the source and no file content changes
- **THEN** every document recorded as inheriting from that folder receives a payload-only access-list update in the next run
- **AND** each of those documents' outcomes is `PERMISSIONS_UPDATED`
- **AND** no document in that folder is re-embedded

#### Scenario: Item that stops inheriting is corrected within one confirmation interval

- **WHEN** a unique permission is set on a previously inheriting item and its container's permissions do not change
- **THEN** the item is read individually on the first run after its confirmation becomes due
- **AND** its chunks carry the item's own access list rather than the container's

### Requirement: Deduplication key pairs content version with access-list version

The ingestion deduplication marker for a connector-landed object SHALL be keyed on the pair of content version and access-list version, so that a change to either produces a distinct key. The access-list version SHALL be a stable hash of the sorted principal list, unchanged when the source returns the same permitted set in a different order, and different when and only when the effective permitted set changed.

#### Scenario: Permission-only change is not deduplicated away

- **WHEN** a sync re-lands a file whose bytes are unchanged but whose captured access list differs from the stored one
- **THEN** the deduplication key differs from the stored key and the item is processed
- **AND** the item's outcome is `PERMISSIONS_UPDATED`

#### Scenario: Reordered principal list is not a change

- **WHEN** the source returns the same permitted set for an item in a different order than the previous run
- **THEN** the computed access-list version equals the stored one
- **AND** the item's outcome is `SKIPPED` with no payload write

#### Scenario: Content change with unchanged permissions still re-indexes

- **WHEN** a file's bytes change and its access list does not
- **THEN** the item is re-parsed, re-chunked, and re-embedded
- **AND** its chunks carry the same access list and the same access-list version as before

### Requirement: Four-way sync branch with a payload-only permission update path

For every item it touches, a sync run SHALL compare both the content version and the access-list version against the stored values and take exactly one of four actions: no-op when neither changed; a payload-only access-list update when only the access list changed; a full re-index carrying the current access list forward when only the content changed; and a full re-index with the new access list when both changed. The payload-only path SHALL set only the four access-list metadata keys on the existing points for that source, and SHALL NOT re-parse, re-chunk, or re-embed.

#### Scenario: Permission-only change takes the payload-only path

- **WHEN** an item's access list changes and its bytes do not
- **THEN** the item's chunks carry the new `acl`, `acl_version`, and `acl_synced_at`
- **AND** the point identifiers for that item are unchanged, proving no re-embed occurred
- **AND** the item's outcome is `PERMISSIONS_UPDATED`

#### Scenario: Content change carries the current access list forward

- **WHEN** an item's bytes change and its access list does not
- **THEN** the item is re-indexed and its new chunks carry the stored access list and its unchanged version
- **AND** the item's outcome is `UPDATED`

#### Scenario: Both changed is a single re-index with the new list

- **WHEN** an item's bytes and its access list both change in the same window
- **THEN** the item is re-indexed once and its new chunks carry the new access list
- **AND** the item's outcome is `UPDATED`, not `PERMISSIONS_UPDATED`

#### Scenario: Neither changed writes nothing

- **WHEN** an item's content version and access-list version both match the stored values
- **THEN** no MinIO write, no payload write, and no embedding call occurs for that item

### Requirement: An access list exceeding the cap is a capture failure

A captured access list containing more than 64 principals SHALL fail that item with outcome `FAILED` and a cap reason. The list SHALL NOT be truncated, no chunk SHALL be written carrying a shortened list, and no chunk for that item SHALL become retrievable. The cap check SHALL run before the MinIO write and before the deduplication key is recorded.

#### Scenario: Over-cap list fails the item loudly

- **WHEN** a connector captures a permission list of 65 principals for an in-scope file
- **THEN** the file's outcome is `FAILED` with a cap reason naming the file
- **AND** no chunk for that file exists in Qdrant
- **AND** no deduplication marker is recorded for that file

#### Scenario: Over-cap list on an already-indexed document does not truncate it

- **WHEN** a previously indexed document's access list grows past the cap at the source
- **THEN** the item's outcome is `FAILED` with a cap reason
- **AND** the document's existing chunks are not rewritten with a truncated list

#### Scenario: Exactly at the cap succeeds

- **WHEN** a connector captures a permission list of exactly 64 principals
- **THEN** the item is landed and its chunks carry all 64 principals

### Requirement: Access-list staleness sweep

The agent SHALL run a scheduled sweep that finds items whose stored access-list synced-at timestamp is older than the connector's configured access-list maximum age and empties the `acl` on those items' chunks through the payload-only update path, recording each as a sync outcome under a run with trigger type `PERMISSION_SWEEP`. The sweep SHALL be claimed with the same database row lock as a scheduled sync so that concurrent agent instances do not sweep one connector twice.

#### Scenario: Silent capture outage becomes visible degradation

- **WHEN** permission capture for a connector has failed continuously for longer than the connector's access-list maximum age
- **THEN** the affected items' chunks carry an empty `acl`
- **AND** a run with trigger type `PERMISSION_SWEEP` records a `PERMISSIONS_UPDATED` outcome per emptied item
- **AND** no caller retrieves those chunks

#### Scenario: Healthy connector is never swept

- **WHEN** a connector confirms permissions on its configured interval and that interval is shorter than its access-list maximum age
- **THEN** the sweep empties no access list for that connector
- **AND** the sweep run records zero emptied items

#### Scenario: Sweep does not delete content

- **WHEN** the sweep empties the access list of a document
- **THEN** the document's MinIO object still exists
- **AND** the document's chunks still exist in Qdrant with their text and their other metadata keys intact

### Requirement: Deletion propagation

When a sync detects that a previously synced file was removed at the source, the agent SHALL remove the corresponding MinIO object and its Qdrant chunks during that run, using the single-document deletion path owned by `add-document-management-api`, and SHALL remove the item's stored access-list record in the same step. The deletion SHALL be recorded as a per-file outcome with action `DELETED`.

#### Scenario: Source deletion removes MinIO object and chunks

- **WHEN** a file that was synced in an earlier run is deleted at the source and the next sync runs
- **THEN** the MinIO object for that file no longer exists
- **AND** Qdrant contains no chunks whose source metadata references it
- **AND** the run's history shows a `DELETED` outcome for that file

#### Scenario: Deleted item leaves no access-list record behind

- **WHEN** a previously synced file is deleted at the source and propagated
- **THEN** no stored item access-list record for that item remains
- **AND** the next staleness sweep reports no aged item for it

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
