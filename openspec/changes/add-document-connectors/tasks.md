## 0. Blocking dependencies

This change cannot be completed before four sibling changes land. Each task below that cannot start until one of them ships carries a `blocked by:` marker, and the marker names the change and the artifact it must provide.

| Sibling change | What this change needs from it | Tasks blocked |
| :--- | :--- | :--- |
| `add-auth-and-identity` | ADMIN role, authenticated principal on mutations, the `namespace:type:id` principal format and its typed factory, the `oid` directory identifier that Graph permission entries map onto, and the cross-provider identity link for split-provider tenants | 2.1, 2.4, 8.1, 8.3, 8.5, 9.3 |
| `add-tenant-isolation` | the `acl` / `acl_source` / `acl_version` / `acl_synced_at` metadata keys, the mandatory keyword payload index on `acl`, the tenant MinIO prefix resolver, the tenant predicate carried into every vector-store operation, and the `tenant:everyone:{tenantId}` pseudo-group | 1.1, 2.2, 3.1, 3.2, 5.3, 6.4, 9.3 |
| `add-document-management-api` | document metadata/status model and the single-document deletion path | 5.6, 5.9 |
| `add-usage-metering-and-quotas` | the encrypted credential store and its opaque handle | 5.2, 5.10 |

Work that is not blocked (the data model, the access-list value type and its hashing, the Graph client, the throttling machinery, the run-history model) starts immediately and compiles against the interfaces the blocked pieces will provide.

## 1. Data model and migrations

- [ ] 1.1 Add Liquibase changelog `AscendAgent/src/main/resources/db/changelog/02-connectors.xml` (wired into `db.changelog-master.yaml`) creating `connector`, `connector_sync_run`, `connector_sync_file_outcome`, `connector_sync_cursor`, and `connector_item_acl` per design D3, with tenant-scoped indexes, FK cascades from run to outcomes and connector to cursors / runs / item access-list rows, an index on `connector_item_acl(acl_synced_at)` for the staleness sweep, and an index on `connector_item_acl(container_id)` for the inheritance fan-out. Blocked by: `add-tenant-isolation` for the tenant key column type.
  verify: `./gradlew integrationTest` runs the changelog against a Testcontainers Postgres and the rollback drops all five tables cleanly; `liquibase status` reports no pending changesets after apply.
- [ ] 1.2 Create JPA entities and Spring Data repositories for the five tables under `repository/` and `model/`, with enums for connector type, run trigger (`SCHEDULED`, `MANUAL`, `PERMISSION_SWEEP`), run status, and file action (`ADDED`, `UPDATED`, `PERMISSIONS_UPDATED`, `DELETED`, `SKIPPED`, `FAILED`).
  verify: repository slice test persists one connector with runs, outcomes, a cursor carrying both content and permission state, and item access-list rows, then reads each back with every enum value round-tripping.
- [ ] 1.3 Add `@ConfigurationProperties` class `ConnectorProperties` (`app.connector.*`: scheduler tick, default per-file size limit, content throttle budget, permission throttle budget, default permission confirmation interval, default access-list maximum age, access-list principal cap, history retention cap) with defaults in `application.yaml`.
  verify: a context test asserts every property binds and that the application fails to start when the default access-list maximum age is not greater than the default confirmation interval.
- [ ] 1.4 Enforce the configuration invariant that a connector's access-list maximum age exceeds its permission confirmation interval, at write time on the connector row.
  verify: repository or service test asserts a violating configuration is rejected and no row is written; a conforming one persists.
- [ ] 1.5 Test: repository slice test (Testcontainers Postgres) asserting tenant-scoped query methods return only the owning tenant's connectors, runs, outcomes, cursors, and item access-list rows.
  verify: seeding two tenants and querying as one returns zero rows belonging to the other, for all five tables.

## 2. Access-list core (nothing that writes an access list may start before this section is done)

- [ ] 2.1 Define the `AccessList` value type in `service/connector/acl/`: an immutable sorted set of principals, the `acl_source` producer name, and the capture instant. Principals are produced only through the typed factory from `add-auth-and-identity`; this package never concatenates a principal string. Blocked by: `add-auth-and-identity` for the factory.
  verify: unit test asserts construction from an unsorted input yields a sorted list, that construction from a raw string bypassing the factory does not compile, and that the type is immutable (no setter, defensive copy on construction).
- [ ] 2.2 Implement the access-list version hash per design D10: a stable hash over the canonical form (principals sorted lexicographically, joined with a separator the principal format cannot contain). Blocked by: `add-tenant-isolation` for the `acl_version` key name.
  verify: unit test asserts the same permitted set in three different input orders produces one identical version; adding a principal produces a different version; removing one produces a different version; and two distinct lists never collide across a generated corpus of at least 10,000 lists.
- [ ] 2.3 Implement the principal cap check per design D13: a list of more than 64 principals is a capture failure carrying a cap reason, never a truncation. The check runs before any MinIO write and before any deduplication marker is recorded.
  verify: unit test asserts a 65-principal list raises a capture failure naming the cap, a 64-principal list is accepted whole, and no code path in the package returns a list shorter than its input.
- [ ] 2.4 Define the `AccessListSource` interface (per-item capture and per-container capture) and the `CaptureFailure` reason taxonomy: source refused, collection unattributable, entry unmappable, personal grant only, link share, cap exceeded, missing directory grant. Blocked by: `add-auth-and-identity` for the principal namespace set that "unmappable" is defined against.
  verify: unit test over a fake `AccessListSource` asserts each reason is distinguishable on the outcome record and that a genuinely empty list is returned as an empty `AccessList` rather than as any failure reason.
- [ ] 2.5 Implement the framework rule that an empty access list and a failed capture are different outcomes: an empty list lands the item and writes an empty `acl`; a failure fails the item and lands nothing.
  verify: orchestrator-level unit test asserts the empty-list item produces chunks with an empty `acl` and outcome `ADDED`, while the failed-capture item produces zero chunks and outcome `FAILED`.

## 3. Payload-only access-list update path

- [ ] 3.1 Implement the payload-only updater in `service/connector/acl/` using the native Qdrant client's `setPayload` against the points already carrying a given source, setting exactly `acl`, `acl_source`, `acl_version`, and `acl_synced_at`, and carrying the tenant predicate. Blocked by: `add-tenant-isolation` for the tenant predicate and the metadata key names.
  verify: integration test against a real Qdrant asserts that after an update the four keys hold the new values, that `source`, `type`, `title`, and `tenant_id` hold their pre-update values, that the point identifiers are unchanged, and that the chunk count is unchanged.
- [ ] 3.2 Prove the updater cannot create, delete, or re-embed a point, and cannot reach across tenants. Blocked by: `add-tenant-isolation` for the tenant predicate.
  verify: integration test asserts an update naming a source that has no points writes nothing and creates nothing; asserts no embedding client call is made during an update (verified against a recording embedding stub with a zero-invocation assertion); and asserts an update issued under tenant A leaves tenant B's identically-named source untouched.
- [ ] 3.3 Document the carve-out to the no-direct-vector-store-writes rule where the rule is stated in code, so the exception is discoverable from the framework interface rather than only from the spec.
  verify: the `DocumentConnector` interface and the orchestrator expose no vector-store handle, and an architecture test asserts the Qdrant client is referenced from exactly one package outside the existing ingestion code.

## 4. Deduplication key

- [ ] 4.1 Extend the ingestion deduplication marker for connector-landed objects to `manual-ingestion:<key>:<contentVersion>:<aclVersion>` per design D10, leaving the marker format for objects landed by the manual upload paths unchanged.
  verify: unit test asserts a permission-only change produces a different key and is processed; a reordered principal list produces the same key and is skipped; a content change with an unchanged list produces a different key; and the manual upload path's marker string is byte-identical to today.

## 5. Connector framework and sync orchestrator

- [ ] 5.1 Define `DocumentConnector`, `ChangeSet`, `SyncCursor`, and the entry type carrying source item id, path, content version, and captured `AccessList` per design D2.
  verify: a fake connector implementing the interface compiles and drives the orchestrator tests in 5.7 onwards without any access to a vector store or an embedding client.
- [ ] 5.2 Implement credential resolution: connector rows hold an opaque credentials reference, resolved through the encrypted credential store. No encryption code here. Blocked by: `add-usage-metering-and-quotas`.
  verify: test asserts the connector row persists only the reference and that the resolved secret is never assigned to a field that outlives the sync call.
- [ ] 5.3 Implement the orchestrator's landing contract per design D1: filename sanitization (`util/IngestionSecurity`), Tika-sniffed MIME allowlist check, MinIO write under the tenant prefix with a sanitized source-relative path segment in the key, attachment of the captured access list to the chunk metadata, then trigger of the existing bucket-scan ingestion for the affected prefix. Blocked by: `add-tenant-isolation` for the prefix resolver and the metadata keys.
  verify: integration test asserts a landed PDF's chunks in Qdrant carry the captured `acl`, an `acl_source` naming the connector, the matching `acl_version`, and an `acl_synced_at` equal to the capture instant; and asserts a disallowed sniffed type produces no MinIO object and no chunk.
- [ ] 5.4 Implement the rule that bytes are never indexed without an access list: an item whose capture failed does not trigger ingestion even when its bytes were already downloaded in that run.
  verify: integration test asserts that after a run in which capture failed for a downloaded item, Qdrant holds zero chunks for that source and the outcome is `FAILED` with the capture reason.
- [ ] 5.5 Implement the four-way branch per design D11, dispatching to no-op, payload-only update, re-index carrying the current list forward, or re-index with the new list.
  verify: orchestrator test drives all four combinations of content-changed and list-changed and asserts, for each, the outcome action, whether point identifiers changed, and whether the embedding stub was invoked.
- [ ] 5.6 Implement deletion propagation: map deleted source items to MinIO keys via the item access-list and document-metadata records, invoke the single-document deletion path, remove the item's access-list record in the same step, record `DELETED`, and ignore deletions for never-landed items. Blocked by: `add-document-management-api`.
  verify: integration test asserts the MinIO object and the Qdrant chunks are gone, no `connector_item_acl` row remains for the item, the outcome is `DELETED`, and a deletion for a never-landed item performs no storage operation and does not fail the run.
- [ ] 5.7 Implement the scheduler: `@Scheduled` tick scanning for `enabled=true` connectors with `next_run_at` due, claimed with `FOR UPDATE SKIP LOCKED`, computing the next fire time from the cron expression after each run.
  verify: Testcontainers Postgres test with two concurrent orchestrator invocations for one due connector records exactly one sync run for that tick.
- [ ] 5.8 Implement permission confirmation state on the cursor per design D12: `permissions_confirmed_through` advances only for items whose permissions were actually read, independently of the content cursor.
  verify: test asserts an empty content delta advances the content cursor and leaves the permission timestamp unchanged; a run whose every permission read failed leaves the permission timestamp unchanged and ends `PARTIAL`; a run confirming all due items advances it to the confirmation time.
- [ ] 5.9 Implement sync-run history: run record with trigger, status, timings, and the six counters; per-file outcome records carrying source path, action, MinIO key, the `acl_version` written, and failure reason. Prune to the configured cap per connector on run insert. Blocked by: `add-document-management-api` for the MinIO key to document-metadata mapping.
  verify: test asserts a run landing two files, updating one, changing permissions on three, and skipping one records counters added=2, updated=1, permissions-updated=3, skipped=1 with a matching outcome row each; and asserts the retention cap prunes the oldest run on the insert that exceeds it.
- [ ] 5.10 Assert credential and access-list hygiene across the framework: no secret material in logs at any level, and no captured principal list in run history or in any connector API response. Blocked by: `add-usage-metering-and-quotas` for the credential store.
  verify: log-capturing test across a successful sync and a failed-auth sync asserts no substring of the client secret or access token appears at any level; a separate assertion over the run-history response body asserts no principal identifier from the captured list appears in it.

## 6. Staleness sweep and immediate resync

- [ ] 6.1 Implement the sweep: a scheduled job scanning `connector_item_acl` for rows older than the connector's access-list maximum age, emptying the `acl` on those items' chunks through the payload-only path, recording each under a run with trigger `PERMISSION_SWEEP`, claimed with the same row lock as a scheduled sync.
  verify: integration test asserts that after simulating a capture outage longer than the maximum age, the affected chunks carry an empty `acl`, the sweep run records one `PERMISSIONS_UPDATED` outcome per emptied item, the MinIO objects still exist, and the chunks still carry their text and their other metadata keys.
- [ ] 6.2 Assert the sweep never touches a healthy connector.
  verify: integration test with a connector confirming on an interval shorter than its maximum age asserts the sweep run empties zero access lists.
- [ ] 6.3 Implement the permissions-only mode of the trigger-sync-now endpoint: confirm permissions across the connector's scope now, apply payload-only updates, fetch and land no content.
  verify: integration test asserts that after a revocation at a fake source with no content change, the permissions-only trigger leaves every MinIO object unrewritten, leaves every point identifier unchanged, and writes the new `acl` and `acl_version` onto the affected chunks.
- [ ] 6.4 Expose the access-list age metric from `acl_synced_at` and the payload-only update counter per run, per the observability table in `docs/architecture/permission-aware-retrieval.md`. Blocked by: `add-tenant-isolation` for the metadata key.
  verify: a metrics test asserts the maximum access-list age is reported and rises when capture is stopped, and that the payload-only update counter is non-zero on a run that changed permissions and zero on a run that did not.

## 7. SharePoint/OneDrive connector: content

- [ ] 7.1 Implement the Graph auth client: client-credentials token acquisition per tenant with in-memory expiry-based caching; secrets resolved at sync time, never persisted or logged.
  verify: test with a mocked token endpoint asserts one token acquisition serves multiple calls within its lifetime, a new one is acquired after expiry, and neither the secret nor the token appears in captured logs or in the database.
- [ ] 7.2 Implement the Graph API client: site to drives resolution, drive delta requests (initial full enumeration and token-based incremental), delta-page pagination, item content download, and deserialization of the `deleted` facet and the `inheritedFrom` marker on permission entries.
  verify: WireMock-backed test asserts a multi-page delta is fully consumed, a `deleted` facet entry is surfaced as a deletion, and a permission entry carrying `inheritedFrom` is distinguishable from one that does not.
- [ ] 7.3 Implement `SharePointConnector` content behaviour: folder-path scoping applied to delta results, MIME and size filters applied from Graph item metadata before download (skip with reason, no full download, no permission read spent), delta entries mapped to `ChangeSet` add / update / delete entries, one delta token persisted per drive.
  verify: WireMock test asserts an add, a modify, and a delete in one delta page produce a MinIO write, a MinIO overwrite, and a deletion-path invocation with correct run counters; an out-of-scope file produces no download and no outcome record; and a 2 GB item produces `SKIPPED` with a size reason and zero content bytes fetched.
- [ ] 7.4 Implement throttling compliance with separate content and permission budgets: honour `Retry-After` on 429/503, exponential backoff with jitter otherwise, bounded per-request retries, and per-run budgets that when exhausted end the run `PARTIAL` with each cursor advanced only through what was fully processed.
  verify: test asserts a 429 carrying `Retry-After: 7` is waited out for at least seven seconds and then retried successfully; asserts content-budget exhaustion ends the run `PARTIAL` with a resumable content cursor; and asserts permission-budget exhaustion ends the run `PARTIAL` while items landed in that run still carry captured access lists.
- [ ] 7.5 Implement delta-token invalidation handling: on Graph 410 or a resync instruction, discard the token and re-enumerate the drive in full.
  verify: WireMock test asserts the token is discarded and a tokenless delta is issued; a file whose bytes and access list are both unchanged keeps its point identifiers and is not re-embedded; and the run's `updated` counter is zero for those files.

## 8. SharePoint/OneDrive connector: access-list capture

- [ ] 8.1 Implement the Graph permission reader against `GET /drives/{drive-id}/items/{item-id}/permissions` and the equivalent container call, returning the effective sharing collection including inherited entries. Blocked by: `add-auth-and-identity` for the `oid` identifier that entries are compared against.
  verify: WireMock test asserts the reader surfaces inherited and non-inherited entries distinctly and that the reader is never invoked for an item filtered out by type or size.
- [ ] 8.2 Implement container-first capture per design D9: read the drive root and each in-scope folder, apply the container list to inheriting items, record the container each item inherited from, and issue a per-item read only for an item carrying a non-inherited entry or whose confirmation is due.
  verify: WireMock test over one folder and 500 inheriting documents asserts the number of permission requests issued is bounded by containers plus uniquely-shared items and does not scale with the 500, while all 500 documents' chunks carry the folder's list.
- [ ] 8.3 Implement principal mapping per design D16: a Graph group entry becomes `entra:group:<directory object id>` through the typed factory, an individual-user entry is not expanded, and a sharing link, an application grant, or an unresolvable site-local group fails capture for that item with a reason naming the entry class. Blocked by: `add-auth-and-identity` for the factory and the namespace set.
  verify: WireMock test asserts a group-shared item's `acl` holds the group's object id and no display name appears in chunk metadata; a user-only-shared item writes no personal principal and records the personal-grant reason; and a link-shared item's outcome is `FAILED` with no partial list written.
- [ ] 8.4 Implement the insufficient-grant detection per design D15: an empty or unattributable permission collection on an item whose content downloaded successfully is a capture failure, not an empty list, and a missing directory grant is reported with its own reason.
  verify: WireMock test asserts an item returning an empty permission collection alongside a successful content download yields `FAILED` with a capture reason and zero chunks; and asserts that with the directory grant simulated absent, every in-scope item fails capture with the missing-directory-grant reason and nothing is landed.
- [ ] 8.5 Implement the container-revocation fan-out and the stopped-inheriting correction: a container permission change invalidates every item recorded as inheriting from it and each receives a payload-only update in that run; an item that acquired a unique permission is read individually on the first run after its confirmation is due. Blocked by: `add-auth-and-identity` for the principal factory used to re-capture.
  verify: integration test asserts a folder revocation with no content change produces one `PERMISSIONS_UPDATED` outcome per inheriting document with unchanged point identifiers and zero embedding calls; and asserts an item given a unique permission is read individually within one confirmation interval and its chunks then carry its own list rather than the folder's.
- [ ] 8.6 Implement the full re-enumeration semantics for permissions: a re-enumeration confirms permissions for the items it covers and applies payload-only updates to items whose sharing moved while their bytes did not.
  verify: WireMock test asserts that after a 410-triggered re-enumeration, a file revoked during the outage carries the new list with unchanged point identifiers, its outcome is `PERMISSIONS_UPDATED`, and the permission confirmation timestamp advanced.

## 9. Connector REST API

- [ ] 9.1 Create DTOs for connector create / update / read (credential fields write-only, confirmation interval and maximum age included), sync-run history, and per-file outcomes carrying the written `acl_version` and never a principal list; add OpenAPI annotations consistent with `IngestionController`.
  verify: MockMvc test asserts a created connector round-trips without echoing the secret, that the outcome DTO exposes `acl_version` and no principal field, and that the generated OpenAPI document contains no schema property holding secret material.
- [ ] 9.2 Implement `ConnectorController` under `/api/v1/connectors`: create, list, get, update, disable, delete, `POST /{id}/sync` accepting a full or permissions-only mode and returning HTTP 409 while a run is in progress, and `GET /{id}/runs` and `GET /{id}/runs/{runId}` for history.
  verify: MockMvc test asserts each endpoint's status code and body shape, that a permissions-only trigger records a run whose counters show no content activity, and that a trigger during an active run returns 409 with no second run started.
- [ ] 9.3 Guard every endpoint with the ADMIN role and scope all queries to the caller's tenant. Blocked by: `add-auth-and-identity` for the role and `add-tenant-isolation` for the tenant scope.
  verify: MockMvc test asserts the USER role receives 403 on every endpoint with no connector data in the body, and that an ADMIN of tenant A receives none of tenant B's connectors, runs, or outcomes.
- [ ] 9.4 Implement the configuration validation surface: reject a create or update whose access-list maximum age is not greater than its permission confirmation interval, with a message naming both values.
  verify: MockMvc test asserts HTTP 400 with both values in the response body and that no row was created or modified.
- [ ] 9.5 Implement delete semantics: remove configuration, cursors, item access-list records, and history; leave already-ingested documents untouched.
  verify: MockMvc plus storage test asserts the four row sets are gone and that a previously synced document's MinIO object and Qdrant chunks both survive the delete.
- [ ] 9.6 Add Bruno requests for the connector API under `docs/api/request/AscendAI/`, including a permissions-only sync trigger and a run-history fetch.
  verify: `bru run` against a live stack returns the documented status code for each request in the folder.

## 10. Documentation and verification

- [ ] 10.1 Author `docs/CONNECTORS.md`: connector concepts, the connector landing contract in both its halves, the full Azure app-registration walkthrough a customer admin performs (app registration, the `Sites.Read.All` or per-site `Sites.Selected` content grant, the `GroupMember.Read.All` directory grant, admin consent, client secret creation), connector API usage examples, the staleness table stating the confirmation interval as the revocation latency a customer is told, the access-list cap and what a capture failure looks like in run history, throttling and first-sync expectations for large sites, and the named follow-on connectors (Google Drive, Confluence, network share) as out of scope.
  verify: a reviewer following only the document completes an app registration whose first sync lands documents carrying non-empty access lists, with no step taken from outside the document.
- [ ] 10.2 Link `docs/CONNECTORS.md` from the root `README.md` documentation map and add connector notes to root `AGENTS.md` and `AscendAgent/AGENTS.md`.
  verify: every link added resolves to an existing file, checked by following each one.
- [ ] 10.3 Run `./gradlew test integrationTest` and fix failures.
  verify: both tasks report BUILD SUCCESSFUL and the coverage gate passes.
- [ ] 10.4 End-to-end verification of the content path against a live stack: create a connector via Bruno, trigger a sync against mocked-or-real Graph, confirm documents appear in MinIO under the tenant prefix and chunks in Qdrant, delete a source file, re-sync, confirm removal; record outcomes in the run history endpoints.
  verify: the run-history response shows the expected action per file and the storage state matches it, checked directly in MinIO and Qdrant rather than from the response alone.
- [ ] 10.5 End-to-end verification of the permission path against a live stack: revoke a group's access to a synced file without editing it, trigger a permissions-only sync, and confirm the observable outcome.
  verify: the file's chunks carry a new `acl_version` with unchanged point identifiers, the run history shows `PERMISSIONS_UPDATED` for that file, and a caller holding only the revoked group's principal no longer retrieves it while a caller holding a retained principal still does.
- [ ] 10.6 End-to-end verification of the failure paths against a live stack: an item whose permission list exceeds the cap, and a simulated capture outage longer than the maximum age.
  verify: the capped item's run outcome is `FAILED` with a cap reason and Qdrant holds zero chunks for it; and after the outage the swept documents' chunks carry an empty `acl`, the sweep run is recorded with trigger `PERMISSION_SWEEP`, and no caller retrieves them.
- [ ] 10.7 Update `openspec/changes/add-document-connectors/tasks.md` checkboxes as work proceeds.
  verify: `openspec status --change add-document-connectors --json` reports progress matching the work actually completed.
