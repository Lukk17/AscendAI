## Why

The RAG knowledge base is write-only. The only ingestion endpoints are `POST /api/v1/ingestion/upload` (multipart to the Floci object store) and `POST /api/v1/ingestion/run` (synchronous full-bucket scan) in `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/controller/IngestionController.java`; a grep for `@GetMapping` / `@DeleteMapping` / `@PutMapping` across `apps/ascend-agent/src/main/java` returns zero matches. Three concrete consequences:

1. **Nobody can see what is indexed.** The only ingestion state today is Spring Integration's `INT_METADATA_STORE` key-value table (`JdbcMetadataStore` bean in `config/AppConfig.java`, schema auto-created via `spring.integration.jdbc.initialize-schema: always`, not managed by the agent's schema migrations (after `upgrade-spring-boot-4`, owner answer 89.11 of 2026-10-08, the `INT_*` tables are created by the agent's Flyway migration V1 and `initialize-schema` is `never`)) holding opaque `manual-ingestion:<s3-key>:<etag>` dedupe markers. No document name, size, MIME type, status, chunk count, last-indexed timestamp, or failure reason exists anywhere.
2. **Deleting or re-indexing a document means operating the object store and Qdrant by hand.** There is no endpoint to remove a document's object from the `knowledge-base` bucket, its chunks from the `ascendai-768` / `ascendai-1536` collections, and its dedupe marker together. Re-ingest replaces old chunks (`ManualIngestionService.ingestIntoActiveCollection` calls `documentService.removeOldDocuments`), but only as a side effect of a full bucket scan.
3. **`POST /api/v1/ingestion/run` blocks the HTTP connection for the whole scan.** Docling / ascend-ocr processing of large PDFs runs minutes; the caller gets back only aggregate `{indexed, skipped, failed}` counts with no per-file failure detail and no way to check progress.

The sibling changes `add-keycloak-login` (ADMIN role, personal) and `add-tenant-isolation` (document ownership, company) both presuppose a document resource to protect and scope. This change creates that resource.

## What Changes

- **New document registry**: a Flyway-managed `documents` table (plus per-collection index state) becomes the source of truth for every knowledge-base document: the tenant (`tenant_id`, from `TenantContext` of `add-keycloak-login`), object key, display name, size, MIME type, source (`source_type` and `origin_uri`), ingestion status, per-collection chunk count and ETag, last-indexed-at, failure reason. `POST /api/v1/ingestion/upload` registers rows on upload; ingestion runs update them. The `source_type` and `origin_uri` given at registration (`upload`, `connector:<name>` from `add-connector-framework`, `web-download` from `add-download-ingestion`) are kept, and a later bucket-scan never overwrites them.
- **Chunk source field**: every ingestion run copies `source_type` from the registry row onto every chunk, and it gets a keyword payload index created at startup. The `connector_id` column, its chunk field and its index come with `add-connector-framework` (owner answer 93 of 2026-10-08).
- **`GET /api/v1/documents`** - paginated listing from the registry (name, size, MIME type, status, chunk count, last indexed at, source), with optional `status` and `sourceType` filters.
- **`GET /api/v1/documents/{id}`** - document detail including per-document ingestion outcome and failure reason.
- **`DELETE /api/v1/documents/{id}`** - removes Qdrant chunks (both collections where present), the stored object, and the registry row, in a retryable order; already-issued presigned source links are not revoked and simply stop resolving / expire.
- **`GET /api/v1/documents/{id}/content`** - authenticated, ownership-scoped download that streams the document's object bytes from object storage back through the agent. It is added alongside the presigned source URL, not in place of it: `AiResponse.sources[*]` (synchronous) and the streaming `sources` event gain the registry document id and this relative content path, while the mandatory non-blank `downloadUrl` and `expiresAt` that `rag-source-attachments` guarantees today stay exactly as they are. A caller therefore never has to implement two ways of fetching the same source (coordinated with `harden-cloud-deployment`'s gateway-only surface, `add-chat-streaming-and-conversations`'s `sources` event, and `add-tenant-isolation`'s ownership check).
- **`POST /api/v1/documents/{id}/reindex`** - single-document re-run through the `DocumentRouter` path, replacing prior chunks; returns a run id.
- **BREAKING**: `POST /api/v1/ingestion/run` becomes asynchronous - returns HTTP 202 with a run id instead of blocking and returning `ManualIngestionResult` counts.
- **`GET /api/v1/ingestion/runs/{id}`** - run status (`QUEUED` / `RUNNING` / `COMPLETED` / `FAILED`) with counts and per-file failures; **`GET /api/v1/ingestion/runs`** - small run-history listing.
- `ManualIngestionService` dedupe moves from `INT_METADATA_STORE` markers to registry ETag comparison, and the Spring Integration streaming pipeline (`config/IngestionPipelineConfig.java`) keeps its poller and its near-instant pickup but writes through the registry and the single-document run, so one store remembers what was ingested (owner answer 89.2 of 2026-10-08).
- Runs are queued as Postgres rows and claimed by one worker per agent instance, one run at a time in the deployment, with leases, a startup sweep and a periodic orphan sweep, so several agent instances share the queue safely (owner answer 87 of 2026-10-08).
- Authorization: this change adds its own rows to the authorization matrix of `add-keycloak-login` (ADMIN for delete and reindex, `USER` or `ADMIN` for the reads, design D11). Every registry and run table carries `tenant_id VARCHAR(64) NOT NULL`, written from `TenantContext.currentTenantId()` of `add-keycloak-login` (`default` in the personal deployment), with no foreign key. Per-tenant enforcement is company work of `add-tenant-isolation`, which adds the foreign keys and its checks later (see design Context).
- Every error of these endpoints is an RFC 7807 problem detail with a `code` from `ApiErrorCode` of `upgrade-spring-boot-4`. This change adds the one code `document_state_conflict` (409).
- The document management API is part of document search (`rag`), which belongs to the always-on core and is not a module (owner decision of 2026-10-03): its controllers, services and the run retention task carry no `@ConditionalOnModule` and no tenant module grant guards them.
- Run retention is the entry `ingestion-run` of the one retention task `record-retention` of `add-shared-scheduler` (owner answer 89.7 of 2026-10-08).

## Capabilities

### New Capabilities

- `document-management`: CRUD visibility and control over the RAG knowledge base - document registry, paginated listing, per-document detail and status, delete across object storage + Qdrant + metadata, single-document re-index, and the chunk payload extension point of design D15. The company-only `PUT /api/v1/documents/{id}/access` of owner decision 65.3 of 2026-10-04, by which a tenant `ADMIN` narrows a directly uploaded document to retrieval groups, is added later by `add-tenant-administration` (company, build group 5) through that extension point.

### Modified Capabilities

- `production-deployment` (created by `harden-cloud-deployment`, which lands earlier): the requirement "The object store is never public" gains the rule that public clients download RAG sources through the agent's `GET /api/v1/documents/{id}/content`.

- `ingestion-correctness`: ingestion runs become asynchronous jobs with observable status - `POST /api/v1/ingestion/run` returns 202 + run id; run status carries counts and per-file failures; a bounded run history is queryable. (Delta adds requirements; no existing requirement covered run semantics.)
- `rag-source-attachments`: source attachments gain the registry document id and the relative `/api/v1/documents/{id}/content` path as additional mandatory fields, on top of the mandatory non-blank `downloadUrl` and `expiresAt` the capability already guarantees. Both download paths are always present, so the client chooses one and implements only that one. (This is the download-mechanism half of the presign-resolution amendment. `add-tenant-isolation` layers the per-tenant ownership check onto the same endpoint.)

## Impact

- **New code (ascend-ai-agent)**:
  - `controller/DocumentController.java` (list, detail, delete, reindex, content download), `controller/IngestionController.java` (async `/run`, new `/runs` endpoints).
  - `service/ingestion/DocumentRegistryService.java`, `service/ingestion/DocumentDeletionService.java`, `service/ingestion/IngestionRunService.java`; refactor of `service/ingestion/ManualIngestionService.java`.
  - `repository/DocumentRepository.java`, `repository/DocumentIndexStateRepository.java`, `repository/IngestionRunRepository.java`; Spring Data JDBC entities under `model/`; DTOs under `dto/`.
  - `service/storage/StorageService.java` gains `deleteFile` and `getObjectBytes` (today it only has `uploadFile`).
- **Database**: new Flyway versioned SQL migration `apps/ascend-agent/src/main/resources/db/migration/V<n>__document_management.sql`, where `<n>` is the next free version after the highest migration present when this change is implemented, (tables `documents`, `document_index_state`, `ingestion_runs`, each with `tenant_id VARCHAR(64) NOT NULL` and no foreign key on it). Flyway finds it by location, so no master file lists it.
- **API**: one breaking change (`POST /api/v1/ingestion/run` response contract); five new endpoints.
- **Configuration**: every value with a default is a setting (owner rule 98 of 2026-10-08, design D17): the run worker lease renewal (10 seconds), lease length (60 seconds) and fallback check (30 seconds) of owner answer 98.4, the run retention, the failure detail cap, the page sizes of the two listings and the orphan sweep schedule, each written as `${ENV:default}` in `application.yaml` and passed as `${ENV:-default}` by the `ascend-agent` service of `compose.yaml`.
- **Docs / tooling**: `apps/ascend-agent/AGENTS.md` endpoint notes, the rows of design D17 in `apps/ascend-agent/docs/CONFIGURATION.md`, the run worker values in `docs/INGESTION.md`; Bruno requests under `docs/api/request/AscendAI/ascend-agent/`.
- **End-to-end tests**: new deterministic specs in `apps/ascend-agent/e2e/testing/` for the registry listing, run failures, delete, reindex, content download, plus in-place updates of `5-rag`, `6-attach-sources` and `7-rag-dedup`, whose text asserts the synchronous `/run` body, to the asynchronous run contract, keeping their numbers (owner answer 67.2 of 2026-10-04: a changed feature updates its existing specs).
- **Dependencies**: none new; uses existing Spring Data JDBC (`CrudRepository` with native `@Query`), Flyway, AWS SDK S3 client, Qdrant vector stores.
- **Sibling coordination**: `add-keycloak-login` provides the login and the matrix this change adds its rows to. `add-tenant-isolation` (company, build group 5) adds the foreign keys of the `tenant_id` columns and its ownership checks later. `add-tenant-administration` (company, build group 5) adds document access groups later through the chunk payload extension point. `add-connector-framework` builds on the registry's connector-friendly `source_type` and `origin_uri` fields, adds its own `connector_id` column, chunk field and payload index (owner answer 93 of 2026-10-08), and calls the bucket-scan entry point of `IngestionRunService`. `add-obsidian-vault` reads `source_type` and `connector_id` on chunks. `add-download-ingestion` adds `POST /api/v1/documents/from-download`, which registers a `web-download` row and starts a single-document run.

## Build order and security gap

Build order (owner build order of 2026-10-04, which supersedes the earlier orders and the group D chain): build group 3 (base), position 8 (owner answer 94.5 of 2026-10-08). It needs `upgrade-spring-boot-4` (group 3, position 2: Flyway, which replaces Liquibase in ascend-agent, and the RFC 7807 problem detail with `ApiErrorCode`), `add-keycloak-login` (group 3, position 3: the login, the role matrix and `TenantContext`), `add-deployment-modules` (group 3, position 6: the module list, in which `rag` is core) and `add-shared-scheduler` (group 3, position 7: the system task that runs the run retention). `add-chat-streaming-and-conversations` (group 3, position 9) lands right after it and its `sources` event carries this change's `documentId` and `contentPath`. In build group 4, `add-connector-framework`, `add-download-ingestion`, `add-obsidian-vault` and `add-passage-level-citations` build on its registry and its runs. Company work of build group 5 (`add-tenant-isolation`, `add-tenant-administration`) plugs in later. This change does not wait for it.

The destructive endpoints (`DELETE /api/v1/documents/{id}`, `POST /api/v1/documents/{id}/reindex`, `POST /api/v1/ingestion/run`) need the `ADMIN` role of `add-keycloak-login`, which lands before this change, through this change's own matrix rows (design D11). Ownership checks per tenant come with the company change `add-tenant-isolation`, and a personal deployment has one tenant.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/api-design`
- `/postgres-patterns`
- `/database-migrations`
- `/tdd-workflow`
