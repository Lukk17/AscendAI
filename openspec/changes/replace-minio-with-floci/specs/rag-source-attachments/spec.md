# rag-source-attachments Delta Specification

## MODIFIED Requirements

### Requirement: `SourceFile` DTO shape

The `SourceFile` DTO SHALL be a JSON object with these fields: `name` (string, the human-readable filename), `mimeType` (string, e.g. `application/pdf`), `downloadUrl` (string, a presigned S3 GET URL), `expiresAt` (ISO-8601 instant), and optional `sizeBytes` (integer, omitted when unknown). The DTO SHALL use `@JsonInclude(NON_NULL)` so unknown size is omitted rather than serialized as `null`.

#### Scenario: SourceFile JSON shape

- **WHEN** a `SourceFile` for a 1.4 MB PDF is serialized
- **THEN** the JSON object has exactly the keys `name`, `mimeType`, `downloadUrl`, `expiresAt`, `sizeBytes` (in any order)
- **AND** `expiresAt` is a valid ISO-8601 instant
- **AND** `sizeBytes` is the integer byte count

#### Scenario: SourceFile with unknown size

- **WHEN** the size cannot be determined (HEAD failed, but presign succeeded against a known-good object)
- **THEN** `sizeBytes` is omitted from the JSON, not serialized as `null`

### Requirement: De-duplication by source object identity

When multiple retrieved chunks point to the same underlying source document (same S3 bucket and key), the response `sources` array SHALL contain that document exactly once. The first occurrence (in similarity-rank order) SHALL determine the position in the result list.

#### Scenario: Five chunks across two unique source documents

- **WHEN** RAG retrieval returns 5 chunks: 3 from `s3://docs/manual.pdf`, 2 from `s3://docs/spec.md`
- **THEN** `response.sources` has exactly 2 entries
- **AND** the first entry corresponds to whichever document contributed the highest-scoring chunk

#### Scenario: One chunk per source

- **WHEN** RAG retrieval returns 4 chunks each from a different source document
- **THEN** `response.sources` has exactly 4 entries

### Requirement: Presigned URLs for source documents

`AiResponse.sources[*].downloadUrl` SHALL be a presigned `GET` URL signed using the agent's configured S3 credentials (`app.s3.access-key` and `app.s3.secret-key`) and scoped to a single object. The URL SHALL be reachable from the caller's network (signed against `app.s3.public-endpoint`, which defaults to `app.s3.endpoint` but may be overridden so containerised callers and host callers both succeed). The TTL SHALL default to 15 minutes and be configurable via `app.rag.source-attachments.presign-ttl` within the bounds `[1 minute, 1 hour]`. Values outside the bounds SHALL be clamped at startup with a WARN log.

The requirement is object-store-neutral. It SHALL hold against any S3-compatible endpoint the agent is pointed at, including one that does not validate the signature it receives. Where the endpoint ignores credentials, the URL SHALL still carry a well-formed `X-Amz-Signature` query parameter, because presence of that parameter is what the no-leakage requirement below is asserted against.

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

- **GIVEN** the agent runs in docker-compose with `app.s3.endpoint=http://host.docker.internal:9070` and `app.s3.public-endpoint=http://localhost:9070`, both reaching the same external Floci instance
- **WHEN** a caller on the host receives a `downloadUrl` and issues a GET against it
- **THEN** the GET returns 200 with the file bytes
- **AND** the URL's host portion is `localhost:9070`, NOT `host.docker.internal:9070`

#### Scenario: URL resolves against an endpoint that does not validate credentials

- **GIVEN** the object store is Floci, which accepts any credential value
- **WHEN** a caller issues a GET against a `downloadUrl` returned by the agent
- **THEN** the GET returns 200 with the file bytes
- **AND** the response is byte-identical to a direct unauthenticated `GET http://localhost:9070/{bucket}/{key}`

### Requirement: Best-effort presigning never fails the request

If presigning a single source document fails (HEAD error, SDK exception, the object store unreachable for that key), the affected source SHALL be omitted from the response array, a single WARN line SHALL be logged, and the request SHALL still return HTTP 200 with the textual answer and any successfully presigned siblings.

#### Scenario: HEAD fails for one source

- **WHEN** the `HEAD` call against `s3://docs/manual.pdf` returns 503
- **THEN** `manual.pdf` is omitted from `response.sources`
- **AND** the response status is 200
- **AND** a WARN log line references `s3://docs/manual.pdf` and the HEAD failure

#### Scenario: Presigner throws

- **WHEN** the AWS SDK presigner throws `SdkException` for one source while succeeding for two others
- **THEN** `response.sources` contains the two successfully presigned entries
- **AND** the request status is 200

#### Scenario: Object store is entirely unreachable

- **WHEN** the endpoint at `app.s3.endpoint` refuses every connection while a prompt with `attachSources=true` is answered
- **THEN** the response status is 200 with the textual answer
- **AND** `response.sources` is `[]`
