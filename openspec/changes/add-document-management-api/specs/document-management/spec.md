## ADDED Requirements

### Requirement: Document registry records every knowledge-base document

The agent SHALL maintain a Liquibase-managed document registry in PostgreSQL that records, for every document in the knowledge base: a stable document id, the MinIO object key, display name, size in bytes, MIME type, source (`upload`, `bucket-scan`, or a connector-provided value), ingestion status (`UPLOADED`, `INDEXING`, `INDEXED`, `FAILED`, `DELETING`), failure reason when failed, and per-collection chunk count, ETag, and last-indexed-at. `POST /api/v1/ingestion/upload` SHALL register or update the row at upload time; ingestion runs SHALL upsert rows for every object they visit and update index state on success or failure.

#### Scenario: Upload registers a document

- **WHEN** a user uploads `notes.md` via `POST /api/v1/ingestion/upload`
- **THEN** a `documents` row exists with `object_key` ending in `notes.md`, status `UPLOADED`, and the file's size and MIME type
- **AND** the chunk count for the document is zero until an ingestion run indexes it

#### Scenario: Bucket-scan run backfills pre-existing objects

- **WHEN** an object exists in the `knowledge-base` bucket with no registry row and an ingestion run scans it
- **THEN** a registry row is created for that object
- **AND** after successful indexing the row has status `INDEXED`, a non-zero chunk count for the target collection, and a `last_indexed_at` timestamp

#### Scenario: Failed ingestion records the reason

- **WHEN** an ingestion run fails to process a registered document (e.g. Docling returns an error)
- **THEN** the document's status is `FAILED`
- **AND** the row's failure reason is non-empty
- **AND** the previously indexed chunks and ETag for that document remain unchanged

### Requirement: Documents can be listed with pagination

The agent SHALL expose `GET /api/v1/documents` returning a paginated listing from the document registry. Each item SHALL include the document id, display name, size in bytes, MIME type, ingestion status, total chunk count across collections, most recent last-indexed-at, and source. The endpoint SHALL accept `page` and `size` query parameters (default size 20, maximum 100) and a `status` filter, and SHALL return `{items, page, size, totalElements, totalPages}`.

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

### Requirement: Document detail exposes per-document ingestion outcome

The agent SHALL expose `GET /api/v1/documents/{id}` returning the full registry record for one document: all listing fields plus the object key, per-collection index state (collection name, chunk count, ETag, last indexed at), and the failure reason when status is `FAILED`. Unknown ids SHALL return HTTP 404.

#### Scenario: Detail for an indexed document

- **WHEN** `GET /api/v1/documents/{id}` is invoked for a document indexed into `ascendai-768`
- **THEN** the response status is 200
- **AND** the body includes per-collection state showing `ascendai-768` with a non-zero chunk count and a last-indexed-at timestamp

#### Scenario: Detail for a failed document

- **WHEN** `GET /api/v1/documents/{id}` is invoked for a document whose last ingestion failed
- **THEN** the body shows status `FAILED` and a non-empty failure reason

#### Scenario: Unknown id

- **WHEN** `GET /api/v1/documents/{id}` is invoked with an id not in the registry
- **THEN** the response status is 404

### Requirement: Document deletion removes storage, vectors, and metadata

The agent SHALL expose `DELETE /api/v1/documents/{id}` which removes, in order: the document's Qdrant chunks (filter `source == <object key>`) from every collection recorded in its index state, the MinIO object, and finally the registry row. The endpoint SHALL return 204 on completion, 404 for an unknown id, and 409 when the document's status is `INDEXING`. After deletion, subsequent RAG retrievals SHALL NOT return chunks for the deleted document.

#### Scenario: Delete removes vectors from both collections

- **WHEN** a document indexed into both `ascendai-768` and `ascendai-1536` is deleted via `DELETE /api/v1/documents/{id}`
- **THEN** the response status is 204
- **AND** the count of Qdrant points with `metadata.source == <object key>` is zero in both collections
- **AND** the MinIO object no longer exists in the `knowledge-base` bucket
- **AND** `GET /api/v1/documents/{id}` returns 404

#### Scenario: Delete rejected while indexing

- **WHEN** `DELETE /api/v1/documents/{id}` is invoked while the document's status is `INDEXING`
- **THEN** the response status is 409
- **AND** no chunks, object, or registry row are removed

### Requirement: Deletion is retryable and safe mid-chat

Deletion SHALL set the document's status to `DELETING` before executing removal steps, each of which is idempotent. A failure part-way SHALL leave the row in `DELETING`, and repeating the DELETE SHALL re-execute the remaining steps to completion. The agent SHALL NOT track or revoke presigned source URLs already handed out in chat responses: they stop resolving once the MinIO object is removed and expire within the configured presign TTL regardless. In-flight chat turns that already retrieved the document's chunks SHALL complete normally.

#### Scenario: Retry after partial failure completes the delete

- **WHEN** a delete removes the Qdrant chunks but fails before removing the MinIO object
- **THEN** `GET /api/v1/documents/{id}` shows status `DELETING`
- **AND** repeating `DELETE /api/v1/documents/{id}` removes the MinIO object and the registry row and returns 204

#### Scenario: Previously issued presigned link after delete

- **WHEN** a chat response included a presigned source URL for a document that is subsequently deleted
- **THEN** the delete succeeds without waiting for or revoking the URL
- **AND** the URL stops returning the object content (MinIO reports the object missing or the link expires at its TTL)

### Requirement: Single-document re-index through the DocumentRouter path

The agent SHALL expose `POST /api/v1/documents/{id}/reindex` which re-processes exactly one document: fetch the object bytes from MinIO, process via `DocumentRouter.routeAndProcess` (extension-based routing to Markdown, Docling, PaddleOCR, Unstructured, or per-page PDF dispatch), split, remove the document's prior chunks for the target collection, and add the new chunks. Reindex SHALL bypass ETag deduplication, SHALL execute asynchronously returning HTTP 202 with a run id, SHALL set the document's status to `INDEXING` while running, and SHALL return 404 for unknown ids and 409 when the document's status is `DELETING`.

#### Scenario: Reindex replaces chunks

- **WHEN** `POST /api/v1/documents/{id}/reindex` is invoked for an already-indexed document and the run completes
- **THEN** the initial response status is 202 with a run id in the body
- **AND** the count of Qdrant points with `metadata.source == <object key>` in the target collection equals the chunk count of the new run (not the sum of old and new)
- **AND** the document's status returns to `INDEXED` with an updated `last_indexed_at`

#### Scenario: Reindex ignores unchanged ETag

- **WHEN** a document is reindexed without its MinIO object having changed
- **THEN** the run processes the document anyway (it is not skipped as a duplicate)

#### Scenario: Reindex rejected during deletion

- **WHEN** `POST /api/v1/documents/{id}/reindex` is invoked while the document's status is `DELETING`
- **THEN** the response status is 409
- **AND** no ingestion run is created

### Requirement: Authenticated document content download

The agent SHALL expose `GET /api/v1/documents/{id}/content` which streams the bytes of the document's MinIO object back through the agent with the object's `Content-Type` and a `Content-Disposition` naming the display name. The endpoint SHALL resolve the object key from the registry, fetch it from MinIO server-side, and stream it without redirecting the caller to MinIO. It SHALL return 404 for an unknown id and 404 once the document has been deleted. This endpoint is the client-facing download path for RAG source attachments; presigned MinIO URLs are retained only for in-network use and are not required to be reachable from public clients. Authorization (authenticated caller) and per-tenant ownership enforcement are layered by the sibling changes (`add-auth-and-identity`, `add-tenant-isolation`).

#### Scenario: Content download streams the object through the agent

- **WHEN** `GET /api/v1/documents/{id}/content` is invoked for an indexed document
- **THEN** the response status is 200 with the object's `Content-Type`
- **AND** the body is the file's bytes
- **AND** the response is served by the agent (no HTTP redirect to a MinIO host)

#### Scenario: Content download after deletion

- **WHEN** `GET /api/v1/documents/{id}/content` is invoked for a document that has been deleted
- **THEN** the response status is 404
