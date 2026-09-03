## Context

AscendAgent today is effectively a single-tenant application that happens to accept a `userId` form field. All four data planes are shared pools:

- Qdrant: two collections (`ascendai-768`, `ascendai-1536`) with no owner metadata beyond `source`/`type`/`title` (`IngestionMetadataKeys`), searched with no filter (`RagRetrievalService`).
- MinIO: one `knowledge-base` bucket, keys are `markdown/<file>` or `documents/<file>` (`IngestionController.determineFolder`).
- Redis: `chat:{userId}` lists (`PersistentChatMemory`) and `user:{userId}:instructions` values (`UserInstructionService`).
- Postgres: `chat_history` and `user_instructions` keyed by `user_id` only (`01-initial-schema.xml`).
- AscendMemory: partitions by caller-supplied `user_id` inside shared Qdrant collections and trusts it blindly.

**Dependency**: this change DEPENDS on the sibling `add-auth-and-identity` change, which delivers authenticated requests carrying a JWT with a `tenant` claim. This design consumes a resolved tenant id per request and does not re-specify token validation, claim extraction, or identity storage. The integration contract is a single request-scoped accessor (referred to below as `TenantContext.currentTenantId()`) that either returns the authenticated tenant id or signals its absence.

**Sibling coordination**: `add-chat-streaming-and-conversations` will introduce a `conversationId` distinct from `userId`. The Redis key scheme chosen here (`chat:{tenantId}:{userId}`) keeps the tenant segment first and the conversation-identifying segment last, so that change only swaps the last segment (`chat:{tenantId}:{conversationId}`) without touching tenant scoping. The Postgres composite index `(tenant_id, user_id)` likewise extends naturally to `(tenant_id, user_id, conversation_id)`.

## Goals / Non-Goals

**Goals:**

- Hard, fail-closed data isolation between tenants across Qdrant, MinIO, Redis, Postgres, and AscendMemory.
- Zero cross-tenant reads: a similarity search, presign, history load, instruction load, or memory search can never return another tenant's data — even under bugs like userId collision or forged form fields.
- In-place upgrade for existing deployments via a `default` tenant backfill; no data loss, no manual data surgery.
- Compatibility with the sibling conversation-model and document-management changes.

**Non-Goals:**

- Authentication, JWT validation, tenant onboarding/admin APIs (owned by `add-auth-and-identity`).
- Per-tenant quotas or usage metering (owned by `add-usage-metering-and-quotas`).
- Tenant-aware audit logging or GDPR export/erasure (owned by `add-audit-and-gdpr-compliance`).
- Physical isolation (separate databases/collections/buckets per tenant) — this change delivers logical isolation within shared infrastructure.
- Changes to AscendMemory, AudioScribe, AscendWebSearch, WeatherMCP, or PaddleOCR service code.

## Decisions

### 1. Logical isolation via mandatory filters, not physical isolation

Shared collections/bucket/tables with a mandatory `tenant_id` discriminator, enforced at every read and write path.

- **Alternative — collection/bucket/schema per tenant**: stronger blast-radius isolation, but Qdrant collection count grows with tenants × embedding dims, MinIO bucket limits bite, Liquibase per-schema migration multiplies, and per-request provider routing (`VectorStoreResolver`) would need a second dimension. Rejected as disproportionate for the current scale; the fail-closed filter gives the same observable guarantee.
- The discriminator approach also matches what AscendMemory/mem0 already does with `user_id`, so one mechanism covers all stores.

### 2. Fail-closed tenant context

Every tenant-scoped operation requires a resolved tenant id. When `TenantContext` is empty (unauthenticated path, misconfiguration, internal caller that forgot to propagate), the operation throws — it never degrades to an unfiltered query or a shared key. HTTP surfaces this as 401/403 (per the auth change's error contract); service-layer callers get an exception.

- **Alternative — fall back to `default` tenant when context is missing**: rejected. A silent fallback turns a propagation bug into a cross-tenant leak into the default tenant's pool. The `default` tenant is a migration target only, reached through normal authenticated context like any other tenant.

### 3. Tenant id format: constrained slug

`tenant_id` is `[a-z0-9-]{1,64}`, validated at the trust boundary. This makes it safe to embed in Redis keys (`:`-delimited), S3 key prefixes (`/`-delimited), Qdrant payload values, and the `{tenantId}:{userId}` composite sent to AscendMemory — no escaping layer anywhere. The reserved id `default` is created by migration.

### 4. Qdrant: metadata stamp + Spring AI FilterExpression

Ingestion adds `tenant_id` to every chunk's metadata (new key in `IngestionMetadataKeys`). Retrieval builds the `SearchRequest` with `.filterExpression("tenant_id == '<current>'")` (via the `FilterExpressionBuilder` API, not string concatenation). The existing Java-side threshold filtering and score logging are unchanged; the tenant filter applies server-side in Qdrant so cross-tenant chunks never even reach the candidate list or the score logs.

### 5. MinIO: tenant prefix + presign guard

Object keys become `tenant/{tenantId}/markdown/...` and `tenant/{tenantId}/documents/...`. Three enforcement points:

- **Upload** (`IngestionController`): key is built from the resolved tenant context, never from user input.
- **Manual scan** (`ManualIngestionService` via `POST /api/v1/ingestion/run`): the caller-supplied `prefix` parameter is interpreted relative to the tenant prefix; the effective scan prefix is always `tenant/{tenantId}/...`.
- **Presign** (`S3PresignedUrlService`): before signing, the requested key must start with `tenant/{tenantId}/` for the caller's tenant; anything else is refused and logged. This is defense in depth — the Qdrant filter should already prevent foreign `SourceRef`s from reaching the presigner, but the presigner must not rely on that.

### 6. Redis and Postgres key/row scoping

- Redis: `chat:{tenantId}:{userId}` and `user:{tenantId}:{userId}:instructions`. TTL semantics unchanged.
- Postgres: `tenant_id VARCHAR(64) NOT NULL` on `chat_history` and `user_instructions`; `user_instructions` primary key becomes composite `(tenant_id, user_id)`; `chat_history` gets index `(tenant_id, user_id)` replacing the single-column index. All repository queries add the tenant predicate.

### 7. AscendMemory: tenant-qualified user id, qualified inside `SemanticMemoryClient`

The agent sends `{tenantId}:{userId}` as `user_id` on every insert/search/wipe/delete. Qualification happens in one place — `SemanticMemoryClient` composes the id from `TenantContext` — so no call site can forget it (single choke point, mirrors how the client already owns snake_case naming).

- **Alternative — add a `tenant_id` parameter to the AscendMemory API**: rejected. It widens the API surface of a service that would still have to trust the caller (AscendAgent is the only client inside the trust boundary), and namespacing the existing partition key achieves identical isolation with zero Python changes.

### 8. Migration: single Liquibase changelog, backfill to `default`

One new changelog file: create `tenants`, insert the `default` row, add `tenant_id` columns with `defaultValue='default'` (backfilling existing rows in the same statement), then tighten to `NOT NULL` and swap indexes. Qdrant and MinIO backfills are not Liquibase's job — a one-shot migration task (admin-triggered) sets `tenant_id='default'` on existing Qdrant points and moves existing `markdown/`/`documents/` objects under `tenant/default/`. Until it runs, pre-existing vectors are invisible to search (fail-closed, decision 2) — visible degradation, not silent leakage.

### 9. The presigned link stays mandatory under the tenant prefix check (owner decision, 2026-09-03)

An earlier draft of this change framed the presigned link as conditional. Its `rag-source-attachments` delta spoke of "any in-network presigned URL (`AiResponse.sources[*].downloadUrl`, when populated)" and called `GET /api/v1/documents/{id}/content` from `add-document-management-api` the primary client-facing download path, and the proposal repeated that framing by saying the client-facing download path moves to the agent endpoint. Both readings contradict the `rag-source-attachments` baseline, which guarantees a non-blank `downloadUrl` and `expiresAt` on every source entry.

The owner decided on 2026-09-03 that the link stays mandatory. Every source entry that is returned always carries a non-blank `downloadUrl` and `expiresAt`, `add-document-management-api` adds `documentId` and `contentPath` beside the link as further mandatory fields rather than instead of it, and neither download path is the primary one. The reason is that a caller must never have to implement two different ways of fetching the same source: a sometimes-absent link forces every client to carry both code paths plus the logic to choose between them. The same decision is recorded as D8 in `add-document-management-api/design.md`.

Nothing this change actually enforces is weakened by that. The tenant prefix check still refuses to presign any key outside `tenant/{tenantId}/`, and a refused `SourceRef` is dropped from the response entirely rather than returned as an entry with a missing link, so the guarantee that every returned entry carries a working link holds alongside the guarantee that no entry ever points outside the caller's tenant. The agent endpoint enforces the identical per-tenant ownership on the resolved document id, so both paths carry the same check and neither is a fallback for the other.

What that costs is the deployment posture: the object store has to stay reachable by clients wherever presigned links are handed out, so `harden-cloud-deployment` cannot treat the agent as the only public surface for source downloads. That cost is accepted deliberately and is not to be reopened here.

## Risks / Trade-offs

- [Missed enforcement point — some future code path queries Qdrant/MinIO/Redis without the tenant discriminator] → centralize: one `TenantContext`, one metadata key constant, one key-builder per store; integration tests assert cross-tenant reads return zero results; `add-audit-and-gdpr-compliance` adds the second net later.
- [Qdrant filter cost on large collections] → Qdrant supports payload indexes; create a keyword payload index on `tenant_id` per collection during migration so the filter is an index lookup, not a scan.
- [MinIO object move during migration is copy+delete, not atomic] → run the migration task with ingestion paused; the task is idempotent (skips already-moved keys) so it can resume after interruption.
- [`{tenantId}:{userId}` composite could collide with a raw userId containing `:` from the pre-tenant era] → memory written before this change stays under the unqualified id and is simply no longer retrieved; the migration task offers an optional re-key of existing AscendMemory entries to `default:{userId}`.
- [Sibling `add-chat-streaming-and-conversations` lands concurrently and both touch `PersistentChatMemory` key construction] → coordinate ordering at merge time; the key scheme here was chosen so the later change only replaces the final segment.
- [Fail-closed breaks existing unauthenticated local workflows the day this merges] → the dependency on `add-auth-and-identity` is explicit; local/dev profile behavior (e.g., a dev-issued token with `tenant=default`) is owned by that change.

## Migration Plan

1. Deploy with the new Liquibase changelog — Postgres tables/columns/indexes backfilled to `default` automatically at boot.
2. Run the one-shot data migration task: stamp `tenant_id='default'` on all existing Qdrant points (both collections), create the `tenant_id` payload indexes, move MinIO objects under `tenant/default/`, optionally re-key AscendMemory entries.
3. Verify: RAG retrieval for a `default`-tenant user returns pre-existing documents; a second tenant's user gets zero hits.
4. Rollback: the Liquibase columns are additive (old code ignores them); reverting the agent image restores pre-tenant behavior against Postgres/Redis. Reverting after the MinIO move requires re-running the move task in reverse (task supports `--direction=down`).

## Open Questions

- Exact name and package of the tenant context accessor delivered by `add-auth-and-identity` — this design assumes `TenantContext.currentTenantId()`; align once that change's design is finalized.
- Whether the one-shot Qdrant/MinIO migration task ships as a Spring Boot CLI runner (`--spring.main.web-application-type=none`) or an admin-only HTTP endpoint; leaning CLI runner to keep it off the API surface. Decide at implementation.
