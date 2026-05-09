## ADDED Requirements

### Requirement: Opt-in `attachSources` parameter on prompt endpoint

`POST /api/v1/ai/prompt` SHALL accept an optional multipart form field named `attachSources` of type boolean. When omitted or set to `false`, the response shape SHALL be byte-for-byte identical to the response shape that exists today (no `sources` key in the JSON). When set to `true`, the response SHALL include a `sources` array describing the original source documents that grounded the RAG answer. The parameter SHALL be documented in the OpenAPI specification via `@Parameter` annotation on the controller method.

#### Scenario: Caller does not send the parameter

- **WHEN** a caller sends `POST /api/v1/ai/prompt` with `userId=frosty` and `prompt=…` and NO `attachSources` part
- **THEN** the response JSON does NOT contain a `sources` key at all
- **AND** the response is structurally identical to a request issued before this change shipped

#### Scenario: Caller sets `attachSources=false`

- **WHEN** a caller sends `attachSources=false` as a multipart form field
- **THEN** the response JSON does NOT contain a `sources` key
- **AND** no presigned URLs are generated server-side

#### Scenario: Caller sets `attachSources=true`

- **WHEN** a caller sends `attachSources=true` and RAG retrieval returns at least one chunk above the configured similarity threshold
- **THEN** the response JSON contains a `sources` array with one or more `SourceFile` objects
- **AND** each `SourceFile` contains non-blank `name`, `mimeType`, `downloadUrl`, and `expiresAt` fields

### Requirement: `SourceFile` DTO shape

The `SourceFile` DTO SHALL be a JSON object with these fields: `name` (string, the human-readable filename), `mimeType` (string, e.g. `application/pdf`), `downloadUrl` (string, a presigned MinIO/S3 GET URL), `expiresAt` (ISO-8601 instant), and optional `sizeBytes` (integer; omitted when unknown). The DTO SHALL use `@JsonInclude(NON_NULL)` so unknown size is omitted rather than serialized as `null`.

#### Scenario: SourceFile JSON shape

- **WHEN** a `SourceFile` for a 1.4 MB PDF is serialized
- **THEN** the JSON object has exactly the keys `name`, `mimeType`, `downloadUrl`, `expiresAt`, `sizeBytes` (in any order)
- **AND** `expiresAt` is a valid ISO-8601 instant
- **AND** `sizeBytes` is the integer byte count

#### Scenario: SourceFile with unknown size

- **WHEN** the size cannot be determined (HEAD failed, but presign succeeded against a known-good object)
- **THEN** `sizeBytes` is omitted from the JSON, not serialized as `null`

### Requirement: Empty source array when RAG returns nothing

When `attachSources=true` is set but `RagRetrievalService` returns zero chunks above the configured similarity threshold, the response SHALL contain `"sources": []` (an empty JSON array). The endpoint SHALL NOT return a 4xx or 5xx status for this case, and SHALL NOT omit the `sources` key.

#### Scenario: Soft-RAG threshold rejected all candidates

- **WHEN** `attachSources=true` is sent and Qdrant returns no chunks scoring above `app.rag.similarity-threshold`
- **THEN** the HTTP status is 200
- **AND** the response JSON contains `"sources": []`
- **AND** no presigned URLs are generated

#### Scenario: User collection is empty

- **WHEN** `attachSources=true` is sent and the user has never ingested any documents
- **THEN** the HTTP status is 200
- **AND** the response JSON contains `"sources": []`

### Requirement: De-duplication by source object identity

When multiple retrieved chunks point to the same underlying source document (same MinIO bucket and key), the response `sources` array SHALL contain that document exactly once. The first occurrence (in similarity-rank order) SHALL determine the position in the result list.

#### Scenario: Five chunks across two unique source documents

- **WHEN** RAG retrieval returns 5 chunks: 3 from `s3://docs/manual.pdf`, 2 from `s3://docs/spec.md`
- **THEN** `response.sources` has exactly 2 entries
- **AND** the first entry corresponds to whichever document contributed the highest-scoring chunk

#### Scenario: One chunk per source

- **WHEN** RAG retrieval returns 4 chunks each from a different source document
- **THEN** `response.sources` has exactly 4 entries

### Requirement: Presigned URLs for source documents

`AiResponse.sources[*].downloadUrl` SHALL be a presigned `GET` URL signed using the agent's MinIO credentials and scoped to a single object. The URL SHALL be reachable from the caller's network (signed against `app.minio.public-endpoint`, which defaults to `app.minio.endpoint` but may be overridden so containerised callers and host callers both succeed). The TTL SHALL default to 15 minutes and be configurable via `app.rag.source-attachments.presign-ttl` within the bounds `[1 minute, 1 hour]`. Values outside the bounds SHALL be clamped at startup with a WARN log.

#### Scenario: Default TTL

- **WHEN** the application boots with no override of `app.rag.source-attachments.presign-ttl`
- **THEN** `expiresAt` on every `SourceFile` is approximately `now + 15 minutes` (within ±1 second of the response time)

#### Scenario: Configured TTL

- **WHEN** `app.rag.source-attachments.presign-ttl: PT5M` is set and a request returns sources
- **THEN** `expiresAt` is approximately `now + 5 minutes`

#### Scenario: TTL clamped above bound

- **WHEN** `app.rag.source-attachments.presign-ttl: PT2H` is configured (above the 1-hour bound)
- **THEN** the application logs a single WARN line indicating the value was clamped
- **AND** the effective TTL used at runtime is 1 hour

#### Scenario: URL fetchable from caller's network

- **GIVEN** the agent runs in docker-compose with `app.minio.endpoint=http://minio:9000` and `app.minio.public-endpoint=http://localhost:9070`
- **WHEN** a caller on the host receives a `downloadUrl` and issues a GET against it
- **THEN** the GET returns 200 with the file bytes
- **AND** the URL's host portion is `localhost:9070`, NOT `minio:9000`

### Requirement: Size cap for attached sources

Source documents larger than `app.rag.source-attachments.max-file-size` (default 25 MB) SHALL be excluded from the response array. The exclusion SHALL log a single WARN line per skipped source containing the bucket, key, actual size, and configured cap. The exclusion SHALL NOT cause the request to fail; remaining sources SHALL still be returned.

#### Scenario: One oversize source among many

- **GIVEN** `app.rag.source-attachments.max-file-size: 25MB` and three retrieved sources with sizes 1 MB, 30 MB, 4 MB
- **WHEN** `attachSources=true` is set
- **THEN** `response.sources` contains exactly 2 entries (the 1 MB and 4 MB documents)
- **AND** logs contain a WARN line referencing the 30 MB source's `s3://{bucket}/{key}`

#### Scenario: All sources oversize

- **WHEN** every retrieved source exceeds the cap
- **THEN** `response.sources` is `[]`
- **AND** the request returns HTTP 200

### Requirement: Best-effort presigning never fails the request

If presigning a single source document fails (HEAD error, SDK exception, MinIO unreachable for that key), the affected source SHALL be omitted from the response array, a single WARN line SHALL be logged, and the request SHALL still return HTTP 200 with the textual answer and any successfully presigned siblings.

#### Scenario: HEAD fails for one source

- **WHEN** the `HEAD` call against `s3://docs/manual.pdf` returns 503
- **THEN** `manual.pdf` is omitted from `response.sources`
- **AND** the response status is 200
- **AND** a WARN log line references `s3://docs/manual.pdf` and the HEAD failure

#### Scenario: Presigner throws

- **WHEN** the AWS SDK presigner throws `SdkException` for one source while succeeding for two others
- **THEN** `response.sources` contains the two successfully presigned entries
- **AND** the request status is 200

### Requirement: No leakage of presigned URLs through logs or chat history

The agent SHALL NOT log the body of any presigned URL (the `?X-Amz-Signature=…` portion). Logs SHALL reference sources by `s3://{bucket}/{key}` only. The agent SHALL NOT persist presigned URLs to chat history (Redis or PostgreSQL). The textual answer that goes into chat history SHALL be unchanged from today's behavior.

#### Scenario: Logs contain no signed URL

- **WHEN** a request returns three presigned sources
- **THEN** application logs at INFO/DEBUG/WARN levels contain zero substrings matching `X-Amz-Signature`
- **AND** logs reference each source as `s3://{bucket}/{key}` only

#### Scenario: Chat history is unaffected

- **WHEN** a prompt is answered with `attachSources=true` and presigned URLs returned
- **THEN** the entry written to Redis chat history contains the textual answer only
- **AND** the entry does NOT contain `downloadUrl`, `expiresAt`, or any presigned URL string

### Requirement: Backward compatibility

Callers that do NOT send the `attachSources` field SHALL receive responses that are structurally identical to responses produced by the previous version of the agent. No existing field SHALL be renamed, removed, retyped, or moved to a different JSON path. The new `sources` field SHALL be omitted from JSON (not serialized as `null`) when not requested.

#### Scenario: Pre-change client behavior

- **WHEN** a client written before this change ships sends a normal prompt request
- **THEN** the response JSON has the same keys, ordering, and types as before this change
- **AND** the response JSON does NOT contain a `sources` key

#### Scenario: JSON schema additivity

- **WHEN** the OpenAPI specification is generated
- **THEN** all previously declared `AiResponse` fields are still present with their original names and types
- **AND** the new `sources` field is declared as optional (not required)
