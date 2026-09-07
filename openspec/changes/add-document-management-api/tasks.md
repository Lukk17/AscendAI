## 1. Database schema and entities

- [ ] 1.1 Create `AscendAgent/src/main/resources/db/changelog/02-document-management.xml` with tables `documents` (UUID pk, unique `object_key`, `display_name`, `size_bytes`, `mime_type`, `source_type`, `origin_uri` nullable, `status`, `failure_reason` nullable, `created_at`, `updated_at`), `document_index_state` (fk to documents, `collection_name`, `chunk_count`, `etag`, `last_indexed_at`, unique `(document_id, collection_name)`), and `ingestion_runs` (UUID pk, `state`, `scope_prefix` nullable, `document_id` nullable, `embedding_provider`, `indexed_count`, `skipped_count`, `failed_count`, `failures` JSONB, `requested_at`, `started_at` nullable, `finished_at` nullable); include indexes on `documents.status` and `ingestion_runs.requested_at`
- [ ] 1.2 Include the new changelog from `db.changelog-master.yaml`
- [ ] 1.3 Add JPA entities `Document`, `DocumentIndexState`, `IngestionRun` under `model/` with status/state enums, and repositories `DocumentRepository`, `DocumentIndexStateRepository`, `IngestionRunRepository` under `repository/`
- [ ] 1.4 Integration test (Testcontainers Postgres): Liquibase migration applies cleanly on an empty database and entities round-trip through the repositories

## 2. Document registry service

- [ ] 2.1 Create `service/ingestion/DocumentRegistryService.java`: upsert-on-upload (key, name, size, MIME type, `source_type=upload`, status `UPLOADED`), upsert-on-scan (`source_type=bucket-scan` when creating), mark `INDEXING`, record success (status `INDEXED`, per-collection chunk count + ETag + `last_indexed_at`), record failure (status `FAILED`, failure reason, prior index state untouched)
- [ ] 2.2 Wire `IngestionController.uploadDocument` to register each successfully stored file via `DocumentRegistryService` using the sanitized key and the sniffed MIME type from `MimeTypeDetector`
- [ ] 2.3 Unit tests: upload registers a row; re-upload of the same key updates size/MIME without duplicating rows; failure recording preserves prior chunk count and ETag

## 3. Async ingestion runs (BREAKING /run)

- [ ] 3.1 Create `service/ingestion/IngestionRunService.java`: persist a `QUEUED` run, execute on a dedicated single-threaded executor, transition `QUEUED` → `RUNNING` → `COMPLETED`/`FAILED`, record counts and capped `{objectKey, reason}` failure entries, and expose run lookup + newest-first history with `limit` (default 20, max 100)
- [ ] 3.2 Refactor `ManualIngestionService`: report per-object outcomes (indexed chunk count, skipped, failed with reason) to the run record and to `DocumentRegistryService`; replace the `metadataStore.putIfAbsent` dedupe and stale-marker cleanup in `processObject` with `document_index_state` ETag comparison per target collection (drop the `ConcurrentMetadataStore` dependency from this class; `IngestionPipelineConfig` untouched)
- [ ] 3.2a Route every scanned object through `DocumentRouter.routeAndProcess` in `processObject` (close the bypass gap): remove any default/plain-parser fallback so scanned PDFs, Office files, images, and e-mail land on the same routed parse path as uploads and reindex
- [ ] 3.2b Test: a `.docx` and a scanned PDF dropped into the bucket are ingested via `DocumentRouter` (Docling / ascend-ocr), not a raw/plain parser
- [ ] 3.3 Change `POST /api/v1/ingestion/run` in `IngestionController` to create a run and return 202 with `{runId}` and a `Location: /api/v1/ingestion/runs/{id}` header; remove the synchronous `ManualIngestionResult` response
- [ ] 3.4 Add `GET /api/v1/ingestion/runs/{id}` (404 for unknown id) and `GET /api/v1/ingestion/runs` with run DTOs under `dto/`
- [ ] 3.5 Add a startup sweep (`ApplicationReadyEvent`) marking leftover `QUEUED`/`RUNNING` runs as `FAILED` with an interrupted-by-restart reason
- [ ] 3.5a Replica-safety: stamp each run with an owner instance id + heartbeat/lease when it transitions to `RUNNING`; the startup sweep SHALL only reclaim runs whose owner lease has expired, so a second agent instance never marks another live instance's in-flight run as `FAILED`. Test two-instance behavior with a stubbed clock/lease
- [ ] 3.6 Unit tests: dedupe skips on matching ETag, retries after failure (ETag not advanced); runs execute serially; failure list capped at 100 while `failed_count` stays exact
- [ ] 3.7 Integration test (Testcontainers Postgres/MinIO/Qdrant): `POST /run` returns 202 immediately, `GET /runs/{id}` transitions `QUEUED`/`RUNNING` → `COMPLETED` with correct `{indexed, skipped, failed}` counts and per-file failure entries for a seeded bucket containing one good and one poisoned object
- [ ] 3.8 Integration test: restart-sweep marks a `RUNNING` row `FAILED` on context refresh

## 4. Document listing and detail endpoints

- [ ] 4.1 Create `controller/DocumentController.java` with `GET /api/v1/documents` (Pageable, default size 20 / max 100, `status` filter, `{items, page, size, totalElements, totalPages}` response) and `GET /api/v1/documents/{id}` (full record with per-collection index state and failure reason; 404 unknown)
- [ ] 4.2 Add listing/detail DTOs under `dto/` (aggregate total chunk count and max `last_indexed_at` for listing items)
- [ ] 4.3 MockMvc tests: listing fields and pagination bounds, `status=FAILED` filter, detail for indexed / failed / unknown documents

## 5. Delete endpoint

- [ ] 5.1 Add `deleteFile(String key)` to `service/storage/StorageService.java`
- [ ] 5.2 Create `service/ingestion/DocumentDeletionService.java` implementing the resumable order: set `DELETING` → delete Qdrant points (`source == object_key`) from every collection in the document's index state → delete MinIO object → delete index-state rows and document row; every step idempotent so repeating the DELETE finishes a partial delete
- [ ] 5.3 Wire `DELETE /api/v1/documents/{id}` in `DocumentController`: 204 on completion, 404 unknown, 409 when status is `INDEXING`
- [ ] 5.4 Integration test (Testcontainers Qdrant/MinIO/Postgres): ingest a document into both collections, delete it, assert the Qdrant point count for `metadata.source == <key>` drops to zero in both collections, the MinIO object is gone, and detail returns 404
- [ ] 5.5 Integration test: force a failure between vector and object deletion, assert status stays `DELETING`, then retry the DELETE and assert it completes
- [ ] 5.6 Unit test: 409 returned for `INDEXING` documents with no side effects

## 6. Reindex endpoint

- [ ] 6.1 Add `getObjectBytes(String key)` to `StorageService` (or reuse the S3 client read path) for reindex fetches
- [ ] 6.2 Implement single-document reindex in `IngestionRunService`: run with `document_id` set, fetch bytes from MinIO, process via `DocumentRouter.routeAndProcess`, split via `DocumentService.splitDocuments`, `removeOldDocuments` then add into the collection resolved by `VectorStoreResolver`; bypass ETag dedupe; update registry status `INDEXING` → `INDEXED`/`FAILED`
- [ ] 6.3 Wire `POST /api/v1/documents/{id}/reindex` in `DocumentController`: 202 with run id, 404 unknown, 409 when status is `DELETING`
- [ ] 6.4 Integration test: reindex an already-indexed document and assert the Qdrant point count for its source equals the new run's chunk count (replacement, not accumulation) and `last_indexed_at` advanced
- [ ] 6.5 Unit tests: reindex proceeds despite unchanged ETag; 409 during `DELETING`; failed reindex sets `FAILED` with reason and preserves prior index state

## 6b. Authenticated content download and source-attachment rewiring (presign resolution)

- [ ] 6b.1 Add `GET /api/v1/documents/{id}/content` to `DocumentController`: resolve the object key from the registry, fetch bytes via `StorageService.getObjectBytes`, stream the response with the stored `Content-Type` and a `Content-Disposition` naming the display name; 404 for unknown or deleted ids; no redirect to MinIO
- [ ] 6b.2 Extend `SourceFile` DTO with mandatory `documentId` and `contentPath` (`/api/v1/documents/{id}/content`), leaving `downloadUrl` and `expiresAt` mandatory and non-blank as they are today; keep `@JsonInclude(NON_NULL)` so only the unknown `sizeBytes` is ever omitted
- [ ] 6b.3 In `RagRetrievalService.buildSourceRefs` (and the streaming source path), resolve the registry `documentId` from each source object key and emit `contentPath`; omit a source whose object key has no registry row with a single WARN referencing `s3://{bucket}/{key}`
- [ ] 6b.4 Keep presigning on the client-facing path unconditionally: no flag, no opt-out, and a source that cannot be presigned is dropped by the existing best-effort rule rather than returned without a link
- [ ] 6b.5 Integration test (Testcontainers MinIO/Postgres): `attachSources=true` returns sources carrying non-blank `documentId`, `contentPath`, `downloadUrl`, and `expiresAt`; a `GET` on `contentPath` streams the bytes through the agent (no redirect) and a `GET` on `downloadUrl` returns the identical bytes; a deleted document's `contentPath` returns 404
- [ ] 6b.6 Unit test: a retrieved chunk whose source object has no registry row is omitted from `sources` with a WARN, request still 200

## 7. Documentation and API collection

- [ ] 7.1 Update `AscendAgent/AGENTS.md`: document the new `/api/v1/documents` endpoints, the async `/api/v1/ingestion/run` contract, and the registry tables
- [ ] 7.2 Add Bruno requests under `docs/api/request/AscendAI/ascend-agent/`: list documents, document detail, delete document, reindex document, run ingestion (async), get run status, list runs; update the existing run-ingestion request for the 202 contract
- [ ] 7.3 Update `AscendAgent/e2e/` specs that assert on the synchronous `/run` response (poll `GET /api/v1/ingestion/runs/{id}` instead) and note the change in `e2e/README.md` if the capability matrix mentions run semantics
- [ ] 7.4 Release note in the proposal-linked docs: first run after deploy backfills the registry and re-indexes existing objects once (one-time embedding cost); `POST /api/v1/ingestion/run` response contract is breaking
