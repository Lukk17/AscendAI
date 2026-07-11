## 1. Data model and migrations

- [ ] 1.1 Add Liquibase changelog `AscendAgent/src/main/resources/db/changelog/02-connectors.xml` (wired into `db.changelog-master.yaml`) creating `connector`, `connector_sync_run`, `connector_sync_file_outcome`, and `connector_sync_cursor` per design D3, with tenant-scoped indexes and FK cascades from run → outcomes and connector → cursors/runs
- [ ] 1.2 Create JPA entities and Spring Data repositories for the four tables under `repository/` and `model/`, with enums for connector type, run trigger, run status, and file action
- [ ] 1.3 Add `@ConfigurationProperties` class `ConnectorProperties` (`app.connector.*`: scheduler tick, default per-file size limit, throttle budget, history retention cap) with defaults in `application.yaml`
- [ ] 1.4 Test: repository slice test (Testcontainers Postgres) persisting a connector with runs, outcomes, and a cursor; assert tenant-scoped query methods return only the owning tenant's rows

## 2. Connector framework

- [ ] 2.1 Define `DocumentConnector` interface and `ChangeSet`/`SyncCursor` value types in `service/connector/` per design D2
- [ ] 2.2 Implement credential resolution: connector rows hold an opaque credentials reference; resolve secret material through the encrypted credential store from `add-usage-metering-and-quotas` (integration point only — no encryption code here)
- [ ] 2.3 Implement `ConnectorSyncOrchestrator`: claim due connector via `FOR UPDATE SKIP LOCKED`, call `fetchChanges`, apply filename sanitization (`util/IngestionSecurity`) and Tika-sniffed MIME allowlist check before any MinIO write, write bytes under the tenant prefix with a sanitized source-relative path segment in the key, trigger the existing bucket-scan ingestion for the affected prefix, record run + per-file outcomes, persist the cursor only on run completion
- [ ] 2.4 Implement deletion propagation: map deleted source items to MinIO keys via file-outcome / document-metadata records and invoke the single-document deletion path from `add-document-management-api`; record `DELETED` outcomes; ignore deletions for never-landed items
- [ ] 2.5 Implement the scheduler: `@Scheduled` tick scanning for `enabled=true` connectors with `next_run_at` due, computing the next fire time from the cron expression after each run
- [ ] 2.6 Implement sync-run history retention: prune to the configured cap per connector on run insert
- [ ] 2.7 Test: orchestrator unit tests with a fake `DocumentConnector` — added/updated files land in MinIO and trigger ingestion; disallowed sniffed type is skipped with reason and never written; per-file failure yields `PARTIAL` with the failed outcome recorded; failed run leaves the cursor unchanged
- [ ] 2.8 Test: two concurrent orchestrator invocations for one due connector produce exactly one sync run (Testcontainers Postgres, real row locking)
- [ ] 2.9 Test: deletion propagation removes the MinIO object and Qdrant chunks for a previously synced file and records the `DELETED` outcome; a deletion for a never-synced item is a no-op

## 3. SharePoint/OneDrive connector (Microsoft Graph)

- [ ] 3.1 Implement the Graph auth client: client-credentials token acquisition per tenant with in-memory expiry-based caching; secrets resolved at sync time, never persisted or logged
- [ ] 3.2 Implement the Graph API client: site → drives resolution, drive delta requests (initial full enumeration and token-based incremental), delta-page pagination, item content download; deserialize the `deleted` facet
- [ ] 3.3 Implement `SharePointConnector` (implements `DocumentConnector`): apply folder-path scoping to delta results, apply MIME and size filters from Graph item metadata before download (skip with reason, no full download), map delta entries to `ChangeSet` add/update/delete entries, persist one delta token per drive via `connector_sync_cursor`
- [ ] 3.4 Implement throttling compliance: honour `Retry-After` on 429/503, exponential backoff with jitter otherwise, bounded per-request retries and a per-run throttle budget that ends the run as `PARTIAL` with the cursor advanced only through fully processed pages
- [ ] 3.5 Implement delta-token invalidation handling: on Graph 410/resync, discard the stored token and re-enumerate the drive in full
- [ ] 3.6 Test: delta-sync test with mocked Graph responses (WireMock or MockRestServiceServer) — an add, a modify, and a delete in one delta page propagate to MinIO write, MinIO overwrite, and deletion-path invocation respectively, with correct run counters
- [ ] 3.7 Test: throttling backoff — mocked 429 with `Retry-After` is waited out and retried; budget exhaustion ends the run `PARTIAL` with a resumable cursor
- [ ] 3.8 Test: 410 resync — token discarded, full re-enumeration issued, unchanged files not re-indexed (ETag dedup observed)
- [ ] 3.9 Test: credentials hygiene — capture log output across a successful sync and a failed-auth sync; assert no substring of the client secret or access token appears at any level, and the `FAILED` run's error summary names the failure class only

## 4. Connector REST API

- [ ] 4.1 Create DTOs for connector create/update/read (credential fields write-only), sync-run history, and per-file outcomes; add OpenAPI annotations consistent with `IngestionController`
- [ ] 4.2 Implement `ConnectorController` under `/api/v1/connectors`: create, list, get, update, disable, delete, `POST /{id}/sync` (trigger-sync-now, HTTP 409 while a run is in progress), `GET /{id}/runs` and `GET /{id}/runs/{runId}` for history
- [ ] 4.3 Guard every endpoint with the ADMIN role from `add-auth-and-identity`; scope all queries to the caller's tenant from `add-tenant-isolation`
- [ ] 4.4 Implement delete semantics: remove configuration, cursors, and history; leave already-ingested documents untouched
- [ ] 4.5 Test: MockMvc tests — USER role gets 403 on every endpoint; created connector round-trips without echoing the secret; disable stops scheduling; trigger during an active run returns 409; delete removes config/history but a synced document's MinIO object survives
- [ ] 4.6 Add Bruno requests for the connector API under `docs/api/request/AscendAI/`

## 5. Documentation and verification

- [ ] 5.1 Author `docs/CONNECTORS.md`: connector concepts, the connector → MinIO → existing-pipeline principle, the full Azure app-registration walkthrough a customer admin performs (app registration, `Sites.Read.All`/`Files.Read.All` application permissions, admin consent, client secret creation), connector API usage examples, throttling and first-sync expectations for large sites, and the named follow-on connectors (Google Drive, Confluence, network share) as out of scope
- [ ] 5.2 Link `docs/CONNECTORS.md` from the root `README.md` documentation map and add connector notes to root `AGENTS.md` and `AscendAgent/AGENTS.md`
- [ ] 5.3 Run `./gradlew test integrationTest` and fix failures
- [ ] 5.4 End-to-end verification against a live stack: create a connector via Bruno, trigger a sync against mocked-or-real Graph, confirm documents appear in MinIO under the tenant prefix and chunks in Qdrant, delete a source file, re-sync, confirm removal; record outcomes in the run history endpoints
- [ ] 5.5 Update `openspec/changes/add-document-connectors/tasks.md` checkboxes as work proceeds
