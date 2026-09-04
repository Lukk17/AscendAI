# rag-source-attachments Delta Specification

## MODIFIED Requirements

### Requirement: `SourceFile` DTO shape

The `SourceFile` DTO SHALL be a JSON object with these fields: `documentId` (string, the registry id of the source document), `name` (string, the human-readable filename), `mimeType` (string, e.g. `application/pdf`), `contentPath` (string, the relative agent path `/api/v1/documents/{documentId}/content` that streams the document through the authenticated agent endpoint), `downloadUrl` (string, a presigned S3 GET URL), `expiresAt` (ISO-8601 instant), `ingestedAt` (ISO-8601 instant, the moment this document's chunks were last written to the vector store), and optional `sizeBytes` (integer, omitted when unknown). `documentId`, `name`, `mimeType`, `contentPath`, `downloadUrl`, `expiresAt`, and `ingestedAt` SHALL be present and non-blank on every serialized `SourceFile`. The DTO SHALL use `@JsonInclude(NON_NULL)` so unknown size is omitted rather than serialized as `null`.

`ingestedAt` SHALL be the document registry's last-indexed instant for that document, not a per-chunk value. Ingestion time is a property of the document, identical for every passage inside it, so it is carried once on the source entry rather than repeated on every citation. It lets a reader judge whether an answer is stale: an answer citing a document last indexed months ago may not reflect the file as it stands today.

Both download paths are always offered and both are expected to work: `contentPath` streams through the agent and is the path that stays valid for the life of the document, `downloadUrl` is the direct presigned object-store route bounded by its TTL. Neither is a fallback for the other, so a client picks one and never has to implement both.

#### Scenario: SourceFile JSON shape

- **WHEN** a `SourceFile` for a 1.4 MB PDF is serialized
- **THEN** the JSON object has exactly the keys `documentId`, `name`, `mimeType`, `contentPath`, `downloadUrl`, `expiresAt`, `ingestedAt`, `sizeBytes` (in any order)
- **AND** `contentPath` equals `/api/v1/documents/{documentId}/content` for that document's id
- **AND** `expiresAt` is a valid ISO-8601 instant
- **AND** `sizeBytes` is the integer byte count

#### Scenario: SourceFile with unknown size

- **WHEN** the size cannot be determined (HEAD failed, but presign succeeded against a known-good object)
- **THEN** `sizeBytes` is omitted from the JSON, not serialized as `null`

#### Scenario: Ingestion time reflects the last index of the document

- **WHEN** a document is reindexed and then cited in a later answer
- **THEN** `ingestedAt` on its source entry equals the registry's last-indexed instant from that reindex
- **AND** it is strictly later than the value returned before the reindex

#### Scenario: Ingestion time is identical across passages of one document

- **WHEN** three retrieved passages come from the same document
- **THEN** the single source entry for that document carries one `ingestedAt`
- **AND** no citation entry carries an ingestion time of its own

### Requirement: De-duplication by source object identity

When multiple retrieved chunks point to the same underlying source document (same S3 bucket and key), the response `sources` array SHALL contain that document exactly once. The first occurrence (in similarity-rank order) SHALL determine the position in the result list.

The array SHALL be derived from the passages actually injected into the prompt, not from every chunk that scored above the similarity threshold. A document whose every chunk was dropped by the context-size budget contributed nothing to the answer and SHALL NOT appear in `sources`, so the array and the response's `citations` array always describe the same evidence.

#### Scenario: Five chunks across two unique source documents

- **WHEN** RAG retrieval returns 5 chunks: 3 from `s3://docs/manual.pdf`, 2 from `s3://docs/spec.md`, and all 5 are injected
- **THEN** `response.sources` has exactly 2 entries
- **AND** the first entry corresponds to whichever document contributed the highest-scoring chunk

#### Scenario: One chunk per source

- **WHEN** RAG retrieval returns 4 chunks each from a different source document and all 4 are injected
- **THEN** `response.sources` has exactly 4 entries

#### Scenario: Document dropped by the context budget is not listed as a source

- **WHEN** a chunk from `s3://docs/appendix.pdf` scores above the threshold but the context-size budget is exhausted before it, so none of its text is injected, and no other chunk from that document is injected
- **THEN** `appendix.pdf` does not appear in `response.sources`
- **AND** no citation refers to it

#### Scenario: Sources and citations describe the same documents

- **WHEN** a prompt is answered with `attachSources=true` and citations enabled
- **THEN** the set of `documentId` values in `response.citations` that are present equals the set of `documentId` values in `response.sources`, except for citations whose source has no registry row
