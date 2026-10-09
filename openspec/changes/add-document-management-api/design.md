## Context

**Current state.** Documents live in the Floci (S3-compatible, host port 9070) bucket `knowledge-base` (`app.s3.bucket` in `apps/ascend-agent/src/main/resources/application.yaml`) under `markdown/` and `documents/` prefixes. Chunks live in Qdrant collections `ascendai-768` and `ascendai-1536` with `source` / `type` / `title` metadata (`service/ingestion/IngestionMetadataKeys.java`); `source` is the sanitized object key, and `DocumentService.removeOldDocuments` deletes by `source ==` filter before re-adding. Ingestion state is a Spring Integration `JdbcMetadataStore` (`config/AppConfig.java`) writing `manual-ingestion:<key>:<etag> -> timestamp` rows into `INT_METADATA_STORE`, a table created by `spring.integration.jdbc.initialize-schema: always` outside the agent's schema migrations (Liquibase today, Flyway once `upgrade-spring-boot-4` lands). `ManualIngestionService.run` scans the bucket synchronously, dedupes via `putIfAbsent` on that marker, and returns aggregate `{indexed, skipped, failed}` counts; stale-marker cleanup on failure is hand-rolled (`processObject`). `ManualIngestionService` routes only by markdown-vs-unstructured; the richer extension-based `DocumentRouter` (Markdown / Docling / ascend-ocr / Unstructured / per-page PDF) is used by the prompt-attachment path.

**Sibling dependencies (consumed, not re-specified).**

- `add-keycloak-login` (build group 3, applied before this change): all endpoints here assume its authenticated identity. Its authorization matrix asks every later change to add the rows of its own endpoints, and its coverage test fails the build for an endpoint with no row (its D4), so this change adds its rows itself (D11): `DELETE /api/v1/documents/{id}` and `POST /api/v1/documents/{id}/reindex` require `ADMIN`, the read endpoints require `USER` or `ADMIN`, and `POST /api/v1/ingestion/run` keeps the `ADMIN` row `add-keycloak-login` already has.
- `add-tenant-isolation` (company, build group 5): every table of this change already carries `tenant_id VARCHAR(64) NOT NULL`, written from `TenantContext.currentTenantId()` of `add-keycloak-login` (`default` in the personal deployment), with no foreign key (D1). The tenant change adds the foreign keys to `tenants(id)` in its own migration and its ownership checks later. No tenancy enforcement is specified here.
- `add-connector-framework` (the connector framework, split out of `add-document-connectors` on 2026-10-04): synced sources (Obsidian of `add-obsidian-vault`, a web crawl of `add-web-crawl-rag-connector`, SharePoint of the company change `add-document-connectors`, later Google Drive, ...) register documents through the same registry. The schema therefore carries `source_type` (open string: `upload`, `bucket-scan`, `web-download`, `connector:<name>` such as `connector:obsidian`) and a nullable `origin_uri` (D12). The `connector_id` column of a landed file, its chunk field and its payload index are added by `add-connector-framework` itself (owner answer 93 of 2026-10-08).
- `add-download-ingestion` (the agent part of `add-file-download` since 2026-10-04, build group 4, applied after this change): its `POST /api/v1/documents/from-download` and its tool `knowledge_add_download` copy a downloaded file into the knowledge base, register a `documents` row with `source_type` `web-download` and `origin_uri` the download's source URL, and start an indexing run with the run model of D3. `source_type` is an open string, so `web-download` needs no schema change here.
- `upgrade-spring-boot-4` (build group 3, position 2): Flyway, and the RFC 7807 problem detail of its D19 that every error of these endpoints uses (D14).
- `add-deployment-modules` (build group 3, position 6): the module catalog. Document search (`rag`), which the document management API belongs to, is part of the always-on core (`core-chat`), not a module (owner decision of 2026-10-03), so nothing of this change carries `@ConditionalOnModule` (D13).
- `add-shared-scheduler` (build group 3, position 7): the system task contract on which the run orphan sweep of D3 runs, and the one retention task `record-retention` on which the run retention of D9 is an entry.

Build order: build group 3, position 8 of the owner build order of 2026-10-04 (owner answer 94.5 of 2026-10-08) (which supersedes the earlier orders and the group D chain). This change needs `upgrade-spring-boot-4`, `add-keycloak-login`, `add-deployment-modules` and `add-shared-scheduler`, all earlier in build group 3, and is applied before `add-chat-streaming-and-conversations` (group 3, position 9) and before `add-connector-framework`, `add-download-ingestion` and `add-obsidian-vault` (build group 4), which register documents in its registry and start its runs.

## Goals / Non-Goals

**Goals:**

- A queryable, Flyway-managed registry of every knowledge-base document with status, chunk counts, and failure reasons.
- List / detail / delete / reindex endpoints over that registry.
- Asynchronous ingestion runs with observable per-file outcomes and a bounded history.
- Delete that is retryable after partial failure and safe to execute mid-chat.

**Non-Goals:**

- Authentication, authorization, tenancy (siblings own these).
- Connector sync logic (only the schema hooks, the registration rule of D12 and the chunk fields land here).
- The download copy of `add-download-ingestion` (its endpoint and tool register a row and start a run through this change's services).
- Changing how the Spring Integration S3 streaming pipeline (`IngestionPipelineConfig`) finds new objects. Its S3 inbound poller stays, and D16 changes only what it does with an object it finds.
- A message broker or a separate job service. Several agent instances run at once (owner answer 87 of 2026-10-08), and the run queue is the `ingestion_runs` rows in Postgres (D3).
- UI.

## Decisions

### D1. Registry tables: `documents` + `document_index_state` + `ingestion_runs`

- Every table below carries `tenant_id VARCHAR(64) NOT NULL`, written from `TenantContext.currentTenantId()` of `add-keycloak-login` (`default` in the personal deployment) when the row is created, with no foreign key. A run started by a request takes the tenant of the request. A row written by the run executor takes the tenant of its run, bound with `TenantContext.runAs` on the executor thread (D3). `add-tenant-isolation` (company, build group 5) adds the foreign keys to `tenants(id)` later.
- `documents`: `id UUID PK`, `tenant_id`, `object_key VARCHAR UNIQUE`, `display_name`, `size_bytes`, `mime_type`, `source_type`, `origin_uri NULL`, `status` (`UPLOADED` | `INDEXING` | `INDEXED` | `FAILED` | `DELETING`), `failure_reason NULL`, `created_at`, `updated_at`.
- `document_index_state`: `tenant_id` (copied from its document), `(document_id FK, collection_name)` unique pair, `chunk_count`, `etag`, `last_indexed_at`. A document can be indexed into `ascendai-768` and `ascendai-1536` independently (the embedding provider chosen per run decides the collection via `VectorStoreResolver`), so per-collection state is a child table rather than duplicated columns. Listing aggregates chunk counts and takes the max `last_indexed_at`.
- `ingestion_runs`: `id UUID PK`, `tenant_id`, `state` (`QUEUED` | `RUNNING` | `COMPLETED` | `FAILED`), `scope_prefix NULL`, `document_id NULL` (set for reindex runs), `embedding_provider`, `indexed_count`, `skipped_count`, `failed_count`, `failures JSONB` (array of `{objectKey, reason}`, capped at `app.ingestion.run-failures.max-entries` entries, default 100, D17), `owner_instance NULL`, `lease_expires_at NULL` (replica-safe restart sweep, task 3.5a, kept by owner answer 87 of 2026-10-08), `requested_at`, `started_at NULL`, `finished_at NULL`. The named partial unique index `uq_ingestion_runs_pending_document` on `document_id` `WHERE state IN ('QUEUED', 'RUNNING')` allows at most one waiting or running run per document, which is how several instances agree that a document is already being indexed (D3, D16).

Alternative considered: extend `INT_METADATA_STORE` usage. Rejected - it is a schema-less key-value table owned by Spring Integration and cannot hold typed columns. (Since owner answer 89.11 of 2026-10-08, `upgrade-spring-boot-4` creates the `INT_*` tables in its Flyway migration, so the earlier reason "not Flyway-managed" no longer holds.)

### D2. Registry ETag comparison replaces the manual-ingestion dedupe markers

`ManualIngestionService` stops calling `metadataStore.putIfAbsent` and instead compares the S3 object's ETag against `document_index_state.etag` for the target collection; unchanged means skip, changed or absent means ingest and update the row on success. This removes the hand-rolled stale-marker cleanup in `processObject` (failure simply leaves the old ETag in place, so the next run retries naturally). Existing `manual-ingestion:*` rows in `INT_METADATA_STORE` become inert and are left in place. Since owner answer 89.2 of 2026-10-08 the streaming pipeline reads the same registry ETag (D16), so no code of the agent reads or writes `INT_METADATA_STORE` any more, and the `JdbcMetadataStore` bean of `config/AppConfig.java` is removed. Spring Integration JDBC then has no reason to stay: at implementation time task 3.11 searches the agent for any other use of it (metadata store, lock registry, message store, channel store). When none is found, this change removes the dependency `libs.spring.integration.jdbc` (and its version catalog entry when nothing else uses it), the `spring.integration.jdbc.initialize-schema` lines of the tests, and drops the `INT_*` tables that the Flyway migration V1 of `upgrade-spring-boot-4` creates, with a Flyway migration of its own, because no data has to survive (owner answers 73.1 and 88.1). When another use is found, the tables and the dependency stay and the task records which use keeps them.

Alternative considered: dual-write both stores during a transition. Rejected - two sources of truth for the same fact (DRY), and nothing reads the old markers after the switch.

### D3. Async runs: the `ingestion_runs` rows are the queue, one run at a time in the deployment

`POST /api/v1/ingestion/run` inserts a `QUEUED` row and returns `202 Accepted` with `{runId}` and a `Location: /api/v1/ingestion/runs/{id}` header. Status reads come from Postgres, so any instance can answer. Reindex jobs and the pickup of the streaming pipeline (D16) share the same run model with `document_id` set.

Several agent instances run at once (owner answer 87 of 2026-10-08), so the queue is the rows, never an in-process executor queue:

- Every instance has one run worker, a single worker thread of its own that executes at most one run at a time. It claims the oldest `QUEUED` run in one transaction that first takes the transaction advisory lock of ingestion runs (`pg_advisory_xact_lock` with one fixed key of this change), checks that no run is `RUNNING` with a lease that has not expired, and then moves the oldest `QUEUED` row to `RUNNING` with `owner_instance` and `lease_expires_at` set. So runs execute one at a time in the whole deployment, in submission order, because a concurrent full-bucket scan against the same collection would race `removeOldDocuments`.
- The worker of the instance that inserted a run is woken at once. The insert also sends `pg_notify` on the channel `ingestion_run_queued` with the run id as payload, through the one listener `PostgresNotificationListener` of `add-keycloak-login` (its D20), so an idle worker on another instance wakes too. Its `onReconnect()` wakes the worker, which then reads the queue. A `@Scheduled` check on Spring Boot's auto-configured `TaskScheduler` wakes the worker as a fallback when a notification was lost (owner answer 89.3 of 2026-10-08).
- While a run executes, the same local `@Scheduled` timer of its instance renews `lease_expires_at`, so a slow Docling or OCR run is never taken for an orphan.
- A `QUEUED` run belongs to no instance and is never failed by a sweep: any live worker runs it, also after the instance that accepted it stopped.
- A `RUNNING` run whose lease expired is an orphan. On application startup the sweep marks such rows `FAILED` with reason `interrupted by restart`, and the system task `ingestion-run-orphan-sweep` on the shared scheduler (`*/5 * * * *` in `UTC`, no module marking) does the same while every instance stays up, so a run of an instance that died is failed even when no instance restarts. A run with a live lease of another instance is never touched. The job itself is safe to re-request because ETag dedupe makes re-runs cheap.

The timing values of the worker are settings (owner answer 98.4 of 2026-10-08, D17): the lease is renewed every 10 seconds (`app.ingestion.run-worker.lease-renew-interval`), expires 60 seconds after its last renewal (`app.ingestion.run-worker.lease-duration`), and the fallback check wakes the worker every 30 seconds (`app.ingestion.run-worker.fallback-check-interval`). The application refuses to start when the lease is not longer than the renewal interval. The three values are listed in `docs/INGESTION.md` and in `apps/ascend-agent/docs/CONFIGURATION.md`.

Alternative considered: keep `/run` synchronous and add polling only for reindex. Rejected - the blocking full-bucket scan is the worst offender (minutes-long HTTP requests through Docling/OCR) and the run-history requirement needs persisted runs anyway. Alternative considered: a message broker or a separate job service. Rejected - the Postgres row is already the durable record, and the advisory lock and the `FOR UPDATE` claim of the rows are the one cross-instance mechanism of the agent for shared queues (owner answer 87). Alternative considered (review item group 3 S2-9): drop the lease columns and fail every `RUNNING` row at startup. Rejected by owner answer 87, because a second instance would then fail the live runs of the first.

### D4. Delete ordering: vectors, then object, then row - resumable via `DELETING` status

`DELETE /api/v1/documents/{id}` executes: (1) set `status = DELETING`; (2) delete Qdrant points with `source == object_key` from every collection listed in `document_index_state` (delete-by-filter is idempotent); (3) delete the object storage object (idempotent); (4) delete the `document_index_state` rows and the `documents` row. A failure at any step leaves the row in `DELETING`; repeating the DELETE re-executes the remaining steps. Order rationale: orphaned vectors are the harmful failure mode (retrieval would cite a document whose file is gone), so vectors go first; an orphaned object storage object is inert. Returns `204 No Content` on completion, `404` for an unknown id, `409 Conflict` if the document is currently `INDEXING` (deleting under an active ingest would race chunk re-insertion).

Mid-chat behavior: presigned source URLs already handed out (TTL `app.rag.source-attachments.presign-ttl`, default PT15M) are not tracked or revoked - they stop resolving once the object storage object is gone and expire on their own anyway. In-flight chat turns that already retrieved chunks complete normally; subsequent retrievals no longer see the document.

### D5. Reindex goes through `DocumentRouter`

`POST /api/v1/documents/{id}/reindex` fetches the object bytes from object storage and processes them via `DocumentRouter.routeAndProcess` (full extension-based routing, including per-page PDF Docling/OCR dispatch), then splits and ingests with the existing `removeOldDocuments`-then-add replacement path into the collection resolved from the requested embedding provider. Reindex ignores ETag dedupe by design (the point is to force a refresh, e.g. after a router or chunking improvement). It runs as an async run (D3) because OCR of a large PDF is minutes-long; response is `202` + run id, and the document shows `INDEXING` until the run finishes.

The bucket-scan path uses the same routing. `ManualIngestionService` today routes only markdown-vs-unstructured, and this change moves every scanned object onto `DocumentRouter.routeAndProcess` (tasks 3.2a and 3.2b), so upload, bucket scan and reindex all parse a file the same way. This change owns that routing. Later changes (add-passage-level-citations, add-connector-framework) build on it and do not re-implement it.

### D6. Registry population

Upload registers or updates the row immediately (`status = UPLOADED`). Bucket-scan runs upsert rows for every object they visit, so an object dropped into the bucket out-of-band gets a row on the next run, and at once when the streaming pipeline is switched on (D16). A bucket-scan upsert sets `source_type` `bucket-scan` only when it creates the row: on a row that exists it never overwrites the `source_type` or `origin_uri` given at registration (D12), and it never writes a column of another change, such as `connector_id` of `add-connector-framework`. While the streaming pipeline is off, an object that no run has scanned yet does not appear in listings until a run executes. There is no backfill of content that existed before this change and no data migration script (see Migration Plan).

### D7. Pagination and response shape

`GET /api/v1/documents` takes `page`, `size` with default 20 / max 100 (the settings `app.documents.list.default-size` and `app.documents.list.max-size`, D17), the optional filters `status` (D9) and `sourceType` (an exact match on `source_type`, for example `connector:obsidian` or `web-download`, D12), sorted by `updated_at` descending, executed as hand-written native queries per D10, and returns `{items, page, size, totalElements, totalPages}` following the module's DTO-at-the-boundary convention. Run history takes a `limit` query parameter (default 20, max 100, the settings `app.ingestion.runs.default-limit` and `app.ingestion.runs.max-limit`, D17) and the optional filter `state` (`QUEUED`, `RUNNING`, `COMPLETED` or `FAILED`, D9), newest first.

### D8. The presigned link stays mandatory, `contentPath` is added beside it (owner decision, 2026-09-03)

The object store stays private, as `harden-cloud-deployment` (build group 3, position 4) requires: in production both presign address variables point at the private address, so `GET /api/v1/documents/{id}/content` is the one public download path for a RAG source. The `production-deployment` delta of this change states it (moved here from `harden-cloud-deployment` by the dependency fix of 2026-10-05).

The first draft of this change made `downloadUrl` and `expiresAt` optional on `SourceFile` and declared `contentPath` the canonical download path, on the reasoning that a public deployment should never have to expose the object store. That contradicted the `rag-source-attachments` baseline, which guarantees a non-blank `downloadUrl` and `expiresAt` on every source entry, and the contradiction had also broken archival: the delta modified a requirement titled `Caller sets `attachSources=true``, which is a scenario in the baseline rather than a requirement, so the merge aborted with a not-found error in every ordering while `openspec validate --strict` stayed silent (the validator skips a MODIFIED block whose target requirement is missing).

The owner's decision is that the link stays. Every source entry always carries a non-blank `downloadUrl` and `expiresAt`, exactly as the baseline guarantees today, and this change adds `documentId` and `contentPath` alongside them as further mandatory fields. The reason is that a caller must never have to implement two different ways of fetching the same source: if the presigned link were sometimes absent, every client would need both code paths plus the logic to choose between them.

Two mechanical consequences follow. The delta now modifies the requirement that genuinely exists, `Opt-in `attachSources` parameter on prompt endpoint`, and carries all three of its baseline scenarios so the merge engine does not abort on a dropped scenario name. The delta's `SourceFile` modification is written on top of the post-Floci wording from `replace-minio-with-floci`, which is the text on the ground, rather than the older object storage-specific phrasing still sitting in `openspec/specs/`.

## Risks / Trade-offs

- [An instance dies while it runs a run] → Mitigation: its lease expires, the startup sweep of any instance or the periodic `ingestion-run-orphan-sweep` marks the run `FAILED` with an explicit reason, and re-requesting is cheap due to ETag dedupe. Queued runs are never lost, because any live worker claims them (D3).
- [Several instances poll the bucket for the streaming pipeline] → each detects the same new object, but the partial unique index `uq_ingestion_runs_pending_document` lets exactly one of them queue its run (D16).
- [Delete leaves an orphaned object storage object if the process dies between steps 3 and 4] → Mitigation: row stays `DELETING` and is surfaced as such in listings; retrying the DELETE finishes the job.
- [`failures` JSONB cap at 100 hides the tail of a catastrophic run] → Mitigation: `failed_count` stays exact; the cap only bounds detail rows, and the log retains every failure line.
- [Breaking `/run` response contract] Existing Bruno requests and the e2e specs assert on synchronous counts. → Mitigation: update the Bruno collection and `apps/ascend-agent/e2e/` specs in the same change; version stays `/api/v1` because the endpoint's consumers are all in-repo.
- [Race between reindex and delete on the same document] → Mitigation: `409` guard both directions - delete rejects `INDEXING`, reindex rejects `DELETING`.

## Migration Plan

The owner decided on 2026-10-02 (confirmed by owner answer 73.1 of 2026-10-06) that there is no existing data to keep, so this change has no backfill, no copy of old dedupe markers, no re-index of existing objects and no rollback script that restores data. This holds only until the first real customer deployment.

1. Ship the Flyway migration `V<n>__document_management.sql` (`<n>` is the next free version at implementation time), which creates the plain schema of D1 in one step, together with the code: new endpoints live, `/run` now async, dedupe reads the registry.
2. Rollback: revert the deployment. No step restores data. Flyway Community has no automatic undo, so the tables are dropped in a later forward migration only if the change is abandoned.

### D9. Run history retention and status filter (owner decision, 2026-10-01)

The one retention task `record-retention` of `add-shared-scheduler` (its D15) deletes `ingestion_runs` rows whose `finished_at` is older than 30 days, through the entry `ingestion-run` this change registers with no module marking: table `ingestion_runs`, time column `finished_at`, age `app.ingestion.run-retention` (default `P30D`), condition `state IN ('COMPLETED', 'FAILED')` (owner answer 89.7 of 2026-10-08). Rows still `QUEUED` or `RUNNING` are never pruned. Each run of that task is run by exactly one agent instance, and running it twice deletes nothing more. The system task `ingestion-run-retention` of the plan before 2026-10-08 is gone. The startup sweep of task 3.5 stays a startup action on each instance, and the periodic orphan sweep of D3 is its own system task. `GET /api/v1/documents` takes an optional `status` filter in this change.

### D10. Persistence style: Spring Data JDBC

The agent uses Spring Data JDBC (`spring-boot-starter-data-jdbc` in `apps/ascend-agent/build.gradle.kts`), never JPA. Entities are plain classes or records with `@Table` and `@Id`. Repositories extend `CrudRepository`. Paginated and filtered queries are hand-written native SQL in `@Query` with `LIMIT :limit OFFSET :offset`, plus a separate `@Query` count for `totalElements`, in the same style as the existing repositories under `repository/`. JSONB columns map through a custom converter registered in a `JdbcConfiguration`.

### D11. Security rows of this change

`add-keycloak-login` is build group 3 and lands before this change (owner rule of 2026-10-04), so every endpoint here is behind its JWT resource server from the start. This change adds its own rows to that change's authorization matrix (its D4) in `SecurityConfig`, each with a security slice test: `DELETE /api/v1/documents/{id}` and `POST /api/v1/documents/{id}/reindex` need `ADMIN`, `GET /api/v1/documents`, `GET /api/v1/documents/{id}`, `GET /api/v1/documents/{id}/content`, `GET /api/v1/ingestion/runs` and `GET /api/v1/ingestion/runs/{id}` need `USER` or `ADMIN`, and `POST /api/v1/ingestion/run` keeps the `ADMIN` row of `add-keycloak-login`. Ownership checks per tenant are company work of `add-tenant-isolation` and plug in later. Until 2026-10-04 this decision accepted a gap behind the optional `httpBasic` until group C. That gap no longer exists, because the personal login lands first.

### D12. Registry values given at registration, and the chunk fields that carry them

The registry keeps the `source_type` and `origin_uri` given when a row is registered: `upload` by the upload path, `connector:<name>` and the source address by the connector framework of `add-connector-framework` (for example `connector:obsidian` with an `obsidian://` address from `add-obsidian-vault`), `web-download` and the download's source URL by `add-download-ingestion`. A later bucket-scan upsert of the same object key never overwrites them with `bucket-scan` (D6).

The `connector_id` of a landed file is not this change's column (owner answer 93 of 2026-10-08, review item S3-13). `add-connector-framework` adds `documents.connector_id` in its own migration, sets it when it registers a landed file, puts it on every chunk through a `ChunkPayloadContributor` of D15, and creates its payload index, so the vault filter of `add-obsidian-vault` on `connector_id` is still served by an index.

Every ingestion run, bucket scan, reindex and single-document indexing alike, copies `source_type` from the registry row onto every chunk it writes, under the new constant `SOURCE_TYPE` (`source_type`) in `IngestionMetadataKeys`. The field gets a keyword payload index on every RAG collection, created at startup together with the other payload indexes, so a filter on it is served by an index.

`GET /api/v1/documents` accepts a `sourceType` filter, the obvious companion of a listing that now holds several sources.

`IngestionRunService` has two entry points for a run: a bucket scan for a prefix (the one `add-connector-framework` calls), and a run for one registered document, which reindex (D5), the pickup of the streaming pipeline (D16) and the download copy of `add-download-ingestion` all use.

### D13. The document management API belongs to the core document search

Document search (`rag`) is part of the always-on core (`core-chat` in the catalog of `add-deployment-modules`), not a module (owner decision of 2026-10-03), and the document management API is part of it. `DocumentController`, the changed `IngestionController`, `DocumentRegistryService`, `DocumentDeletionService`, `IngestionRunService`, the run worker, the `ingestion-run-orphan-sweep` task bean and the `ingestion-run` retention entry carry no `@ConditionalOnModule` and always exist, and no tenant module grant guards `/api/v1/documents/**` or `/api/v1/ingestion/**`. `POST /api/v1/documents/from-download` of `add-download-ingestion` carries `@ConditionalOnModule("web-download")`, which that change owns.

### D14. Error bodies are RFC 7807 problem details

Every error of these endpoints is the problem detail of `upgrade-spring-boot-4` D19: media type `application/problem+json`, `type` `https://ascend.ai/errors/<code with - for _>`, `title`, `status`, `detail`, `instance` and the top level extension field `code` from `ApiErrorCode`. The controllers throw `ApiProblemException` with a code and build no error body of their own. The codes:

- 400 `validation` for a `page`, `size`, `limit`, `status`, `state` or `sourceType` value out of range or unknown, with the `errors` field of D19 point 5 for a bean validation failure.
- 404 `not_found` for an unknown document or run id, and for the content of a deleted document.
- 409 `document_state_conflict` for a delete while the document is `INDEXING` and a reindex while it is `DELETING`. This change adds that one value to `ApiErrorCode` and reuses the existing codes for every other case.

### D15. Chunk payload extension point, and document access groups added later by company work

Owner decision 65.3 of 2026-10-04 lets a tenant `ADMIN` narrow who may find a directly uploaded document with `PUT /api/v1/documents/{id}/access`. That is company-only work: the personal deployment has one user and needs no narrower list. Since the dependency fix of 2026-10-05 the endpoint, its column, its principals, its refusals, its audit action and its end-to-end spec belong to `add-tenant-administration` (company, build group 5), which builds on the retrieval groups of its own D7 and on `add-auth-and-identity` and `add-tenant-isolation`. This change keeps only the extension point that work plugs into, with a safe default:

- `ChunkPayloadContributor` (core interface): given the registry row of the document being indexed, it returns extra payload fields for every chunk the run writes. Every ingestion run (bucket scan, reindex and single-document run) asks every registered contributor, through `ObjectProvider`, after it has set `source` and `source_type` (D12). A contributor never removes or replaces a field this change sets. This change registers no contributor, so a deployment without `add-connector-framework` writes exactly the fields of D12. `add-connector-framework` registers one for `connector_id` (D12).
- `add-tenant-administration` registers its contributor later. It writes the narrowed access list of a document onto every new chunk, so a reindex keeps the list. Its own migration adds the column that stores the list, and its own controller adds the endpoint. No class of this change is edited for it.
- Every audit action of that work goes through `AuditEventPort` of `add-deployment-modules` (D21), so it needs no audit edit here either.

Why a port and not a column now: the access list means nothing without the retrieval groups and principals of company work, and an unused column would be a schema promise this change cannot test.

### D16. The streaming S3 pipeline writes through the registry and the runs (owner answer 89.2 of 2026-10-08)

One store remembers what was ingested: the registry ETag of D2. The Spring Integration streaming pipeline of `IngestionPipelineConfig` (switched on by `app.ingestion.auto.enabled`, off by default) keeps its S3 inbound poller and its fixed delay (`app.ingestion.poller.fixed-delay-millis`, default 1 second), so an object that lands in the bucket is still picked up within about a second. The poller runs on Spring Boot's auto-configured `TaskScheduler`, the one local timer (owner answer 89.3 of 2026-10-08). What changes is what happens to an object it finds:

- `S3PersistentAcceptOnceFileListFilter` on `INT_METADATA_STORE` is replaced by a filter that accepts an object only when the registry has no `document_index_state` row for it and the target collection with the same ETag, and the document is not `DELETING`.
- For an accepted object the flow no longer parses, splits and embeds itself. It upserts the registry row through `DocumentRegistryService` (`bucket-scan` when the row is new, D6) and starts the single-document run of `IngestionRunService` for it, with `INSERT ... ON CONFLICT ON CONSTRAINT uq_ingestion_runs_pending_document DO NOTHING`. So the object is parsed through `DocumentRouter` like every other path (D5), its run appears in the run history, its registry row reaches `INDEXED` or `FAILED`, and its ETag is recorded on success.
- Several instances run the poller, each for itself. When two of them find the same object, the partial unique index lets exactly one run be queued, and the run worker of D3 runs it once in the deployment (owner answer 87 of 2026-10-08). While that run is `QUEUED` or `RUNNING`, a later poll that finds the object again queues nothing.
- The markdown and unstructured channels of the flow, which wrote to the vector store directly, are removed, because the run does the work.

Alternative considered: a bucket scan on the shared scheduler in place of the poller. Rejected: the shortest step of the shared scheduler is one minute, so pickup would drop from about a second to a minute, which owner answer 89.2 does not allow.

### D17. Settings of this change (owner rule 98 of 2026-10-08)

Every value of this change that has a default is a setting: `application.yaml` writes `key: ${ENV:default}`, the `@ConfigurationProperties` record that binds it carries the same default in code, the `ascend-agent` service of `compose.yaml` writes `- ENV=${ENV:-default}`, and `apps/ascend-agent/docs/CONFIGURATION.md` gets one row per setting whose description ends with "Added by `add-document-management-api`.". ENV is Spring Boot's canonical environment form of the key.

| Key | Environment variable | Default | What it does |
| :--- | :--- | :--- | :--- |
| `app.ingestion.run-worker.lease-renew-interval` | `APP_INGESTION_RUNWORKER_LEASERENEWINTERVAL` | `10s` | How often an instance renews the lease of the run it executes (D3, owner answer 98.4) |
| `app.ingestion.run-worker.lease-duration` | `APP_INGESTION_RUNWORKER_LEASEDURATION` | `60s` | Time after the last renewal at which a `RUNNING` run counts as an orphan (D3, owner answer 98.4) |
| `app.ingestion.run-worker.fallback-check-interval` | `APP_INGESTION_RUNWORKER_FALLBACKCHECKINTERVAL` | `30s` | How often an idle run worker checks the queue when no `ingestion_run_queued` notification reached it (D3, owner answer 98.4) |
| `app.ingestion.run-retention` | `APP_INGESTION_RUNRETENTION` | `P30D` | Age after which a finished run is deleted by the entry `ingestion-run` (D9) |
| `app.ingestion.run-failures.max-entries` | `APP_INGESTION_RUNFAILURES_MAXENTRIES` | `100` | Largest number of `{objectKey, reason}` entries a run keeps in `failures` (D1) |
| `app.ingestion.runs.default-limit` | `APP_INGESTION_RUNS_DEFAULTLIMIT` | `20` | Run history page size when no `limit` is sent (D7) |
| `app.ingestion.runs.max-limit` | `APP_INGESTION_RUNS_MAXLIMIT` | `100` | Largest `limit` of the run history (D7) |
| `app.documents.list.default-size` | `APP_DOCUMENTS_LIST_DEFAULTSIZE` | `20` | Document listing page size when no `size` is sent (D7) |
| `app.documents.list.max-size` | `APP_DOCUMENTS_LIST_MAXSIZE` | `100` | Largest `size` of the document listing (D7) |
| `app.scheduler.system-tasks.ingestion-run-orphan-sweep.cron` | `APP_SCHEDULER_SYSTEMTASKS_INGESTIONRUNORPHANSWEEP_CRON` | `*/5 * * * *` | Schedule of the orphan sweep (D3, the contract of `add-shared-scheduler` D2) |
| `app.scheduler.system-tasks.ingestion-run-orphan-sweep.time-zone` | `APP_SCHEDULER_SYSTEMTASKS_INGESTIONRUNORPHANSWEEP_TIMEZONE` | `UTC` | Zone of that schedule |

The application refuses to start when a duration or a count is zero or negative, when the lease is not longer than its renewal interval, and when a default page size or limit is greater than its maximum. Kept as constants, because they are not operational: the fixed key of the advisory lock of D3, the notification channel name `ingestion_run_queued`, the reason text `interrupted by restart`, the status and state names, the `source_type` values, the chunk field name `source_type`, the index and constraint names, and the error codes. The existing settings this change keeps unchanged (`app.ingestion.auto.enabled`, `app.ingestion.poller.fixed-delay-millis`, `app.rag.source-attachments.presign-ttl`) are not added by this change, so their rows come from the inventory of `fix-linux-docker-host-access`.

## Owner decisions of 2026-10-06

Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores. This change keeps its plan with no backfill, no copy of old dedupe markers and no re-index of existing objects. The registry starts empty, and only objects that a run scans after the change appear in it.

## Owner decisions of 2026-10-07

Answer 75.1: the owner approved the fixes of the review of 2026-10-07. In this change they fix item 4 (the paragraph of D8 that said the object store must stay reachable by clients is dropped, because the content endpoint is the one public download path), item 18 (the end-to-end specs 9.3 and 9.5 run on the scripted chat model and the scripted embeddings of `close-agent-test-gaps`, with no real model and no `OPENAI_API_KEY`), item 54 (document search `rag` is called part of the core, never a module) and item 58 (D7 names the `state` filter of the run history that D14 validates).

## Owner decisions of 2026-10-08

Answer 76.2: the scripted model of the shared harness of `close-agent-test-gaps` is Mockoon. The vector files of specs 9.3 and 9.5 lie in `apps/ascend-agent/e2e/fixtures/scripted-model/embeddings/document-management/`, and spec 9.3 reads the scripted model's request log (`GET /mockoon-admin/logs`). Answer 77.1: in the deterministic phase the provider `scripted` sends the embedding provider name `openai`, which the e2e overlay points at the scripted model, so specs 9.3 and 9.5 write to `ascendai-1536` like the other specs of task group 9. (The dummy key of the start restart that this record named is gone since owner answer 91.1 of 2026-10-08: the agent keeps its key from `.env`, and only the scripted model sees it.)

Answer 78.1: the provider `scripted` uses `default-embedding: openai`, and the deterministic phase overlay points the agent's own embedding entry `openai` at Mockoon. There is no separate scripted embedding entry, and every vector file of this change is 1536 long (`ascendai-1536` and `ascend_memory_1536`).

Answer 78.4: the subfolder name `document-management` of the scripted model's reply files and vector files stays.

Approved fix of 2026-10-08: every deterministic spec of this change that runs a scripted chat turn wipes in AscendMemory the memories of its users in its Reset state and Post-run cleanup (`POST /api/v1/memory/wipe` with the provider `openai` and the service token), because the memory extraction of a scripted turn embeds through the scripted model into `ascend_memory_1536` (tasks 9.3 and 9.5). (Superseded by owner answer 91.1 of 2026-10-08: the deterministic specs wipe no memories.)

Answer 79.1 and 79.2: the harness phase of `close-agent-test-gaps` D7 sets the dummy `OPENAI_API_KEY` `e2e-scripted-not-a-real-key` in the shell of its start restart only, and the end check confirms the key is no longer this value. (The dummy key part is superseded by owner answer 91.1 of 2026-10-08.) The scripted chat model and the scripted embeddings of specs 9.3 and 9.5 come from the container `e2e-scripted-model` at `http://e2e-scripted-model:3000` on the stack's network (tasks 9.3 and 9.5).

Answer 87 (rule R1): several agent instances run at once. The lease columns of `ingestion_runs` stay (review item group 3 S2-9 is not applied), the `ingestion_runs` rows are the queue, claimed under one advisory lock so runs execute one at a time in the deployment, `QUEUED` runs survive the instance that accepted them, a periodic `ingestion-run-orphan-sweep` joins the startup sweep, and the streaming pipeline queues each object once through the partial unique index `uq_ingestion_runs_pending_document` (D1, D3, D16). The worker of another instance wakes through Postgres `NOTIFY` on the channel `ingestion_run_queued` of the one listener of `add-keycloak-login` D20. The registry, the deletes and the content download keep no in-process state.

Answer 85.1: no secret is set in the shell. Every key the deterministic phase of specs 9.3 and 9.5 needs comes from the repository `.env` (task group 9). (Since owner answer 98.1 of 2026-10-08 the phase sets nothing in the shell at all: it copies the overlay into the running agent, `close-agent-test-gaps` D7.)

Answer 88 (rule R2): the company plug-in point `ChunkPayloadContributor` of D15 stays, and `add-connector-framework` now uses it too for `connector_id` (D12, D15).

Answer 89.2: one ingestion path. The streaming S3 pipeline keeps its poller and its near-instant pickup, and writes through `DocumentRegistryService` and the single-document run of `IngestionRunService`, so the registry ETag is the one store of what was ingested and `INT_METADATA_STORE` is no longer used (D2, D16, task 3.9). Unless another use of Spring Integration JDBC is found, this change also removes that dependency and drops the `INT_*` tables with its own Flyway migration, so answer 89.11 (one schema owner) carries no dead tables (D2, task 3.11).

Answer 89.3: the local timers of this change (the lease renewal, the fallback wake of the run worker, the pipeline poller) run on Spring Boot's auto-configured `TaskScheduler`, and the cluster-wide orphan sweep runs on the shared scheduler (D3, D16).

Answer 89.7: run retention is the entry `ingestion-run` of the one retention task `record-retention` of `add-shared-scheduler`, in place of the system task `ingestion-run-retention` (D9, task 3.5b).

Answer 89.11 (received from `upgrade-spring-boot-4`): Spring Integration no longer creates its own tables. `upgrade-spring-boot-4` puts Spring Integration's PostgreSQL DDL into the agent's Flyway migration `V1__initial_schema.sql` and sets `spring.integration.jdbc.initialize-schema: never`, so `INT_METADATA_STORE` and the other `INT_*` tables are created by Flyway. The reason "not Flyway-managed" of the D1 alternative no longer holds, and the others stay. This change reads, alters or drops no `INT_*` table: it only stops using `INT_METADATA_STORE` (D2).

Answer 91.1: the deterministic phase of `close-agent-test-gaps` D7 recreates only the agent, AscendMemory is faked in the Mockoon container `e2e-scripted-model` under `/ascend-memory/`, there is no dummy key, and no deterministic spec wipes memories. Specs 9.3 and 9.5 drop their memory wipes, and the memory extraction of their scripted turns sends its insert to the fake, so nothing reaches `ascend_memory_1536`. The agent's own scripted embeddings still go to `ascendai-1536`, so the vector files stay 1536 long (task group 9).

Answer 91.3: spec 9.6, which restarted the agent during a slow Docling run, is removed, because the integration test of task 3.8 and the sweep tests of task 3.10 prove the sweep. Its README rows, its allowlist shape and its scenario line go with it.

Answer 93: review item S3-13, the `connector_id` column, its chunk field and its payload index move to `add-connector-framework` (D1, D12). Review items S2-8 (`ChunkPayloadContributor`) and S2-9 (the lease columns) are not applied: the first is a company plug-in point (rule R2) that `add-connector-framework` now also uses, and the second is kept by rule R1.

Answer 94.5: the new change `scale-ocr-and-audio-across-containers` takes build group 3, position 5, directly after `harden-cloud-deployment`, so this change moves from position 7 to position 8 (`openspec/BUILD_ORDER.md`), and the positions of the other moved changes it names were moved by one too. Its dependencies and its tasks do not change.

Answer 98: every value of this change with a default is a setting with its environment variable, the same default in code, a `${VAR:-default}` line on the `ascend-agent` service of `compose.yaml` and a row in `apps/ascend-agent/docs/CONFIGURATION.md` ending with "Added by `add-document-management-api`." (D17, tasks 3.1, 3.4, 3.5a, 3.5b, 3.10, 4.1 and 7.6). Made external: `APP_INGESTION_RUNWORKER_LEASERENEWINTERVAL` (`10s`), `APP_INGESTION_RUNWORKER_LEASEDURATION` (`60s`), `APP_INGESTION_RUNWORKER_FALLBACKCHECKINTERVAL` (`30s`), `APP_INGESTION_RUNRETENTION` (`P30D`), `APP_INGESTION_RUNFAILURES_MAXENTRIES` (`100`), `APP_INGESTION_RUNS_DEFAULTLIMIT` (`20`), `APP_INGESTION_RUNS_MAXLIMIT` (`100`), `APP_DOCUMENTS_LIST_DEFAULTSIZE` (`20`), `APP_DOCUMENTS_LIST_MAXSIZE` (`100`), `APP_SCHEDULER_SYSTEMTASKS_INGESTIONRUNORPHANSWEEP_CRON` (`*/5 * * * *`) and `APP_SCHEDULER_SYSTEMTASKS_INGESTIONRUNORPHANSWEEP_TIMEZONE` (`UTC`). Kept as constants, because they are not operational: the advisory lock key, the channel name `ingestion_run_queued`, the reason text, the status, state and `source_type` values, the chunk field, index and constraint names, and the error codes (D17).

Answer 98.1: no test line in `compose.yaml` and no `e2e` profile. The deterministic phase that specs 9.3 and 9.5 run in copies the overlay into the running agent and restarts it, and its end step recreates the agent from the image, as `close-agent-test-gaps` D7 writes out. The intro of task group 9 and the record of answer 85.1 now cite that decision instead of the profile restart.

Answer 98.4: the document ingestion run lease is renewed every 10 seconds, expires 60 seconds after its last renewal, and the fallback check of the run worker runs every 30 seconds, three settings (D3, D17, tasks 3.1 and 3.5a, the `ingestion-correctness` scenario "A long run keeps its lease"). The earlier text that left these values to the implementation is gone.

## Open Questions

None. Retention and the status filter were settled on 2026-10-01 (D9). The administrator surface for narrower access lists on direct uploads was decided by owner decision 65.3 of 2026-10-04: `PUT /api/v1/documents/{id}/access`, added by `add-tenant-administration` later through the extension point of D15 (dependency fix of 2026-10-05), and the retrieval groups in `add-tenant-administration` (its D7), both company-only work built after the personal version.
