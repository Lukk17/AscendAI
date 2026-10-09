## ADDED Requirements

### Requirement: Document registry records every knowledge-base document

The agent SHALL maintain a Flyway-managed document registry in PostgreSQL that records, for every document in the knowledge base: a stable document id, the stored object key, display name, size in bytes, MIME type, source type (`upload`, `bucket-scan`, `web-download`, or a connector-provided value of the form `connector:<name>` such as `connector:obsidian`), origin URI when one was given, ingestion status (`UPLOADED`, `INDEXING`, `INDEXED`, `FAILED`, `DELETING`), failure reason when failed, and per-collection chunk count, ETag, and last-indexed-at. Every registry and run row SHALL carry the tenant that `TenantContext.currentTenantId()` answers when the row is created. `POST /api/v1/ingestion/upload` SHALL register or update the row at upload time; ingestion runs SHALL upsert rows for every object they visit and update index state on success or failure. The registry SHALL keep the source type and origin URI given at registration: a bucket-scan upsert SHALL set `bucket-scan` only when it creates the row, and SHALL NOT overwrite the source type or origin URI of a row that exists, nor any column another change adds to the row.

#### Scenario: Upload registers a document

- **WHEN** a user uploads `notes.md` via `POST /api/v1/ingestion/upload`
- **THEN** a `documents` row exists with `object_key` ending in `notes.md`, status `UPLOADED`, and the file's size and MIME type
- **AND** the chunk count for the document is zero until an ingestion run indexes it

#### Scenario: Bucket-scan run registers an object dropped into the bucket

- **WHEN** an object was dropped into the `knowledge-base` bucket out-of-band with no registry row and an ingestion run scans it
- **THEN** a registry row is created for that object
- **AND** after successful indexing the row has status `INDEXED`, a non-zero chunk count for the target collection, and a `last_indexed_at` timestamp

#### Scenario: Bucket scan keeps the source given at registration

- **WHEN** the connector framework of `add-connector-framework` registers a landed note with source type `connector:obsidian` and an origin URI, and a later bucket-scan run visits the same object key
- **THEN** the registry row still carries source type `connector:obsidian` and that origin URI

#### Scenario: Failed ingestion records the reason

- **WHEN** an ingestion run fails to process a registered document (e.g. Docling returns an error)
- **THEN** the document's status is `FAILED`
- **AND** the row's failure reason is non-empty
- **AND** the previously indexed chunks and ETag for that document remain unchanged

### Requirement: Documents can be listed with pagination

The agent SHALL expose `GET /api/v1/documents` returning a paginated listing from the document registry. Each item SHALL include the document id, display name, size in bytes, MIME type, ingestion status, total chunk count across collections, most recent last-indexed-at, and source. The endpoint SHALL accept `page` and `size` query parameters (a configured default size, default 20, and a configured maximum, default 100), a `status` filter and a `sourceType` filter that matches the source type exactly, and SHALL return `{items, page, size, totalElements, totalPages}`. A parameter out of range or of unknown value SHALL answer HTTP 400 with an RFC 7807 problem detail whose `code` is `validation`.

#### Scenario: Default listing

- **WHEN** `GET /api/v1/documents` is invoked with 3 documents in the registry
- **THEN** the response status is 200
- **AND** `items` contains 3 entries each carrying id, name, size, MIME type, status, chunk count, last indexed at, and source
- **AND** `totalElements` equals 3

#### Scenario: Pagination bounds respected

- **WHEN** `GET /api/v1/documents?page=0&size=2` is invoked with 3 documents in the registry
- **THEN** `items` contains 2 entries, `totalPages` equals 2, and requesting `page=1` returns the remaining entry

#### Scenario: Status filter

- **WHEN** `GET /api/v1/documents?status=FAILED` is invoked
- **THEN** every returned item has status `FAILED`

#### Scenario: Source type filter

- **WHEN** `GET /api/v1/documents?sourceType=connector:obsidian` is invoked while the registry holds uploaded documents and documents landed by an Obsidian connector
- **THEN** every returned item has source type `connector:obsidian`

#### Scenario: Page size above the maximum

- **WHEN** `GET /api/v1/documents?size=101` is invoked
- **THEN** the response status is 400 with `code` `validation`

### Requirement: Document detail exposes per-document ingestion outcome

The agent SHALL expose `GET /api/v1/documents/{id}` returning the full registry record for one document: all listing fields plus the object key, per-collection index state (collection name, chunk count, ETag, last indexed at), and the failure reason when status is `FAILED`. Unknown ids SHALL return HTTP 404 with `code` `not_found`.

#### Scenario: Detail for an indexed document

- **WHEN** `GET /api/v1/documents/{id}` is invoked for a document indexed into `ascendai-768`
- **THEN** the response status is 200
- **AND** the body includes per-collection state showing `ascendai-768` with a non-zero chunk count and a last-indexed-at timestamp

#### Scenario: Detail for a failed document

- **WHEN** `GET /api/v1/documents/{id}` is invoked for a document whose last ingestion failed
- **THEN** the body shows status `FAILED` and a non-empty failure reason

#### Scenario: Unknown id

- **WHEN** `GET /api/v1/documents/{id}` is invoked with an id not in the registry
- **THEN** the response status is 404 with an RFC 7807 problem detail whose `code` is `not_found`

### Requirement: Document deletion removes storage, vectors, and metadata

The agent SHALL expose `DELETE /api/v1/documents/{id}` which removes, in order: the document's Qdrant chunks (filter `source == <object key>`) from every collection recorded in its index state, the stored object, and finally the registry row. The endpoint SHALL return 204 on completion, 404 with `code` `not_found` for an unknown id, and 409 with `code` `document_state_conflict` when the document's status is `INDEXING`. After deletion, subsequent RAG retrievals SHALL NOT return chunks for the deleted document.

#### Scenario: Delete removes vectors from both collections

- **WHEN** a document indexed into both `ascendai-768` and `ascendai-1536` is deleted via `DELETE /api/v1/documents/{id}`
- **THEN** the response status is 204
- **AND** the count of Qdrant points with `metadata.source == <object key>` is zero in both collections
- **AND** the stored object no longer exists in the `knowledge-base` bucket
- **AND** `GET /api/v1/documents/{id}` returns 404

#### Scenario: Delete rejected while indexing

- **WHEN** `DELETE /api/v1/documents/{id}` is invoked while the document's status is `INDEXING`
- **THEN** the response status is 409 with `code` `document_state_conflict`
- **AND** no chunks, object, or registry row are removed

### Requirement: Deletion is retryable and safe mid-chat

Deletion SHALL set the document's status to `DELETING` before executing removal steps, each of which is idempotent. A failure part-way SHALL leave the row in `DELETING`, and repeating the DELETE SHALL re-execute the remaining steps to completion. The agent SHALL NOT track or revoke presigned source URLs already handed out in chat responses: they stop resolving once the stored object is removed and expire within the configured presign TTL regardless. In-flight chat turns that already retrieved the document's chunks SHALL complete normally.

#### Scenario: Retry after partial failure completes the delete

- **WHEN** a delete removes the Qdrant chunks but fails before removing the stored object
- **THEN** `GET /api/v1/documents/{id}` shows status `DELETING`
- **AND** repeating `DELETE /api/v1/documents/{id}` removes the stored object and the registry row and returns 204

#### Scenario: Previously issued presigned link after delete

- **WHEN** a chat response included a presigned source URL for a document that is subsequently deleted
- **THEN** the delete succeeds without waiting for or revoking the URL
- **AND** the URL stops returning the object content (the object store reports the object missing or the link expires at its TTL)

### Requirement: Single-document re-index through the DocumentRouter path

The agent SHALL expose `POST /api/v1/documents/{id}/reindex` which re-processes exactly one document: fetch the object bytes from object storage, process via `DocumentRouter.routeAndProcess` (extension-based routing to Markdown, Docling, ascend-ocr, Unstructured, or per-page PDF dispatch), split, remove the document's prior chunks for the target collection, and add the new chunks. Reindex SHALL bypass ETag deduplication, SHALL execute asynchronously returning HTTP 202 with a run id, SHALL set the document's status to `INDEXING` while running, and SHALL return 404 with `code` `not_found` for unknown ids and 409 with `code` `document_state_conflict` when the document's status is `DELETING`.

#### Scenario: Reindex replaces chunks

- **WHEN** `POST /api/v1/documents/{id}/reindex` is invoked for an already-indexed document and the run completes
- **THEN** the initial response status is 202 with a run id in the body
- **AND** the count of Qdrant points with `metadata.source == <object key>` in the target collection equals the chunk count of the new run (not the sum of old and new)
- **AND** the document's status returns to `INDEXED` with an updated `last_indexed_at`

#### Scenario: Reindex ignores unchanged ETag

- **WHEN** a document is reindexed without its stored object having changed
- **THEN** the run processes the document anyway (it is not skipped as a duplicate)

#### Scenario: Reindex rejected during deletion

- **WHEN** `POST /api/v1/documents/{id}/reindex` is invoked while the document's status is `DELETING`
- **THEN** the response status is 409 with `code` `document_state_conflict`
- **AND** no ingestion run is created

### Requirement: Authenticated document content download

The agent SHALL expose `GET /api/v1/documents/{id}/content` which streams the bytes of the document's stored object back through the agent with the object's `Content-Type` and a `Content-Disposition` naming the display name. The endpoint SHALL resolve the object key from the registry, fetch it from object storage server-side, and stream it without redirecting the caller to object storage. It SHALL return 404 for an unknown id and 404 once the document has been deleted. This endpoint is offered alongside the presigned object-store URL that `rag-source-attachments` already guarantees, not instead of it: every source entry carries both, so a client picks whichever suits its network and never implements a fallback. Authorization (authenticated caller) is this change's row in the matrix of `add-keycloak-login`, and per-tenant ownership enforcement is layered by the company change `add-tenant-isolation`.

#### Scenario: Content download streams the object through the agent

- **WHEN** `GET /api/v1/documents/{id}/content` is invoked for an indexed document
- **THEN** the response status is 200 with the object's `Content-Type`
- **AND** the body is the file's bytes
- **AND** the response is served by the agent (no HTTP redirect to an object storage host)

#### Scenario: Content download after deletion

- **WHEN** `GET /api/v1/documents/{id}/content` is invoked for a document that has been deleted
- **THEN** the response status is 404

### Requirement: Chunks carry the document's source type

Every ingestion run SHALL copy the source type from the document's registry row onto every chunk it writes, under the payload key `source_type`. The key SHALL have a keyword payload index on every RAG collection, created at application startup. The connector id of a connector document is added by the connector framework through the chunk payload extension point.

#### Scenario: Connector-landed chunks carry the source type

- **WHEN** an ingestion run indexes a document registered with source type `connector:obsidian`
- **THEN** every chunk of that document carries `source_type` `connector:obsidian`

#### Scenario: Uploaded chunks carry the source type

- **WHEN** an ingestion run indexes a document uploaded through `POST /api/v1/ingestion/upload`
- **THEN** every chunk carries `source_type` `upload`

#### Scenario: Payload index exists after startup

- **WHEN** the application has started
- **THEN** every RAG collection has a keyword payload index on `source_type`

### Requirement: Document management is part of the core document search and answers problem details

The document and ingestion run endpoints, their services, the run orphan sweep and the run retention entry SHALL be part of the core document search (`rag`), which is always on and is not a module. They SHALL carry no `@ConditionalOnModule`, SHALL exist whatever `ASCEND_MODULES` holds, and SHALL NOT be guarded by a tenant module grant. Every error body of these endpoints SHALL be the RFC 7807 problem detail of `upgrade-spring-boot-4`, sent as `application/problem+json` with the top level `code` from `ApiErrorCode`.

#### Scenario: Present without any switchable module

- **WHEN** the agent starts with an `ASCEND_MODULES` that holds no switchable module
- **THEN** `GET /api/v1/documents` is served
- **AND** the system task `ingestion-run-orphan-sweep` and the retention entry `ingestion-run` are registered

#### Scenario: Error body is a problem detail

- **WHEN** `DELETE /api/v1/documents/{id}` is invoked while the document's status is `INDEXING`
- **THEN** the `Content-Type` is `application/problem+json`
- **AND** the body carries `type` `https://ascend.ai/errors/document-state-conflict`, `status` 409, a `detail` and `code` `document_state_conflict`

### Requirement: Document management is verified end to end against a live stack

Every user-visible behaviour of the document and ingestion run endpoints SHALL be covered by an end-to-end spec in the ascend-agent suite under `apps/ascend-agent/e2e/testing/`, numbered with the next free number when it is written. These specs SHALL be deterministic: their pass criteria SHALL be HTTP status, response body and persisted state in Postgres, Qdrant and the object store, and SHALL NOT be a log line or the wording of a model answer. A spec that sends a prompt SHALL judge only the `sources` array. The ascend-agent specs `5-rag`, `6-attach-sources` and `7-rag-dedup` SHALL be updated in place, keeping their numbers, to use the asynchronous run contract, and no successor spec SHALL be written for them.

#### Scenario: Upload, run, list and filter

- **WHEN** the registry listing spec uploads two Markdown canaries, starts a run scoped to their prefix and polls it
- **THEN** the run request answers 202 with a run id and a `Location` header, and the run ends `COMPLETED` with `indexed` 2 and `failed` 0
- **AND** the listing shows both documents `INDEXED` with a chunk count above zero, pages and filters by `status` and `sourceType`, and answers `size=101` with 400 `validation`
- **AND** a second identical run reports both documents as skipped

#### Scenario: An object dropped into the bucket is registered by a run

- **WHEN** the registry listing spec puts a canary straight into the bucket and starts a run
- **THEN** the document's row has source type `bucket-scan` and status `INDEXED`

#### Scenario: A failed object is reported and retried

- **WHEN** the failure reporting spec runs over a valid canary and a file with a `.pdf` name whose bytes are not a PDF
- **THEN** the run ends `COMPLETED` with `failed` 1 and a failure entry naming the broken file with a reason
- **AND** the broken document's detail reads `FAILED` with a failure reason, and a second run tries it again

#### Scenario: Delete leaves no trace

- **WHEN** the delete spec deletes an indexed canary
- **THEN** the response is 204, no Qdrant point keeps its `source`, the object is gone from the bucket, and detail and content answer 404
- **AND** a later prompt with `attachSources=true` lists no source with that document id

#### Scenario: Reindex replaces chunks

- **WHEN** the reindex spec reindexes an indexed canary and polls the returned run
- **THEN** the Qdrant point count for the document equals the new run's chunk count, and `lastIndexedAt` moved forward

#### Scenario: Both download paths return the same bytes

- **WHEN** the content download spec fetches an indexed canary through `/api/v1/documents/{id}/content` and through the `downloadUrl` of a source entry
- **THEN** the agent answers 200 with no redirect and the two bodies are byte-identical to the fixture
- **AND** a source whose registry row was removed is left out of `sources` while the prompt still answers 200


### Requirement: Chunk payload can be extended without editing the ingestion runs

Every ingestion run SHALL ask every registered chunk payload contributor for extra payload fields of each chunk it writes, after it has set the source and the source type, and SHALL NOT let a contributor replace one of those fields. With no contributor registered, a run SHALL write exactly the fields this capability defines. A contributor SHALL be added by registering a bean, with no edit of the ingestion runs.

#### Scenario: No contributor, no extra field

- **WHEN** a document is indexed in a deployment that registers no chunk payload contributor
- **THEN** its chunks carry only the fields this capability defines

#### Scenario: A registered contributor adds a field on reindex

- **WHEN** a test contributor that adds one field is registered and an indexed document is reindexed
- **THEN** every new chunk of the document carries that field and its source and source type are unchanged

