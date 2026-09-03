## Why

AscendAI has no tenant concept anywhere. Every data plane is a single shared pool, which makes it impossible to host two companies on one deployment and blocks consolidating today's per-company deployments later:

1. **RAG is fully shared.** Both Qdrant collections (`ascendai-768` / `ascendai-1536`, `AscendAgent/src/main/resources/application.yaml` `app.vectorstore.collections`) hold everyone's chunks. `RagRetrievalService.retrieve(...)` builds its `SearchRequest` with query + topK + threshold only — no owner filter of any kind (`AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/rag/RagRetrievalService.java:77-88`). Ingestion stamps only `source` / `type` / `title` metadata (`service/ingestion/IngestionMetadataKeys.java`). Any prompt retrieves any company's documents.
2. **MinIO is one shared bucket.** Uploads land in `knowledge-base` under `markdown/` or `documents/` keyed by sanitized filename only (`controller/IngestionController.java:101-105`). Two tenants uploading `handbook.pdf` silently overwrite each other, and the `attachSources` presigning path (`service/rag/S3PresignedUrlService.java`, `RagRetrievalService.buildSourceRefs`) will happily hand tenant A a signed download link to tenant B's document.
3. **Chat history and instructions key on userId alone.** Redis key is `"chat:" + conversationId` where conversationId == userId (`memory/PersistentChatMemory.java:69,183`), Postgres `chat_history` has only `user_id` (`db/changelog/01-initial-schema.xml`), and user instructions live at `"user:" + userId + ":instructions"` (`service/user/UserInstructionService.java:31`). A userId collision across companies merges their conversations.
4. **AscendMemory trusts the caller-supplied `user_id`** and partitions shared Qdrant collections by it, so the same collision leaks long-term memories across companies.

The sibling `add-auth-and-identity` change is introducing authenticated identity with a JWT `tenant` claim. This change consumes that claim and makes every data plane enforce it, fail-closed.

## What Changes

- **Tenant model**: new `tenants` table plus `tenant_id` columns on `user_instructions` and `chat_history` (Liquibase changelog additions with indexes). Tenant identifiers are constrained slugs (`[a-z0-9-]{1,64}`) so they can be embedded safely in Redis keys, S3 prefixes, and composite ids.
- **Tenant context, fail-closed**: the agent resolves the current tenant from the JWT `tenant` claim delivered by `add-auth-and-identity`. Any tenant-scoped operation (RAG search, presign, chat history, instructions, memory) executed without a resolved tenant fails with an error — never falls through to unfiltered/shared behavior.
- **Qdrant isolation**: every ingested chunk is stamped with `tenant_id` metadata; every similarity search applies a mandatory Spring AI `FilterExpression` on `tenant_id`. **BREAKING** for existing collections: points without `tenant_id` become unreachable until the default-tenant backfill runs.
- **MinIO isolation**: object keys become `tenant/<tenantId>/markdown/...` and `tenant/<tenantId>/documents/...`; presigning refuses any key outside the caller's tenant prefix; manual ingestion scans (`POST /api/v1/ingestion/run`) are scoped to the caller's tenant prefix. **BREAKING** key layout change, covered by migration.
- **Chat history + instructions scoping**: Redis keys become `chat:{tenantId}:{userId}` and `user:{tenantId}:{userId}:instructions`; Postgres reads/writes filter on `(tenant_id, user_id)` with a composite index. Key shape stays compatible with the future `conversationId` from `add-chat-streaming-and-conversations` (tenant segment first, last segment swaps).
- **AscendMemory scoping**: the agent sends tenant-qualified user ids (`{tenantId}:{userId}`) on every AscendMemory call, so memories cannot cross tenants without any AscendMemory code change.
- **Migration path**: a `default` tenant row is created; all existing Postgres rows, Qdrant points, and MinIO objects are mapped/backfilled to it, so existing single-company deployments upgrade in place.

## Capabilities

### New Capabilities

- `tenant-isolation`: the tenant model itself — tenant entity and persistence, fail-closed tenant context resolution from the JWT claim, tenant id format rules, and the default-tenant migration for existing deployments.

### Modified Capabilities

- `rag-retrieval`: similarity search gains a mandatory tenant filter; retrieval without tenant context fails closed.
- `rag-source-attachments`: presigned URLs are only issued for objects under the caller's tenant prefix. Every source entry that is returned still carries a non-blank `downloadUrl` and `expiresAt`, exactly as the baseline guarantees. `add-document-management-api` lands later and adds `documentId` and `contentPath` beside that link as further mandatory fields, and its `GET /api/v1/documents/{id}/content` endpoint enforces the same per-tenant ownership on the resolved document id, so both download paths carry the tenant check and neither of them is the primary one.
- `ingestion-security`: storage keys gain the tenant prefix on top of filename sanitization; ingested chunks are stamped with tenant metadata.
- `ingestion-correctness`: upload idempotency (replace-on-re-upload) becomes per-tenant; identical filenames in different tenants coexist.
- `chat-history-persistence`: Redis key scheme and Postgres persistence become tenant+user scoped.
- `semantic-memory-client`: all AscendMemory calls carry tenant-qualified user ids.

## Impact

- **Dependency**: `add-auth-and-identity` must land first — this change consumes its JWT `tenant` claim and does not re-specify authentication.
- **AscendAgent code**: `RagRetrievalService`, `S3PresignedUrlService`, `IngestionController`, `ManualIngestionService`, ingestion producers stamping `IngestionMetadataKeys`, `PersistentChatMemory`, `UserInstructionService`, `SemanticMemoryClient` call sites, plus a new tenant context holder and `Tenant` entity/repository.
- **Database**: new Liquibase changelog (tenants table, `tenant_id` columns, composite indexes, default-tenant backfill) in `AscendAgent/src/main/resources/db/changelog/`.
- **Data stores**: Qdrant point payloads (new `tenant_id` key), MinIO object key layout, Redis key namespace.
- **No AscendMemory / Python service changes**: isolation rides on the `user_id` namespace they already partition by.
- **Out of scope** (sibling changes): authentication itself, conversation model, document management API, usage metering, audit/GDPR, cloud hardening, document connectors.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/jpa-patterns`
- `/database-migrations`
- `/api-design`
- `/python-patterns`
- `/springboot-tdd`
