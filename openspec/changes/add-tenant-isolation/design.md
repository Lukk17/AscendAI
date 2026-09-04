## Context

AscendAgent today is effectively a single-tenant application that happens to accept a `userId` form field. All four data planes are shared pools:

- Qdrant: two collections (`ascendai-768`, `ascendai-1536`) with no owner metadata beyond `source`/`type`/`title` (`IngestionMetadataKeys`), searched with no filter (`RagRetrievalService`).
- MinIO: one `knowledge-base` bucket, keys are `markdown/<file>` or `documents/<file>` (`IngestionController.determineFolder`).
- Redis: `chat:{userId}` lists (`PersistentChatMemory`) and `user:{userId}:instructions` values (`UserInstructionService`).
- Postgres: `chat_history` and `user_instructions` keyed by `user_id` only (`01-initial-schema.xml`).
- AscendMemory: partitions by caller-supplied `user_id` inside shared Qdrant collections and trusts it blindly.

**Two axes, not one.** Isolation here has a tenant axis and an access axis, and the change is only complete when both are enforced at the same points. The tenant axis answers which company owns a chunk. The access axis answers which people inside that company may read it, because a company's documents are not uniformly readable by that company: the board pack, the salary bands, and the postmortem naming a customer are not for everyone. Wherever this document says isolation, it means both axes. A filter, a guard, or a migration step that handles only the tenant predicate is incomplete, not partially done, and the settled model behind the access axis is [permission-aware retrieval](../../../docs/architecture/permission-aware-retrieval.md) with its decision records ADR-M004 through ADR-M009.

**Dependency**: this change DEPENDS on the sibling `add-auth-and-identity` change, which delivers authenticated requests carrying a JWT with a `tenant` claim and resolves the caller's group principals from the token claim or the provider's transitive membership endpoint. This design consumes a resolved tenant id and a resolved principal set per request, and does not re-specify token validation, claim extraction, principal identifier format, membership resolution, or identity storage. The integration contract is two request-scoped accessors (referred to below as `TenantContext.currentTenantId()` and `PrincipalContext.currentPrincipals()`) that each either return the authenticated value or signal its absence.

**Sibling coordination**: `add-chat-streaming-and-conversations` will introduce a `conversationId` distinct from `userId`. The Redis key scheme chosen here (`chat:{tenantId}:{userId}`) keeps the tenant segment first and the conversation-identifying segment last, so that change only swaps the last segment (`chat:{tenantId}:{conversationId}`) without touching tenant scoping. The Postgres composite index `(tenant_id, user_id)` likewise extends naturally to `(tenant_id, user_id, conversation_id)`.

## Goals / Non-Goals

**Goals:**

- Hard, fail-closed data isolation between tenants across Qdrant, MinIO, Redis, Postgres, and AscendMemory.
- Zero cross-tenant reads: a similarity search, presign, history load, instruction load, or memory search can never return another tenant's data — even under bugs like userId collision or forged form fields.
- Zero unpermitted within-tenant reads: a similarity search or presign inside the caller's own tenant can only return chunks whose access list intersects the caller's resolved principal set, and a chunk with no list is returned to nobody.
- One filter composition point carrying both axes, so there is a single place a filter can be got wrong rather than two things that each believe they own filtering.
- In-place upgrade for existing deployments via a `default` tenant backfill; no data loss, no manual data surgery.
- Compatibility with the sibling conversation-model and document-management changes.

**Non-Goals:**

- Authentication, JWT validation, tenant onboarding/admin APIs (owned by `add-auth-and-identity`).
- Principal identifier format, the typed principal factory, group membership resolution, the Redis principal-set cache, and the cross-provider identity join (all owned by `add-auth-and-identity`). This change consumes the resolved set and defines only the `tenant:everyone:{tenantId}` pseudo-group.
- Capturing access lists from a source system, the deduplication key that pairs content version with access-list version, the payload-only update path, and the staleness sweep (owned by `add-document-connectors`). This change defines the payload fields those steps write.
- The administrator surface for assigning narrower lists to direct uploads. Direct uploads land on `tenant:everyone:{tenantId}` here, and who owns that surface is an open question in the permission-aware retrieval design.
- Per-tenant quotas or usage metering (owned by `add-usage-metering-and-quotas`).
- Tenant-aware audit logging or GDPR export/erasure (owned by `add-audit-and-gdpr-compliance`).
- Physical isolation (separate databases/collections/buckets per tenant) — this change delivers logical isolation within shared infrastructure.
- Changes to AscendMemory, AudioScribe, AscendWebSearch, WeatherMCP, or PaddleOCR service code.

## Decisions

### 1. Logical isolation via mandatory filters, not physical isolation

Shared collections/bucket/tables with a mandatory `tenant_id` discriminator, enforced at every read and write path.

- **Alternative — collection/bucket/schema per tenant**: stronger blast-radius isolation, but Qdrant collection count grows with tenants × embedding dims, MinIO bucket limits bite, Liquibase per-schema migration multiplies, and per-request provider routing (`VectorStoreResolver`) would need a second dimension. Rejected as disproportionate for the current scale; the fail-closed filter gives the same observable guarantee.
- The discriminator approach also matches what AscendMemory/mem0 already does with `user_id`, so one mechanism covers all stores.
- The same reasoning applies harder to the access axis, and is why it is a second payload field rather than a second partitioning: groups are far more numerous than tenants, so a collection per group would multiply collections by groups times embedding dimensions. Qdrant offers no per-principal authorization model to fall back on, which is recorded upstream as ADR-M009.

### 2. Fail-closed tenant context

Every tenant-scoped operation requires a resolved tenant id. When `TenantContext` is empty (unauthenticated path, misconfiguration, internal caller that forgot to propagate), the operation throws — it never degrades to an unfiltered query or a shared key. HTTP surfaces this as 401/403 (per the auth change's error contract); service-layer callers get an exception.

The principal set gets identical treatment. Similarity search and source presigning additionally require a resolved principal set, and when `PrincipalContext` is empty they throw for the same reason and in the same way. In particular they do not degrade to a search filtered by tenant alone, which would be the natural-looking shortcut and is exactly the leak this change exists to close: a tenant-only search hands the caller every document their company owns, including the ones the company deliberately restricted.

An empty resolved set and an unresolved set are different things and must not be conflated in code. An empty set is a successful answer that legitimately matches nothing, and it arises for real callers, for example one whose identity link is broken and who is left holding only `tenant:everyone`. An unresolved set is a failure. Representing the accessor's result as an `Optional<Set<Principal>>`, rather than as a possibly-empty set, keeps the two distinguishable at the type level.

- **Alternative — fall back to `default` tenant when context is missing**: rejected. A silent fallback turns a propagation bug into a cross-tenant leak into the default tenant's pool. The `default` tenant is a migration target only, reached through normal authenticated context like any other tenant.
- **Alternative, fall back to a tenant-only filter when the principal set is missing**: rejected for the same shape of reason. It degrades an authorization failure into a successful-looking response that over-shares inside the tenant, and it is invisible: the request returns 200, the answer is fluent, and nothing indicates that the access axis was skipped.

### 3. Tenant id format: constrained slug

`tenant_id` is `[a-z0-9-]{1,64}`, validated at the trust boundary. This makes it safe to embed in Redis keys (`:`-delimited), S3 key prefixes (`/`-delimited), Qdrant payload values, and the `{tenantId}:{userId}` composite sent to AscendMemory — no escaping layer anywhere. The reserved id `default` is created by migration.

### 4. Qdrant: metadata stamp + one composed Spring AI FilterExpression

Ingestion adds five metadata keys to every chunk: `tenant_id`, plus the access-list contract `acl`, `acl_source`, `acl_version`, and `acl_synced_at` (all new constants in `IngestionMetadataKeys`). Direct uploads stamp `acl` as `["tenant:everyone:{tenantId}"]` with `acl_source` of `tenant-default`; connector-captured lists come later from `add-document-connectors` and write the same fields.

Retrieval builds the `SearchRequest` with one filter expression carrying both axes:

```text
tenant_id == '<currentTenant>' AND acl IN <principalSet>
```

Both conjuncts are built through the `FilterExpressionBuilder` API, never by string concatenation, and they are composed into a single expression at a single place rather than added by two pieces of code that each think they own filtering. Spring AI's `IN` operator against a keyword-array payload field maps to Qdrant's match-any semantics, which is the set-intersection test this needs: the chunk is a candidate when its `acl` holds at least one principal the caller holds. That translation is the one part of the design that rests on library behaviour rather than our own code, so it is pinned by an integration test against a real Qdrant rather than a mocked `VectorStore`, which would confirm whatever we assumed.

The existing Java-side threshold filtering and score logging are unchanged. They operate on what Qdrant returned, and after this change what Qdrant returns is already permitted. Both filters apply server-side, so a chunk of another tenant, or of this tenant that the caller may not read, never reaches the candidate list, the score logs, the `topK` budget, or the model.

Deny-by-default falls out of this expression and is not written as code anywhere. A chunk whose `acl` is absent or empty intersects no principal set, so nothing retrieves it, including a caller holding every group in the tenant and including a caller holding role `ADMIN`, because a role is not a principal and does not widen the expression. There is deliberately no branch that inspects a missing list and decides what to do about it; the absence of such a branch is the property to preserve in review.

Both payload fields need a keyword payload index. Without an index on `acl` the access conjunct is evaluated by walking the collection, which turns the pre-filter that makes this design correct into the thing that makes it unusably slow. Both indexes are created in the same migration step (decision 8), so a deployment cannot end up with one axis indexed and the other scanned.

- **Alternative, filter the candidate list in Java after the search**: rejected, and this is the decision the whole design turns on. `topK` is spent before a post-filter runs, so a caller permitted only chunks ranked below the cut receives nothing while an unpermitted caller's query looks fine. It does not leak, it suppresses, so the obvious test passes and the design looks correct. With `topK` of 5 and a caller whose only permitted chunk ranks eighth, post-filtering returns an empty context and the model answers from its own weights. Pre-filtering returns that chunk. The symptom lands hardest on narrow-access callers, which is to say on the new joiner, the contractor, and the person the customer's security team sent to check whether permissions work. Recorded upstream as ADR-M005.
- **Alternative, over-fetch then filter in Java**: rejected. It makes the failure rarer rather than fixing it, and whether it works depends on what else is in the collection when the question is asked, so the same question can succeed today and fail after an unrelated ingest. A non-deterministic correctness property is worse than a deterministic failure, because it cannot be tested.

### 5. MinIO: tenant prefix + presign guard

Object keys become `tenant/{tenantId}/markdown/...` and `tenant/{tenantId}/documents/...`. Three enforcement points:

- **Upload** (`IngestionController`): key is built from the resolved tenant context, never from user input.
- **Manual scan** (`ManualIngestionService` via `POST /api/v1/ingestion/run`): the caller-supplied `prefix` parameter is interpreted relative to the tenant prefix; the effective scan prefix is always `tenant/{tenantId}/...`.
- **Presign** (`S3PresignedUrlService`): before signing, the reference must pass both axes. The key must start with `tenant/{tenantId}/` for the caller's tenant, and the chunk's access list must intersect the caller's principal set, evaluated with the same test the search filter uses. Anything else is refused and logged. This is defense in depth: the composed Qdrant filter should already prevent foreign or unpermitted `SourceRef`s from reaching the presigner, but the presigner must not rely on that. The reference list is assembled by `buildSourceRefs`, handed across a service boundary, and will one day be reachable from a path that did not filter, because that is what happens to every check that lives in only one place.

  A refused reference is dropped from the response entirely rather than returned as an entry with a missing link. That is not a new response shape: `presign` already returns an `Optional<SourceFile>` and `presignAll` already filters empties out of the result list, so this change adds a second reason to return empty and nothing else. It preserves the decision in section 9 that every returned entry always carries a working link.

  Two mechanics this needs. First, the access list has to reach the presigner: `buildSourceRefs` reads chunk metadata already, so it carries `acl` onto the `SourceRef` record, and the presigner evaluates that rather than making a second Qdrant round trip per source. Second, `presignAll` fans out onto `taskExecutor`, and request-scoped context does not propagate to those threads on its own, so the tenant id and principal set are captured on the request thread and passed into the asynchronous work. Reading the accessors inside the async lambda would throw on every request, which fails closed but is a fail-closed outage rather than a fail-closed control.

  What this check cannot do is reach a link that was already handed out. A presigned URL is self-contained, so a revocation does not invalidate one issued two minutes earlier. That window is bounded by the presign TTL, 15 minutes by default and one hour at most, and it is disclosed rather than closed, because closing it means proxying every download through the agent and that collides with the settled decision in section 9.

### 6. Redis and Postgres key/row scoping

- Redis: `chat:{tenantId}:{userId}` and `user:{tenantId}:{userId}:instructions`. TTL semantics unchanged.
- Postgres: `tenant_id VARCHAR(64) NOT NULL` on `chat_history` and `user_instructions`; `user_instructions` primary key becomes composite `(tenant_id, user_id)`; `chat_history` gets index `(tenant_id, user_id)` replacing the single-column index. All repository queries add the tenant predicate.

### 7. AscendMemory: tenant-qualified user id, qualified inside `SemanticMemoryClient`

The agent sends `{tenantId}:{userId}` as `user_id` on every insert/search/wipe/delete. Qualification happens in one place — `SemanticMemoryClient` composes the id from `TenantContext` — so no call site can forget it (single choke point, mirrors how the client already owns snake_case naming).

- **Alternative — add a `tenant_id` parameter to the AscendMemory API**: rejected. It widens the API surface of a service that would still have to trust the caller (AscendAgent is the only client inside the trust boundary), and namespacing the existing partition key achieves identical isolation with zero Python changes.

### 8. Migration: single Liquibase changelog, backfill to `default`

One new changelog file: create `tenants`, insert the `default` row, add `tenant_id` columns with `defaultValue='default'` (backfilling existing rows in the same statement), then tighten to `NOT NULL` and swap indexes.

Qdrant and MinIO backfills are not Liquibase's job. A one-shot migration task (admin-triggered) does four things to existing points, in one pass: stamps `tenant_id='default'`, stamps `acl=["tenant:everyone:default"]` with `acl_source='tenant-default'`, a matching `acl_version`, and `acl_synced_at` set to the run time, creates the keyword payload indexes on both `tenant_id` and `acl`, and moves existing `markdown/`/`documents/` objects under `tenant/default/`.

The access-list stamp is not optional and it is not a later step. Under deny-by-default a point that carries a tenant and no access list is retrievable by nobody, so a tenant-only backfill would leave a single-company deployment upgrading in place with a corpus that is present, indexed, paid for, and invisible. Stamping `tenant:everyone:default` reproduces today's behaviour deliberately, as a grant anybody can see in the payload, rather than reproducing it by omission. It is the same thing ADR-M006 folds in as a migration step under the deny-by-default rule.

Until the task runs, pre-existing vectors are invisible to search (fail-closed, decision 2) — visible degradation, not silent leakage.

### 9. The presigned link stays mandatory under the tenant prefix check (owner decision, 2026-09-03)

An earlier draft of this change framed the presigned link as conditional. Its `rag-source-attachments` delta spoke of "any in-network presigned URL (`AiResponse.sources[*].downloadUrl`, when populated)" and called `GET /api/v1/documents/{id}/content` from `add-document-management-api` the primary client-facing download path, and the proposal repeated that framing by saying the client-facing download path moves to the agent endpoint. Both readings contradict the `rag-source-attachments` baseline, which guarantees a non-blank `downloadUrl` and `expiresAt` on every source entry.

The owner decided on 2026-09-03 that the link stays mandatory. Every source entry that is returned always carries a non-blank `downloadUrl` and `expiresAt`, `add-document-management-api` adds `documentId` and `contentPath` beside the link as further mandatory fields rather than instead of it, and neither download path is the primary one. The reason is that a caller must never have to implement two different ways of fetching the same source: a sometimes-absent link forces every client to carry both code paths plus the logic to choose between them. The same decision is recorded as D8 in `add-document-management-api/design.md`.

Nothing this change actually enforces is weakened by that. The tenant prefix check still refuses to presign any key outside `tenant/{tenantId}/`, and a refused `SourceRef` is dropped from the response entirely rather than returned as an entry with a missing link, so the guarantee that every returned entry carries a working link holds alongside the guarantee that no entry ever points outside the caller's tenant. The agent endpoint enforces the identical per-tenant ownership on the resolved document id, so both paths carry the same check and neither is a fallback for the other.

What that costs is the deployment posture: the object store has to stay reachable by clients wherever presigned links are handed out, so `harden-cloud-deployment` cannot treat the agent as the only public surface for source downloads. That cost is accepted deliberately and is not to be reopened here.

### 10. Exactly one method calls the similarity search, and an architecture test says so

A mandatory filter is only mandatory if there is one place it can be applied. Today `RagRetrievalService.performSimilaritySearch` is the only production call to `VectorStore.similaritySearch(...)`, which is a fact about the current code rather than a property of it. This change turns it into a property: that method stays the sole call site, it is the same method that composes the filter expression, and an architecture test asserts that no other production class calls `similaritySearch`, failing the build with the offending class named when one appears.

Without that test the guarantee is a convention, and a convention is exactly what a future feature breaks: someone adds a second retrieval path for a new surface, builds their own `SearchRequest`, gets working results in review because their test fixture holds one tenant's data, and the access axis is gone on that path with nothing to say so. ADR-M009 accepts that a security control living in application code is mitigated by tests rather than by architecture, and this is that test.

ArchUnit is the mechanism, added as a test-only dependency, since the alternative of grepping the source tree in a test is the same assertion written worse.

- **Alternative, wrap the vector store in a decorator that refuses an unfiltered request**: attractive, and weaker than it looks. A decorator can check that a filter expression is present, but not that it is the right one for this caller, so the check it can enforce is the one least likely to be got wrong. It also adds a bean between the resolver and the store for every provider. The architecture test costs one test dependency and asserts the thing that matters.
- **Alternative, trust code review**: rejected. The failure this prevents is invisible in a diff that looks like a legitimate new feature.

### 11. `tenant:everyone:{tenantId}` is a real principal, written on purpose

Tenant-wide readability is expressed by writing `tenant:everyone:{tenantId}` onto a chunk's `acl`, never by leaving the list off. Every authenticated caller of a tenant holds that principal, direct uploads stamp it, and the default-tenant migration stamps it onto every pre-existing point.

The point is that a broadly readable chunk and a chunk whose capture failed then look completely different from each other. One has a principal in its payload that says who may read it; the other has an empty list and is invisible. Under the alternative where a missing list means tenant-wide, those two states are identical in the payload and identical in behaviour, so every capture bug becomes a silent widening of access that nobody discovers by using the product. Recorded upstream as ADR-M006.

This change owns the pseudo-group because it owns the tenant identifier that names it and the migration that first writes it. `add-auth-and-identity` puts it into every caller's principal set, using the tenant id resolved from the token.

## Decision records

Three decisions in this change are architecturally significant, are not already recorded in the monorepo decision log (`docs/architecture/decisions/`, which covers the permission model itself as ADR-M004 through ADR-M009), and are drafted here for placement in `AscendAgent/docs/architecture/decisions/`:

| Draft | Records |
| :--- | :--- |
| [ADR-010](decisions/ADR-010-logical-tenant-isolation-via-discriminators.md) | Logical isolation via a mandatory discriminator on shared infrastructure, rather than a collection, bucket, or schema per tenant (design decision 1) |
| [ADR-011](decisions/ADR-011-single-similarity-search-call-site.md) | One method issues the similarity search, enforced by an architecture test (design decision 10) |
| [ADR-012](decisions/ADR-012-fail-closed-on-missing-tenant-or-principals.md) | Fail closed on a missing tenant context or a missing principal set, with no fallback to the default tenant and no fallback to a tenant-only filter (design decision 2) |

They are drafted inside this change folder so the change carries its own rationale, and task 9.1 moves them into `AscendAgent/docs/architecture/decisions/` when the change is implemented. Decisions 3, 6, and 7 (tenant slug format, key scoping, AscendMemory namespacing) stay design-local: they are settled here and nothing outside this change has to reason about them.

## Risks / Trade-offs

- [Missed enforcement point, some future code path queries Qdrant/MinIO/Redis without the tenant discriminator] → centralize: one `TenantContext`, one `PrincipalContext`, one metadata key constant, one key-builder per store, one similarity-search call site pinned by the architecture test in decision 10; integration tests assert cross-tenant and unpermitted within-tenant reads return zero results; `add-audit-and-gdpr-compliance` adds the second net later.
- [Qdrant filter cost on large collections] → Qdrant supports payload indexes; create keyword payload indexes on both `tenant_id` and `acl` per collection in the same migration step, so both conjuncts are index lookups rather than scans and neither can be forgotten separately.
- [Spring AI's `IN` operator does not translate to Qdrant match-any semantics the way the API shape suggests] → pin it with an integration test against a real Qdrant rather than a mocked `VectorStore`, since a mock confirms whatever was assumed. This is the one correctness property that depends on library behaviour rather than our code.
- [The access list on `SourceRef` goes stale between retrieval and presigning within one request] → the window is milliseconds and the presigned link's own 15-minute window dominates it; a revocation landing inside that window is covered by the disclosed staleness table in the permission-aware retrieval design rather than by a second read.
- [Request-scoped tenant and principals do not propagate to the presign task executor] → capture both on the request thread and pass them into the asynchronous work; reading the accessors inside the async lambda fails closed on every request, which is an outage rather than a control.
- [MinIO object move during migration is copy+delete, not atomic] → run the migration task with ingestion paused; the task is idempotent (skips already-moved keys) so it can resume after interruption.
- [`{tenantId}:{userId}` composite could collide with a raw userId containing `:` from the pre-tenant era] → memory written before this change stays under the unqualified id and is simply no longer retrieved; the migration task offers an optional re-key of existing AscendMemory entries to `default:{userId}`.
- [Sibling `add-chat-streaming-and-conversations` lands concurrently and both touch `PersistentChatMemory` key construction] → coordinate ordering at merge time; the key scheme here was chosen so the later change only replaces the final segment.
- [Fail-closed breaks existing unauthenticated local workflows the day this merges] → the dependency on `add-auth-and-identity` is explicit; local/dev profile behavior (e.g., a dev-issued token with `tenant=default`) is owned by that change.

## Migration Plan

1. Deploy with the new Liquibase changelog — Postgres tables/columns/indexes backfilled to `default` automatically at boot.
2. Run the one-shot data migration task: in one pass over both collections, stamp `tenant_id='default'` and `acl=["tenant:everyone:default"]` with `acl_source='tenant-default'`, a matching `acl_version`, and `acl_synced_at`; create the keyword payload indexes on `tenant_id` and on `acl`; move MinIO objects under `tenant/default/`; optionally re-key AscendMemory entries. The tenant stamp and the access-list stamp are one step, because a point carrying only the first is retrievable by nobody.
3. Verify, in this order: a `default`-tenant user holding `tenant:everyone:default` retrieves pre-existing documents; a second tenant's user gets zero hits for the same query; a `default`-tenant user whose principal set does not contain `tenant:everyone:default` also gets zero hits, which proves the access conjunct is doing work rather than being satisfied by everyone.
4. Rollback: the Liquibase columns are additive (old code ignores them); reverting the agent image restores pre-tenant behavior against Postgres/Redis. The Qdrant payload stamps are additive too, so old code ignores them and the payload indexes are harmless if nothing filters on them. Reverting after the MinIO move requires re-running the move task in reverse (task supports `--direction=down`).

## Open Questions

- Exact name and package of the tenant context accessor delivered by `add-auth-and-identity` — this design assumes `TenantContext.currentTenantId()`; align once that change's design is finalized.
- Exact name, package, and return type of the principal set accessor delivered by `add-auth-and-identity`: this design assumes `PrincipalContext.currentPrincipals()` returning an `Optional` of a principal set, so unresolved and empty stay distinguishable (decision 2). Align once that change's design is finalized; if it returns a bare set, this change adds the distinction at its own boundary rather than losing it.
- Who owns the administrator surface for assigning narrower access lists to direct uploads. Until it exists, direct uploads land on `tenant:everyone:{tenantId}`, which is correct and coarse. The open question is recorded in `docs/architecture/permission-aware-retrieval.md` and sits between `add-tenant-administration` and `add-document-management-api`.
- Whether the one-shot Qdrant/MinIO migration task ships as a Spring Boot CLI runner (`--spring.main.web-application-type=none`) or an admin-only HTTP endpoint; leaning CLI runner to keep it off the API surface. Decide at implementation.
