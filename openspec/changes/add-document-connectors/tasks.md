## 0. Blocking dependencies

This change cannot be completed before four sibling changes land. Each task below that cannot start until one of them ships carries a `blocked by:` marker, and the marker names the change and the artifact it must provide.

| Sibling change | What this change needs from it | Tasks blocked |
| :--- | :--- | :--- |
| `add-auth-and-identity` | the `ADMIN` role, the authenticated principal recorded on connector mutations, and the filter chain this change adds its own rule to | 6.3, 6.4 |
| `add-tenant-isolation` | the tenant MinIO prefix resolver, the tenant metadata carried into chunks, the four access-list metadata keys, the `tenant:everyone:{tenantId}` pseudo-group, and the ingestion producer default that stamps it onto a document with no source-captured list | 1.1, 2.3, 2.4, 6.3 |
| `add-document-management-api` | document metadata/status model and the single-document deletion path | 2.5, 2.8 |
| `add-usage-metering-and-quotas` | the encrypted credential store and its opaque handle | 2.2, 2.9 |

Nothing here is blocked on a directory identifier, a directory-namespaced principal, or a cross-provider identity link. This version captures no permissions from a source, so it consumes none of those. What that costs a customer is stated in the design's Named limitation section.

Work that is not blocked (the data model, the Graph client, the throttling machinery, the run-history model, the freshness check) starts immediately and compiles against the interfaces the blocked pieces will provide.

## 1. Data model and migrations

- [ ] 1.1 Add Liquibase changelog `apps/ascend-ai-agent/src/main/resources/db/changelog/02-connectors.xml` (wired into `db.changelog-master.yaml`) creating `connector`, `connector_sync_run`, `connector_sync_file_outcome`, and `connector_sync_cursor` per design D3, with tenant-scoped indexes, FK cascades from run to outcomes and connector to cursors and runs, and an index on `connector(enabled, last_successful_sync_at)` for the freshness check. Blocked by: `add-tenant-isolation` for the tenant key column type.
  verify: `./gradlew integrationTest` runs the changelog against a Testcontainers Postgres and the rollback drops all four tables cleanly; `liquibase status` reports no pending changesets after apply.
- [ ] 1.2 Create JPA entities and Spring Data repositories for the four tables under `repository/` and `model/`, with enums for connector type, run trigger (`SCHEDULED`, `MANUAL`, `FRESHNESS_CHECK`), run status (`RUNNING`, `SUCCEEDED`, `PARTIAL`, `FAILED`), and file action (`ADDED`, `UPDATED`, `DELETED`, `SKIPPED`, `FAILED`).
  verify: repository slice test persists one connector with runs, outcomes, and a cursor, then reads each back with every enum value round-tripping.
- [ ] 1.3 Add `@ConfigurationProperties` class `ConnectorProperties` (`app.connector.*`: scheduler tick, freshness-check tick, default per-file size limit, throttle budget, default cron schedule, default maximum sync age, history retention cap) with defaults in `application.yaml`.
  verify: a context test asserts every property binds and that the application fails to start when the default maximum sync age is not greater than the interval the default cron schedule fires on.
- [ ] 1.4 Enforce the configuration invariant that a connector's maximum sync age exceeds the interval its cron schedule fires on, at write time on the connector row.
  verify: repository or service test asserts a violating configuration is rejected and no row is written; a conforming one persists.
- [ ] 1.5 Test: repository slice test (Testcontainers Postgres) asserting tenant-scoped query methods return only the owning tenant's connectors, runs, outcomes, and cursors.
  verify: seeding two tenants and querying as one returns zero rows belonging to the other, for all four tables.

## 2. Connector framework and sync orchestrator

- [ ] 2.1 Define `DocumentConnector`, `ChangeSet`, `SyncCursor`, and the entry type carrying source item id, path, and content version per design D2.
  verify: a fake connector implementing the interface compiles and drives the orchestrator tests in 2.6 onwards, and the interface exposes no vector store and no embedding client.
- [ ] 2.2 Implement credential resolution: connector rows hold an opaque credentials reference, resolved through the encrypted credential store. No encryption code here. Blocked by: `add-usage-metering-and-quotas`.
  verify: test asserts the connector row persists only the reference and that the resolved secret is never assigned to a field that outlives the sync call.
- [ ] 2.3 Implement the orchestrator's landing contract per design D1: filename sanitization (`util/IngestionSecurity`), Tika-sniffed MIME allowlist check, MinIO write under the tenant prefix with a sanitized source-relative path segment in the key, then trigger of the existing bucket-scan ingestion for the affected prefix. Blocked by: `add-tenant-isolation` for the prefix resolver.
  verify: integration test asserts a landed PDF appears in Qdrant through the standard parse path, and asserts a disallowed sniffed type produces no MinIO object and no chunk.
- [ ] 2.4 Assert the company-wide visibility rule per design D18: a connector-landed document's chunks carry `acl` of exactly `["tenant:everyone:{tenantId}"]` with `acl_source` of `tenant-default`, written by the ingestion producer default rather than by any connector code. Blocked by: `add-tenant-isolation` for the producer default and the metadata keys.
  verify: integration test asserts every chunk of a landed document carries that list and that `acl_source`; an architecture test asserts no class under `service/connector/` references the principal factory, the access-list helper, or any of the four access-list metadata key constants.
- [ ] 2.5 Implement deletion propagation: map deleted source items to MinIO keys via the file-outcome and document-metadata records, invoke the single-document deletion path, record `DELETED`, and ignore deletions for never-landed items. Blocked by: `add-document-management-api`.
  verify: integration test asserts the MinIO object and the Qdrant chunks are gone, the outcome is `DELETED`, and a deletion for a never-landed item performs no storage operation and does not fail the run.
- [ ] 2.6 Implement the scheduler: `@Scheduled` tick scanning for `enabled=true` connectors with `next_run_at` due, claimed with `FOR UPDATE SKIP LOCKED`, computing the next fire time from the cron expression after each run.
  verify: Testcontainers Postgres test with two concurrent orchestrator invocations for one due connector records exactly one sync run for that tick.
- [ ] 2.7 Record the last successful sync: a run triggered `SCHEDULED` or `MANUAL` that ends `SUCCEEDED` or `PARTIAL` stamps the connector's `last_successful_sync_at`. A run ending `FAILED` leaves it untouched, as does a run that never completed, as does every `FRESHNESS_CHECK` run whatever its status.
  verify: test asserts the timestamp advances on a succeeded sync run and on a partial one, holds its prior value across a failed run and an interrupted one, and is unmoved by a `FRESHNESS_CHECK` run that completes successfully.
- [ ] 2.8 Implement sync-run history: run record with trigger, status, timings, and the five counters; per-file outcome records carrying source path, action, MinIO key, and failure reason. Prune to the configured cap per connector on run insert. Blocked by: `add-document-management-api` for the MinIO key to document-metadata mapping.
  verify: test asserts a run landing two files, updating one, and skipping one records counters added=2, updated=1, skipped=1 with a matching outcome row each; and asserts the retention cap prunes the oldest run on the insert that exceeds it.
- [ ] 2.9 Assert credential and principal hygiene across the framework: no secret material in logs at any level, and no principal identifier in run history or in any connector API response. Blocked by: `add-usage-metering-and-quotas` for the credential store.
  verify: log-capturing test across a successful sync and a failed-auth sync asserts no substring of the client secret or access token appears at any level; a separate assertion over the run-history response body asserts no principal identifier appears in it.

## 3. Deduplication

- [ ] 3.1 Confirm that connector-landed objects deduplicate through the existing `manual-ingestion:<key>:<etag>` marker with no format change and no second marker format anywhere in the connector packages.
  verify: unit test asserts the marker a connector-landed object produces is byte-identical to the marker a manual upload of the same object produces; an unchanged file is skipped with outcome `SKIPPED` and unchanged point identifiers; a content change is re-indexed with outcome `UPDATED`.

## 4. Sync freshness check

- [ ] 4.1 Implement the freshness check per design D19: a scheduled job comparing each enabled connector's `last_successful_sync_at` against its maximum sync age, setting or clearing the connector's stale flag, claimed with the same row lock as a scheduled sync, and recording a run with trigger `FRESHNESS_CHECK` only on a state transition.
  verify: integration test asserts that after simulating a sync outage longer than the maximum sync age the connector reads as stale and exactly one `FRESHNESS_CHECK` run is recorded; a second check with no further change records no additional run.
- [ ] 4.2 Assert the check changes no document and calls no source.
  verify: integration test asserts that after the check marks a connector stale, its landed MinIO objects still exist, its chunks still carry their text and all metadata keys including `acl`, a caller of the owning tenant still retrieves them, and no outbound request was issued to the source during the check.
- [ ] 4.3 Assert a healthy connector is never marked stale, and that recovery clears the flag.
  verify: integration test with a connector syncing more often than its maximum sync age asserts the flag is never set; a stale connector that then completes a successful sync has the flag cleared in that run and one transition run recorded.
- [ ] 4.4 Expose the freshness metrics: seconds since last successful sync per connector, and the count of stale connectors.
  verify: a metrics test asserts the age gauge rises while a connector is not syncing and drops on a successful sync, and that the stale count matches the number of connectors carrying the flag.

## 5. SharePoint/OneDrive connector

- [ ] 5.1 Implement the Graph auth client: client-credentials token acquisition per tenant with in-memory expiry-based caching; secrets resolved at sync time, never persisted or logged.
  verify: test with a mocked token endpoint asserts one token acquisition serves multiple calls within its lifetime, a new one is acquired after expiry, and neither the secret nor the token appears in captured logs or in the database.
- [ ] 5.2 Implement the Graph API client: site to drives resolution, drive delta requests (initial full enumeration and token-based incremental), delta-page pagination, item content download, and deserialization of the `deleted` facet.
  verify: WireMock-backed test asserts a multi-page delta is fully consumed and a `deleted` facet entry is surfaced as a deletion.
- [ ] 5.3 Implement `SharePointConnector` content behaviour: folder-path scoping applied to delta results, MIME and size filters applied from Graph item metadata before download (skip with reason, no full download), delta entries mapped to `ChangeSet` add / update / delete entries, one delta token persisted per drive.
  verify: WireMock test asserts an add, a modify, and a delete in one delta page produce a MinIO write, a MinIO overwrite, and a deletion-path invocation with correct run counters; an out-of-scope file produces no download and no outcome record; and a 2 GB item produces `SKIPPED` with a size reason and zero content bytes fetched.
- [ ] 5.4 Implement throttling compliance with one per-run budget: honour `Retry-After` on 429/503, exponential backoff with jitter otherwise, bounded per-request retries, and a per-run budget that when exhausted ends the run `PARTIAL` with the cursor advanced only through what was fully processed.
  verify: test asserts a 429 carrying `Retry-After: 7` is waited out for at least seven seconds and then retried successfully, and asserts budget exhaustion ends the run `PARTIAL` with a resumable content cursor.
- [ ] 5.5 Implement delta-token invalidation handling: on Graph 410 or a resync instruction, discard the token and re-enumerate the drive in full.
  verify: WireMock test asserts the token is discarded and a tokenless delta is issued; a file whose bytes are unchanged keeps its point identifiers and is not re-embedded; and the run's `updated` counter is zero for those files.
- [ ] 5.6 Assert the connector requests and uses content permissions only: no directory, group, or group-member application permission in the setup path, and no request issued against a directory group endpoint.
  verify: WireMock test asserts a full sync completes against a Graph mock that rejects every directory endpoint with 403, and a source scan asserts no directory endpoint path appears in the connector's request builders.
- [ ] 5.7 Implement the ungranted-site failure per design D15: a site the registration cannot read fails that site's sync with a reason naming the site rather than reporting an empty success.
  verify: WireMock test asserts a 403 on site resolution produces a run whose outcome names the site and whose status is not `SUCCEEDED`, and that no item from that site is landed.

## 6. Connector REST API

- [ ] 6.1 Create DTOs for connector create / update / read (credential fields write-only, maximum sync age and stale flag included), sync-run history, and per-file outcomes; add OpenAPI annotations consistent with `IngestionController`.
  verify: MockMvc test asserts a created connector round-trips without echoing the secret, that the read DTO exposes the stale flag and the last successful sync time, and that the generated OpenAPI document contains no schema property holding secret material.
- [ ] 6.2 Implement `ConnectorController` under `/api/v1/connectors`: create, list, get, update, disable, delete, `POST /{id}/sync` returning HTTP 409 while a run is in progress, and `GET /{id}/runs` and `GET /{id}/runs/{runId}` for history.
  verify: MockMvc test asserts each endpoint's status code and body shape, and that a trigger during an active run returns 409 with no second run started.
- [ ] 6.3 Add the filter-chain authorization rule for `/api/v1/connectors/**` requiring `ADMIN`, in `SecurityConfig` alongside the matrix `add-auth-and-identity` establishes, and scope all queries to the caller's tenant. Blocked by: `add-auth-and-identity` for the role and the filter chain, and `add-tenant-isolation` for the tenant scope.
  verify: MockMvc test asserts an unauthenticated caller receives 401 and a `USER`-only caller receives 403 on every endpoint including the sync trigger and both history reads, with no connector data, credentials reference, or source scope in the body; and asserts an ADMIN of tenant A receives none of tenant B's connectors, runs, or outcomes.
- [ ] 6.4 Assert the rule is the single visible source of truth: the connector paths appear in the filter chain configuration and no connector endpoint relies on a method-level annotation as its only authorization check. Blocked by: `add-auth-and-identity` for the filter chain.
  verify: a test over the resolved security configuration asserts `/api/v1/connectors/**` is present with an `ADMIN` requirement, and a source scan asserts no `@PreAuthorize` on `ConnectorController` stands in place of it.
- [ ] 6.5 Implement the configuration validation surface: reject a create or update whose maximum sync age is not greater than the interval its cron schedule fires on, with a message naming both values.
  verify: MockMvc test asserts HTTP 400 with both values in the response body and that no row was created or modified.
- [ ] 6.6 Implement delete semantics: remove configuration, cursors, and history; leave already-ingested documents untouched.
  verify: MockMvc plus storage test asserts the three row sets are gone and that a previously synced document's MinIO object and Qdrant chunks both survive the delete and stay retrievable for a caller of the owning tenant.
- [ ] 6.7 Add Bruno requests for the connector API under `docs/api/request/AscendAI/`, including a sync trigger and a run-history fetch.
  verify: `bru run` against a live stack returns the documented status code for each request in the folder.

## 7. Documentation and verification

- [ ] 7.1 Author `docs/CONNECTORS.md`: connector concepts, the connector landing contract, the Azure app-registration walkthrough a customer admin performs (app registration, the `Sites.Read.All` or per-site `Sites.Selected` content grant, admin consent, client secret creation, and the explicit note that no directory permission is requested), connector API usage examples, the company-wide visibility statement a customer is told plainly, the freshness numbers including the default maximum sync age, throttling and first-sync expectations for large sites, and the named follow-on connectors (Google Drive, Confluence, network share) as out of scope.
  verify: a reviewer following only the document completes an app registration whose first sync lands documents retrievable by a caller of that tenant, with no step taken from outside the document.
- [ ] 7.2 Link `docs/CONNECTORS.md` from the root `README.md` documentation map and add connector notes to root `AGENTS.md` and `apps/ascend-ai-agent/AGENTS.md`.
  verify: every link added resolves to an existing file, checked by following each one.
- [ ] 7.3 Run `./gradlew test integrationTest` and fix failures.
  verify: both tasks report BUILD SUCCESSFUL and the coverage gate passes.
- [ ] 7.4 End-to-end verification of the content path against a live stack: create a connector via Bruno, trigger a sync against mocked-or-real Graph, confirm documents appear in MinIO under the tenant prefix and chunks in Qdrant, delete a source file, re-sync, confirm removal; record outcomes in the run history endpoints.
  verify: the run-history response shows the expected action per file and the storage state matches it, checked directly in MinIO and Qdrant rather than from the response alone.
- [ ] 7.5 End-to-end verification of retrieval against a live stack: prompt as a caller of the owning tenant and confirm the synced document is retrieved, then prompt as a caller of a second tenant and confirm it is not.
  verify: the first caller's response cites the synced document and its chunks carry `acl` of `["tenant:everyone:<tenant>"]`; the second caller's response cites none of them.
- [ ] 7.6 End-to-end verification of the freshness path against a live stack: stop a connector's syncs for longer than its maximum sync age and confirm the observable outcome.
  verify: the connector reads as stale on `GET /api/v1/connectors`, the age gauge exceeds the maximum sync age, one `FRESHNESS_CHECK` run is recorded, and every document that connector landed is still retrievable by a caller of the owning tenant.
- [ ] 7.7 Update `openspec/changes/add-document-connectors/tasks.md` checkboxes as work proceeds.
  verify: `openspec status --change add-document-connectors --json` reports progress matching the work actually completed.
