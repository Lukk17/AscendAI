## Why

The RAG knowledge base is write-only. The only ingestion endpoints are `POST /api/v1/ingestion/upload` (multipart to MinIO) and `POST /api/v1/ingestion/run` (synchronous full-bucket scan) in `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/controller/IngestionController.java`; a grep for `@GetMapping` / `@DeleteMapping` / `@PutMapping` across `AscendAgent/src/main/java` returns zero matches. Three concrete consequences:

1. **Nobody can see what is indexed.** The only ingestion state today is Spring Integration's `INT_METADATA_STORE` key-value table (`JdbcMetadataStore` bean in `config/AppConfig.java`, schema auto-created via `spring.integration.jdbc.initialize-schema: always`, not Liquibase-managed) holding opaque `manual-ingestion:<s3-key>:<etag>` dedupe markers. No document name, size, MIME type, status, chunk count, last-indexed timestamp, or failure reason exists anywhere.
2. **Deleting or re-indexing a document means operating MinIO and Qdrant by hand.** There is no endpoint to remove a document's object from the `knowledge-base` bucket, its chunks from the `ascendai-768` / `ascendai-1536` collections, and its dedupe marker together. Re-ingest replaces old chunks (`ManualIngestionService.ingestIntoActiveCollection` calls `documentService.removeOldDocuments`), but only as a side effect of a full bucket scan.
3. **`POST /api/v1/ingestion/run` blocks the HTTP connection for the whole scan.** Docling / PaddleOCR processing of large PDFs runs minutes; the caller gets back only aggregate `{indexed, skipped, failed}` counts with no per-file failure detail and no way to check progress.

The sibling changes `add-auth-and-identity` (ADMIN role) and `add-tenant-isolation` (document ownership) both presuppose a document resource to protect and scope. This change creates that resource.

## What Changes

- **New document registry**: a Liquibase-managed `documents` table (plus per-collection index state) becomes the source of truth for every knowledge-base document: object key, display name, size, MIME type, source, ingestion status, per-collection chunk count and ETag, last-indexed-at, failure reason. `POST /api/v1/ingestion/upload` registers rows on upload; ingestion runs update them.
- **`GET /api/v1/documents`** — paginated listing from the registry (name, size, MIME type, status, chunk count, last indexed at, source).
- **`GET /api/v1/documents/{id}`** — document detail including per-document ingestion outcome and failure reason.
- **`DELETE /api/v1/documents/{id}`** — removes Qdrant chunks (both collections where present), the MinIO object, and the registry row, in a retryable order; already-issued presigned source links are not revoked and simply stop resolving / expire.
- **`GET /api/v1/documents/{id}/content`** — authenticated, ownership-scoped download that streams the document's MinIO object bytes back through the agent. It is added alongside the presigned source URL, not in place of it: `AiResponse.sources[*]` (synchronous) and the streaming `sources` event gain the registry document id and this relative content path, while the mandatory non-blank `downloadUrl` and `expiresAt` that `rag-source-attachments` guarantees today stay exactly as they are. A caller therefore never has to implement two ways of fetching the same source (coordinated with `harden-cloud-deployment`'s gateway-only surface, `add-chat-streaming-and-conversations`'s `sources` event, and `add-tenant-isolation`'s ownership check).
- **`POST /api/v1/documents/{id}/reindex`** — single-document re-run through the `DocumentRouter` path, replacing prior chunks; returns a run id.
- **BREAKING**: `POST /api/v1/ingestion/run` becomes asynchronous — returns HTTP 202 with a run id instead of blocking and returning `ManualIngestionResult` counts.
- **`GET /api/v1/ingestion/runs/{id}`** — run status (`QUEUED` / `RUNNING` / `COMPLETED` / `FAILED`) with counts and per-file failures; **`GET /api/v1/ingestion/runs`** — small run-history listing.
- `ManualIngestionService` dedupe moves from `INT_METADATA_STORE` markers to registry ETag comparison; the Spring Integration streaming pipeline (`config/IngestionPipelineConfig.java`) keeps its metadata-store filter untouched.
- Authorization (ADMIN for delete / reindex / run) and tenant scoping are consumed from the sibling changes, not re-specified here; the schema reserves room for the ownership column (see design Context).

## Capabilities

### New Capabilities

- `document-management`: CRUD visibility and control over the RAG knowledge base — document registry, paginated listing, per-document detail and status, delete across MinIO + Qdrant + metadata, single-document re-index.

### Modified Capabilities

- `ingestion-correctness`: ingestion runs become asynchronous jobs with observable status — `POST /api/v1/ingestion/run` returns 202 + run id; run status carries counts and per-file failures; a bounded run history is queryable. (Delta adds requirements; no existing requirement covered run semantics.)
- `rag-source-attachments`: source attachments gain the registry document id and the relative `/api/v1/documents/{id}/content` path as additional mandatory fields, on top of the mandatory non-blank `downloadUrl` and `expiresAt` the capability already guarantees. Both download paths are always present, so the client chooses one and implements only that one. (This is the download-mechanism half of the presign-resolution amendment. `add-tenant-isolation` layers the per-tenant ownership check onto the same endpoint.)

## Impact

- **New code (AscendAgent)**:
  - `controller/DocumentController.java` (list, detail, delete, reindex, content download), `controller/IngestionController.java` (async `/run`, new `/runs` endpoints).
  - `service/ingestion/DocumentRegistryService.java`, `service/ingestion/DocumentDeletionService.java`, `service/ingestion/IngestionRunService.java`; refactor of `service/ingestion/ManualIngestionService.java`.
  - `repository/DocumentRepository.java`, `repository/DocumentIndexStateRepository.java`, `repository/IngestionRunRepository.java`; entities under `model/`; DTOs under `dto/`.
  - `service/storage/StorageService.java` gains `deleteFile` and `getObjectBytes` (today it only has `uploadFile`).
- **Database**: new Liquibase changelog `AscendAgent/src/main/resources/db/changelog/02-document-management.xml` (tables `documents`, `document_index_state`, `ingestion_runs`) included from `db.changelog-master.yaml`.
- **API**: one breaking change (`POST /api/v1/ingestion/run` response contract); five new endpoints.
- **Docs / tooling**: `AscendAgent/AGENTS.md` endpoint notes; Bruno requests under `docs/api/request/AscendAI/ascend-agent/`.
- **Dependencies**: none new; uses existing Spring Data JPA, Liquibase, AWS SDK S3 client, Qdrant vector stores.
- **Sibling coordination**: `add-auth-and-identity` guards the mutating endpoints; `add-tenant-isolation` adds the ownership column to `documents`; `add-document-connectors` builds on the registry's connector-friendly `source_type` / `origin_uri` fields.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/api-design`
- `/jpa-patterns`
- `/database-migrations`
- `/springboot-tdd`
