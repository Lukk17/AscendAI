## MODIFIED Requirements

### Requirement: Presigned URLs for source documents

`AiResponse.sources[*].downloadUrl` SHALL be a presigned `GET` URL signed using the agent's configured S3 credentials (`app.s3.access-key` and `app.s3.secret-key`) and scoped to a single object.

Before signing, the agent SHALL apply both isolation axes to every `SourceRef`, independently of retrieval rather than trusting that retrieval already filtered it:

1. Tenant axis: the object key SHALL start with `tenant/{tenantId}/` for the caller's resolved tenant.
2. Access axis: the access list carried on the reference SHALL intersect the caller's resolved principal set, using the same set-intersection test the search filter applies. A reference whose list is absent or empty intersects nothing and fails this check, so deny-by-default holds here for the same reason it holds in retrieval.

To make the second check possible without a second Qdrant round trip, `buildSourceRefs` SHALL carry the chunk's `acl` payload onto the `SourceRef` it constructs, and the presigner SHALL evaluate that list rather than re-reading the point. Because presigning runs on a task executor rather than the request thread, the tenant id and principal set SHALL be captured on the request thread and passed into the asynchronous work. An unresolved tenant or principal set at that point SHALL fail the request rather than sign anything.

A reference failing either check SHALL be refused: it is dropped from the response entirely, not returned as an entry with a missing or blank link, and a single WARN line is logged with the offending `s3://{bucket}/{key}`. Dropping is the presigner's existing shape rather than a new response shape, since `presign` already returns an `Optional<SourceFile>` and empties are already filtered out of the result list, and this change adds a second reason to return empty. When no tenant context or no principal set is resolved, no source download SHALL be offered at all.

Every source entry that is returned always carries a non-blank `downloadUrl` and `expiresAt`, exactly as the baseline guarantees, so this requirement governs a link that is always present rather than an optional one. `add-document-management-api` adds `documentId` and `contentPath` beside that link as further mandatory fields, and its `GET /api/v1/documents/{id}/content` endpoint enforces the identical tenant and access-list checks on the resolved document id. Neither download path is the primary one and neither is a fallback for the other, so a caller picks one and never has to implement both.

An already-issued presigned link SHALL remain valid for its remaining lifetime, because the signature is self-contained and nothing consults the application when the URL is fetched. That window is bounded by the presign TTL and is disclosed rather than closed. The URL SHALL be reachable from the caller's network (signed against `app.s3.public-endpoint`, which defaults to `app.s3.endpoint` but may be overridden so containerised callers and host callers both succeed). The TTL SHALL default to 15 minutes and be configurable via `app.rag.source-attachments.presign-ttl` within the bounds `[1 minute, 1 hour]`. Values outside the bounds SHALL be clamped at startup with a WARN log.

The requirement is object-store-neutral. It SHALL hold against any S3-compatible endpoint the agent is pointed at, including one that does not validate the signature it receives. Where the endpoint ignores credentials, the URL SHALL still carry a well-formed `X-Amz-Signature` query parameter, because presence of that parameter is what the no-leakage requirement below is asserted against.

#### Scenario: Presign refused outside the caller's tenant prefix

- **WHEN** a request from a user of tenant `globex` produces a `SourceRef` pointing at `tenant/acme/documents/handbook.pdf`
- **THEN** no presigned URL is generated for that key
- **AND** the source is omitted from `response.sources`
- **AND** a WARN log line references `s3://knowledge-base/tenant/acme/documents/handbook.pdf`

#### Scenario: Presign refused inside the caller's tenant but outside the access list

- **WHEN** a user of tenant `acme` whose principal set is `["tenant:everyone:acme"]` produces a `SourceRef` for `tenant/acme/documents/board-pack.pdf` whose access list is `["entra:group:finance"]`
- **THEN** no presigned URL is generated for that key
- **AND** the entry is absent from `response.sources` entirely, rather than present with a blank link
- **AND** the remaining sources for that request are still returned with working links

#### Scenario: Presign refused for a reference with no access list

- **WHEN** a `SourceRef` reaches the presigner carrying an absent or empty access list, for a key inside the caller's own tenant prefix
- **THEN** no presigned URL is generated for that key
- **AND** the entry is absent from `response.sources`

#### Scenario: Presign refused when retrieval did not filter

- **GIVEN** a caller path hands the presigner a `SourceRef` list that was not produced by the filtered retrieval path
- **WHEN** one of those references fails either the tenant check or the access-list check
- **THEN** it is refused on the presigner's own check
- **AND** the outcome is identical to the case where retrieval filtered it

#### Scenario: Presign succeeds inside the caller's tenant and access list

- **WHEN** a user of tenant `acme` receives sources whose keys start with `tenant/acme/` and whose access lists intersect that caller's principal set
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
