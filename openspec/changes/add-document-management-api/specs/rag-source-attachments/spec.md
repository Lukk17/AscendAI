# rag-source-attachments Delta Specification

## MODIFIED Requirements

### Requirement: Opt-in `attachSources` parameter on prompt endpoint

`POST /api/v1/ai/prompt` SHALL accept an optional multipart form field named `attachSources` of type boolean. When omitted or set to `false`, the response shape SHALL be byte-for-byte identical to the response shape that exists today (no `sources` key in the JSON). When set to `true`, the response SHALL include a `sources` array describing the original source documents that grounded the RAG answer. The parameter SHALL be documented in the OpenAPI specification via `@Parameter` annotation on the controller method.

Every entry in that array SHALL carry both download paths at once: the presigned object-store URL (`downloadUrl` plus `expiresAt`) that this capability already guarantees, and the registry-backed agent path (`documentId` plus `contentPath`) that this change adds. A caller therefore never has to implement a second way of fetching the same source. The document id SHALL be resolved from the document registry by the source object's S3 key. A retrieved chunk whose source object has no registry row SHALL be omitted from `sources` with a single WARN line referencing `s3://{bucket}/{key}`, because such a source cannot be offered through both paths.

#### Scenario: Caller does not send the parameter

- **WHEN** a caller sends `POST /api/v1/ai/prompt` with `userId=frosty` and `prompt=…` and NO `attachSources` part
- **THEN** the response JSON does NOT contain a `sources` key at all
- **AND** the response is structurally identical to a request issued before this change shipped

#### Scenario: Caller sets `attachSources=false`

- **WHEN** a caller sends `attachSources=false` as a multipart form field
- **THEN** the response JSON does NOT contain a `sources` key
- **AND** no presigned URLs are generated server-side

#### Scenario: Caller sets `attachSources=true`

- **WHEN** a caller sends `attachSources=true` and RAG retrieval returns at least one chunk above the configured similarity threshold whose source object is registered
- **THEN** the response JSON contains a `sources` array with one or more `SourceFile` objects
- **AND** each `SourceFile` contains non-blank `documentId`, `name`, `mimeType`, `contentPath`, `downloadUrl`, and `expiresAt` fields

#### Scenario: Retrieved chunk without a registry row

- **WHEN** `attachSources=true` is set and a retrieved chunk's source object has no `documents` registry row
- **THEN** that source is omitted from `response.sources`
- **AND** a single WARN line references `s3://{bucket}/{key}`
- **AND** the request still returns HTTP 200 with any remaining sources

#### Scenario: Both download paths return the same bytes

- **WHEN** a caller fetches a source through `contentPath` with its credentials and separately fetches the same source through `downloadUrl`
- **THEN** both responses return 200
- **AND** the two bodies are byte-identical

### Requirement: `SourceFile` DTO shape

The `SourceFile` DTO SHALL be a JSON object with these fields: `documentId` (string, the registry id of the source document), `name` (string, the human-readable filename), `mimeType` (string, e.g. `application/pdf`), `contentPath` (string, the relative agent path `/api/v1/documents/{documentId}/content` that streams the document through the authenticated agent endpoint), `downloadUrl` (string, a presigned S3 GET URL), `expiresAt` (ISO-8601 instant), and optional `sizeBytes` (integer, omitted when unknown). `documentId`, `name`, `mimeType`, `contentPath`, `downloadUrl`, and `expiresAt` SHALL be present and non-blank on every serialized `SourceFile`. The DTO SHALL use `@JsonInclude(NON_NULL)` so unknown size is omitted rather than serialized as `null`.

Both download paths are always offered and both are expected to work: `contentPath` streams through the agent and is the path that stays valid for the life of the document, `downloadUrl` is the direct presigned object-store route bounded by its TTL. Neither is a fallback for the other, so a client picks one and never has to implement both.

#### Scenario: SourceFile JSON shape

- **WHEN** a `SourceFile` for a 1.4 MB PDF is serialized
- **THEN** the JSON object has exactly the keys `documentId`, `name`, `mimeType`, `contentPath`, `downloadUrl`, `expiresAt`, `sizeBytes` (in any order)
- **AND** `contentPath` equals `/api/v1/documents/{documentId}/content` for that document's id
- **AND** `expiresAt` is a valid ISO-8601 instant
- **AND** `sizeBytes` is the integer byte count

#### Scenario: SourceFile with unknown size

- **WHEN** the size cannot be determined (HEAD failed, but presign succeeded against a known-good object)
- **THEN** `sizeBytes` is omitted from the JSON, not serialized as `null`
