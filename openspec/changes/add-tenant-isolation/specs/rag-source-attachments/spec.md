## MODIFIED Requirements

### Requirement: Presigned URLs for source documents

`AiResponse.sources[*].downloadUrl` SHALL be a presigned `GET` URL signed using the agent's configured S3 credentials (`app.s3.access-key` and `app.s3.secret-key`) and scoped to a single object. The agent SHALL only issue a source download for objects whose key starts with `tenant/{tenantId}/` for the caller's resolved tenant; a `SourceRef` whose key falls outside the caller's tenant prefix SHALL be refused (omitted from the response) and a single WARN line logged with the offending `s3://{bucket}/{key}`. When no tenant context is resolved, no source download SHALL be offered. Every source entry that is returned always carries a non-blank `downloadUrl` and `expiresAt`, exactly as the baseline guarantees, so this requirement governs a link that is always present rather than an optional one. `add-document-management-api` adds `documentId` and `contentPath` beside that link as further mandatory fields, and its `GET /api/v1/documents/{id}/content` endpoint enforces the identical per-tenant ownership on the resolved document id. Neither download path is the primary one and neither is a fallback for the other, so a caller picks one and never has to implement both. The URL SHALL be reachable from the caller's network (signed against `app.s3.public-endpoint`, which defaults to `app.s3.endpoint` but may be overridden so containerised callers and host callers both succeed). The TTL SHALL default to 15 minutes and be configurable via `app.rag.source-attachments.presign-ttl` within the bounds `[1 minute, 1 hour]`. Values outside the bounds SHALL be clamped at startup with a WARN log.

The requirement is object-store-neutral. It SHALL hold against any S3-compatible endpoint the agent is pointed at, including one that does not validate the signature it receives. Where the endpoint ignores credentials, the URL SHALL still carry a well-formed `X-Amz-Signature` query parameter, because presence of that parameter is what the no-leakage requirement below is asserted against.

#### Scenario: Presign refused outside the caller's tenant prefix

- **WHEN** a request from a user of tenant `globex` produces a `SourceRef` pointing at `tenant/acme/documents/handbook.pdf`
- **THEN** no presigned URL is generated for that key
- **AND** the source is omitted from `response.sources`
- **AND** a WARN log line references `s3://knowledge-base/tenant/acme/documents/handbook.pdf`

#### Scenario: Presign succeeds inside the caller's tenant prefix

- **WHEN** a user of tenant `acme` receives sources whose keys start with `tenant/acme/`
- **THEN** each such source is presigned and returned with non-blank `downloadUrl` and `expiresAt`

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
