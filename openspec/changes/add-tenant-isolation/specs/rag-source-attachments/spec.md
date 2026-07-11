## MODIFIED Requirements

### Requirement: Presigned URLs for source documents

The agent SHALL only issue a source download for objects whose key starts with `tenant/{tenantId}/` for the caller's resolved tenant; a `SourceRef` whose key falls outside the caller's tenant prefix SHALL be refused (omitted from the response) and a single WARN line logged with the offending `s3://{bucket}/{key}`. When no tenant context is resolved, no source download SHALL be offered. This requirement governs any in-network presigned URL (`AiResponse.sources[*].downloadUrl`, when populated); after the presign-resolution amendment the primary client-facing download path is `GET /api/v1/documents/{id}/content` (`add-document-management-api`), which enforces the identical per-tenant ownership on the resolved document id. The URL SHALL be reachable from the caller's network (signed against `app.s3.public-endpoint`, which defaults to `app.s3.endpoint` but may be overridden so containerised callers and host callers both succeed). The TTL SHALL default to 15 minutes and be configurable via `app.rag.source-attachments.presign-ttl` within the bounds `[1 minute, 1 hour]`. Values outside the bounds SHALL be clamped at startup with a WARN log.

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

- **GIVEN** the agent runs in docker-compose with `app.s3.endpoint=http://minio:9000` and `app.s3.public-endpoint=http://localhost:9070`
- **WHEN** a caller on the host receives a `downloadUrl` and issues a GET against it
- **THEN** the GET returns 200 with the file bytes
- **AND** the URL's host portion is `localhost:9070`, NOT `minio:9000`
