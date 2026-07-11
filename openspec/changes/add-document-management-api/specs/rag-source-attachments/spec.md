## MODIFIED Requirements

### Requirement: `SourceFile` DTO shape

The `SourceFile` DTO SHALL be a JSON object with these fields: `documentId` (string, the registry id of the source document), `name` (string, the human-readable filename), `mimeType` (string, e.g. `application/pdf`), `contentPath` (string, the relative agent path `/api/v1/documents/{documentId}/content` the client uses to download the document through the authenticated agent endpoint), optional `sizeBytes` (integer; omitted when unknown), and optional `downloadUrl` / `expiresAt` (a presigned MinIO/S3 GET URL and its expiry, populated only for in-network callers when direct presigning is enabled; omitted otherwise). The DTO SHALL use `@JsonInclude(NON_NULL)` so unknown or unused fields are omitted rather than serialized as `null`. Clients SHALL treat `contentPath` as the canonical download path; `downloadUrl` is a legacy/in-network convenience and is not guaranteed to be reachable from public clients.

#### Scenario: SourceFile JSON shape

- **WHEN** a `SourceFile` for a 1.4 MB PDF is serialized for a public client
- **THEN** the JSON object contains `documentId`, `name`, `mimeType`, `contentPath`, and `sizeBytes`
- **AND** `contentPath` equals `/api/v1/documents/{documentId}/content` for that document's id
- **AND** a `GET` against `contentPath` (with the caller's credentials) returns the document bytes through the agent

#### Scenario: SourceFile with unknown size

- **WHEN** the size cannot be determined
- **THEN** `sizeBytes` is omitted from the JSON, not serialized as `null`

#### Scenario: Presigned fields omitted for public clients

- **WHEN** direct in-network presigning is not enabled for the deployment
- **THEN** `downloadUrl` and `expiresAt` are omitted from the `SourceFile` JSON
- **AND** `contentPath` is present and is the only download path offered

### Requirement: Caller sets `attachSources=true`

When a caller sends `attachSources=true` and RAG retrieval returns at least one chunk above the configured similarity threshold, the response JSON SHALL contain a `sources` array with one or more `SourceFile` objects. Each `SourceFile` SHALL carry non-blank `documentId`, `name`, `mimeType`, and `contentPath` fields; `downloadUrl` / `expiresAt` MAY be present for in-network deployments. The document id SHALL be resolved from the document registry by the source object's MinIO key; a retrieved chunk whose source object has no registry row SHALL be omitted from `sources` with a single WARN line referencing `s3://{bucket}/{key}`.

#### Scenario: Caller sets `attachSources=true`

- **WHEN** a caller sends `attachSources=true` and RAG retrieval returns at least one chunk above the configured similarity threshold whose source object is registered
- **THEN** the response JSON contains a `sources` array with one or more `SourceFile` objects
- **AND** each `SourceFile` contains non-blank `documentId`, `name`, `mimeType`, and `contentPath` fields

#### Scenario: Retrieved chunk without a registry row

- **WHEN** `attachSources=true` is set and a retrieved chunk's source object has no `documents` registry row
- **THEN** that source is omitted from `response.sources`
- **AND** a single WARN line references `s3://{bucket}/{key}`
- **AND** the request still returns HTTP 200 with any remaining sources
