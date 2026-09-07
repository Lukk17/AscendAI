## Why

AscendAI has no tenant concept anywhere. Every data plane is a single shared pool, which makes it impossible to host two companies on one deployment and blocks consolidating today's per-company deployments later:

1. **RAG is fully shared.** Both Qdrant collections (`ascendai-768` / `ascendai-1536`, `apps/ascend-ai-agent/src/main/resources/application.yaml` `app.vectorstore.collections`) hold everyone's chunks. `RagRetrievalService.retrieve(...)` builds its `SearchRequest` with query + topK + threshold only — no owner filter of any kind (`apps/ascend-ai-agent/src/main/java/com/lukk/ascend/ai/agent/service/rag/RagRetrievalService.java:77-88`). Ingestion stamps only `source` / `type` / `title` metadata (`service/ingestion/IngestionMetadataKeys.java`). Any prompt retrieves any company's documents.
2. **MinIO is one shared bucket.** Uploads land in `knowledge-base` under `markdown/` or `documents/` keyed by sanitized filename only (`controller/IngestionController.java:101-105`). Two tenants uploading `handbook.pdf` silently overwrite each other, and the `attachSources` presigning path (`service/rag/S3PresignedUrlService.java`, `RagRetrievalService.buildSourceRefs`) will happily hand tenant A a signed download link to tenant B's document.
3. **Chat history and instructions key on userId alone.** Redis key is `"chat:" + conversationId` where conversationId == userId (`memory/PersistentChatMemory.java:69,183`), Postgres `chat_history` has only `user_id` (`db/changelog/01-initial-schema.xml`), and user instructions live at `"user:" + userId + ":instructions"` (`service/user/UserInstructionService.java:31`). A userId collision across companies merges their conversations.
4. **AscendMemory trusts the caller-supplied `user_id`** and partitions shared Qdrant collections by it, so the same collision leaks long-term memories across companies.
5. **Inside a company, everything is readable by everyone.** A company's documents are not uniformly readable by that company: the board pack, the salary bands, and the postmortem naming a customer are not for everyone, and SharePoint and Google Drive enforce exactly that on every file open. Once those files are chunked into Qdrant, nothing carries who may read them: `IngestionMetadataKeys` records `source`, `type`, and `title`, none of which says anything about readers. So separating companies is necessary and not sufficient. A deployment that isolates tenants perfectly still answers a support engineer's question out of the board pack.

The sibling `add-auth-and-identity` change is introducing authenticated identity with a JWT `tenant` claim and a resolved set of group principals per caller. This change consumes both and makes every data plane enforce them, fail-closed, on two axes: the tenant that owns a chunk, and the access list that says who inside that tenant may read it. The settled model behind the second axis is [permission-aware retrieval](../../../docs/architecture/permission-aware-retrieval.md), recorded as ADR-M004 through ADR-M009.

## What Changes

- **Tenant model**: new `tenants` table plus `tenant_id` columns on `user_instructions` and `chat_history` (Liquibase changelog additions with indexes). Tenant identifiers are constrained slugs (`[a-z0-9-]{1,64}`) so they can be embedded safely in Redis keys, S3 prefixes, and composite ids.
- **Tenant context and principal set, fail-closed**: the agent resolves the current tenant from the JWT `tenant` claim and the caller's group principals from the resolution that `add-auth-and-identity` delivers. Any tenant-scoped operation (RAG search, presign, chat history, instructions, memory) executed without a resolved tenant fails with an error, and search and presign additionally fail without a resolved principal set, never falling through to unfiltered behaviour, a shared key, or a filter carrying only the tenant conjunct. An empty resolved principal set is a valid answer that matches nothing; an unresolved one is a failure.
- **Qdrant isolation on both axes**: every ingested chunk is stamped with `tenant_id` plus the access-list contract `acl`, `acl_source`, `acl_version`, and `acl_synced_at`; every similarity search applies one mandatory Spring AI `FilterExpression` composed of both conjuncts, `tenant_id == '<currentTenant>' AND acl IN <principalSet>`, built through `FilterExpressionBuilder` at the single place a search request is constructed. Direct uploads stamp `acl` as `["tenant:everyone:{tenantId}"]`, which reproduces today's tenant-wide readability as an explicit grant. A chunk whose list is absent or empty is retrieved by nobody, and that follows from the filter rather than from special-case code. **BREAKING** for existing collections: points without both `tenant_id` and `acl` are unreachable until the default-tenant backfill runs.
- **One search call site, pinned**: `RagRetrievalService.performSimilaritySearch` stays the only production caller of `VectorStore.similaritySearch(...)`, and an architecture test fails the build when a second call site appears. A mandatory filter is only mandatory when there is one place it can be applied.
- **Payload indexes on both filter fields**: keyword payload indexes on `tenant_id` and on `acl` in both collections, created in the same migration step. Without the `acl` index the access conjunct degrades to a walk of the collection.
- **MinIO isolation**: object keys become `tenant/<tenantId>/markdown/...` and `tenant/<tenantId>/documents/...`; presigning refuses any key outside the caller's tenant prefix and additionally re-checks the reference's access list against the caller's principal set, dropping a refused reference from the response entirely; manual ingestion scans (`POST /api/v1/ingestion/run`) are scoped to the caller's tenant prefix. **BREAKING** key layout change, covered by migration.
- **Chat history + instructions scoping**: Redis keys become `chat:{tenantId}:{userId}` and `user:{tenantId}:{userId}:instructions`; Postgres reads/writes filter on `(tenant_id, user_id)` with a composite index. Key shape stays compatible with the future `conversationId` from `add-chat-streaming-and-conversations` (tenant segment first, last segment swaps).
- **AscendMemory scoping**: the agent sends tenant-qualified user ids (`{tenantId}:{userId}`) on every AscendMemory call, so memories cannot cross tenants without any AscendMemory code change.
- **Migration path**: a `default` tenant row is created; all existing Postgres rows, Qdrant points, and MinIO objects are mapped/backfilled to it, so existing single-company deployments upgrade in place. The Qdrant backfill stamps `tenant_id = 'default'` and `acl = ["tenant:everyone:default"]` in the same pass, because under deny-by-default a point carrying a tenant and no access list is retrievable by nobody, and a tenant-only backfill would leave an upgraded deployment with an invisible corpus.

## Capabilities

### New Capabilities

- `tenant-isolation`: the isolation model itself, meaning the two axes and their vocabulary, tenant entity and persistence, the chunk access-list payload contract (`acl`, `acl_source`, `acl_version`, `acl_synced_at`), the `tenant:everyone:{tenantId}` pseudo-group, the mandatory payload indexes on both filter fields, fail-closed resolution of tenant context and principal set, tenant id format rules, and the default-tenant migration for existing deployments.

### Modified Capabilities

- `rag-retrieval`: similarity search gains one mandatory filter expression carrying both the tenant equality and the access-list intersection; a chunk with no access list is retrieved by nobody as a consequence of that expression; exactly one method issues the search and an architecture test holds it there; retrieval without tenant context or without a resolved principal set fails closed.
- `rag-source-attachments`: presigned URLs are only issued for objects under the caller's tenant prefix whose access list intersects the caller's principal set, and a reference failing either check is dropped from the response entirely rather than returned without a link, which is the presigner's existing `Optional` shape rather than a new response shape. Every source entry that is returned still carries a non-blank `downloadUrl` and `expiresAt`, exactly as the baseline guarantees. `add-document-management-api` lands later and adds `documentId` and `contentPath` beside that link as further mandatory fields, and its `GET /api/v1/documents/{id}/content` endpoint enforces the same per-tenant and per-access-list ownership on the resolved document id, so both download paths carry both checks and neither of them is the primary one.
- `ingestion-security`: storage keys gain the tenant prefix on top of filename sanitization; ingested chunks are stamped with tenant metadata and with an explicit access list, defaulting to the tenant-everyone pseudo-group for direct uploads.
- `ingestion-correctness`: upload idempotency (replace-on-re-upload) becomes per-tenant; identical filenames in different tenants coexist.
- `chat-history-persistence`: Redis key scheme and Postgres persistence become tenant+user scoped.
- `semantic-memory-client`: all AscendMemory calls carry tenant-qualified user ids.

## Impact

- **Dependency**: `add-auth-and-identity` must land first, because this change consumes its JWT `tenant` claim and its resolved principal set, and re-specifies neither authentication, principal identifier format, nor membership resolution. A filter built from anything a client can type is not a filter.
- **Successor**: `add-document-connectors` fills the access lists this change makes enforceable, replacing the tenant-everyone default on connector-sourced documents with lists captured from the source. Until it lands, access lists are correct and coarse.
- **ascend-ai-agent code**: `RagRetrievalService` (composed filter, one search call site, `acl` carried onto `SourceRef`), `S3PresignedUrlService` (both re-checks, context captured before the async fan-out), `IngestionController`, `ManualIngestionService`, ingestion producers stamping `IngestionMetadataKeys`, `PersistentChatMemory`, `UserInstructionService`, `SemanticMemoryClient` call sites, plus a new tenant context holder, principal-set accessor consumption, and `Tenant` entity/repository.
- **Build**: an architecture-test dependency (ArchUnit, test scope only) for the single-call-site assertion.
- **Database**: new Liquibase changelog (tenants table, `tenant_id` columns, composite indexes, default-tenant backfill) in `apps/ascend-ai-agent/src/main/resources/db/changelog/`.
- **Data stores**: Qdrant point payloads (new `tenant_id`, `acl`, `acl_source`, `acl_version`, `acl_synced_at` keys plus keyword payload indexes on `tenant_id` and `acl`), MinIO object key layout, Redis key namespace.
- **Documentation**: three architecture decision records drafted under `openspec/changes/add-tenant-isolation/decisions/` and placed into `apps/ascend-ai-agent/docs/architecture/decisions/` at implementation.
- **No AscendMemory / Python service changes**: isolation rides on the `user_id` namespace they already partition by.
- **Out of scope** (sibling changes): authentication itself, principal resolution and caching, connector-side access-list capture, the administrator surface for assigning narrower lists to direct uploads, conversation model, document management API, usage metering, audit/GDPR, cloud hardening.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/jpa-patterns`
- `/database-migrations`
- `/api-design`
- `/python-patterns`
- `/springboot-tdd`
- `/springboot-security`
- `/security-review`
