## 1. Tenant model and Liquibase migration

- [ ] 1.1 Create `AscendAgent/src/main/resources/db/changelog/02-tenant-isolation.xml`: `tenants` table (`id VARCHAR(64) PK`, `display_name`, `created_at`), insert reserved `default` row, register in `db.changelog-master.yaml`
- [ ] 1.2 Same changelog: add `tenant_id VARCHAR(64)` to `chat_history` and `user_instructions` with `defaultValue='default'` (backfills existing rows), then add NOT NULL constraints
- [ ] 1.3 Same changelog: change `user_instructions` primary key to composite `(tenant_id, user_id)`; create index `idx_chat_history_tenant_user` on `chat_history(tenant_id, user_id)` and drop `idx_chat_history_user_id`
- [ ] 1.4 Add `Tenant` JPA entity + `TenantRepository` under `model/` and `repository/`; add `tenant_id` to the `ChatHistory` entity and `UserInstruction` composite id
- [ ] 1.5 Test (Testcontainers `integrationTest`): boot against a Postgres seeded with pre-tenant rows, assert Liquibase backfills `tenant_id='default'` and the composite index exists

## 2. Tenant context plumbing (consumes add-auth-and-identity)

- [ ] 2.1 Add `TenantContext` accessor (request-scoped holder) that returns the tenant id resolved from the JWT `tenant` claim by the `add-auth-and-identity` filter; align the exact hook once that change's design is final
- [ ] 2.2 Validate the tenant id against `[a-z0-9-]{1,64}` at the boundary; reject malformed values with a client error
- [ ] 2.3 Fail-closed guard: `TenantContext.currentTenantId()` throws when unresolved; map the exception to 401/403 in the global exception handler
- [ ] 2.4 Test: request whose form field claims a different tenant than the JWT — assert all operations use the JWT tenant (forged tenant rejected)
- [ ] 2.5 Test: tenant-scoped service call with empty context throws and performs no store access

## 3. Qdrant isolation

- [ ] 3.1 Add `TENANT_ID` constant to `service/ingestion/IngestionMetadataKeys.java`
- [ ] 3.2 Stamp `tenant_id` metadata on every `Document` in all ingestion producers (Markdown, Docling, PaddleOCR, Unstructured paths); fail ingestion when tenant context is unresolved
- [ ] 3.3 In `service/rag/RagRetrievalService.java`, build the `SearchRequest` with a `FilterExpressionBuilder`-based `tenant_id == currentTenant` filter; throw before searching when tenant context is unresolved
- [ ] 3.4 Scope `documentService.removeOldDocuments(...)` dedup deletes by `tenant_id` in addition to `source`
- [ ] 3.5 Test (`RagRetrievalServiceTenantTest`): verify the outgoing `SearchRequest` carries the tenant filter expression, and that a missing tenant context throws without invoking the vector store
- [ ] 3.6 Integration test (Testcontainers Qdrant): ingest a document as tenant `acme`, search as tenant `globex` — assert zero hits; search as `acme` — assert hits returned
- [ ] 3.7 Integration test: re-upload the same filename as tenant `acme` — assert `globex` points with the same `source` are untouched

## 4. MinIO isolation

- [ ] 4.1 In `controller/IngestionController.java`, build upload keys as `tenant/{tenantId}/{folder}/{safeName}` from `TenantContext` (never from user input)
- [ ] 4.2 In `ManualIngestionService`, resolve the effective scan prefix as `tenant/{tenantId}/` + caller-supplied `prefix`; reject or neutralize values that would escape the tenant prefix
- [ ] 4.3 In `service/rag/S3PresignedUrlService.java`, refuse to presign any key not starting with `tenant/{tenantId}/` for the caller's tenant; omit the source and log one WARN with `s3://{bucket}/{key}`
- [ ] 4.4 Test (`S3PresignedUrlServiceTenantTest`): presign request for `tenant/acme/...` as tenant `globex` — assert refused, WARN logged, request still returns 200 with remaining sources
- [ ] 4.5 Integration test (Testcontainers MinIO): uploads from two tenants with identical filenames land at distinct keys and neither overwrites the other
- [ ] 4.6 Integration test: `POST /api/v1/ingestion/run` with `prefix=tenant/globex/` as tenant `acme` ingests nothing outside `tenant/acme/`

## 5. Chat history and user instructions scoping

- [ ] 5.1 In `memory/PersistentChatMemory.java`, change key construction to `chat:{tenantId}:{userId}` (single key-builder helper; tenant segment first for future `conversationId` compatibility)
- [ ] 5.2 In `service/user/UserInstructionService.java`, change key construction to `user:{tenantId}:{userId}:instructions`
- [ ] 5.3 Add `tenant_id` to `ChatHistoryRepository` queries (`findRecentHistory` and writes in `persistToDb`) and to `UserInstructionService` Postgres access
- [ ] 5.4 Test (`PersistentChatMemoryTenantTest`): same userId under two tenants — writes land on distinct Redis keys and Postgres rows; loads never mix
- [ ] 5.5 Test: history read/write with empty tenant context throws and creates no legacy-format `chat:{userId}` key

## 6. AscendMemory scoping

- [ ] 6.1 In `SemanticMemoryClient`, compose outbound `user_id` as `{tenantId}:{userId}` from `TenantContext` in one private helper used by search, insert, wipe, and delete
- [ ] 6.2 Fail closed: unresolved tenant context throws for search/wipe/delete and short-circuits with one WARN for fire-and-forget insert
- [ ] 6.3 Test (`SemanticMemoryClientTenantTest`): assert outgoing search URL contains `user_id=acme:frosty`, insert body contains `"user_id":"acme:frosty"`, wipe body likewise; assert no request ever carries the bare userId
- [ ] 6.4 Integration test: insert a fact as `acme:frosty`, search as `globex:frosty` — assert zero items returned

## 7. Data migration for existing deployments

- [ ] 7.1 Implement the one-shot migration task (Spring Boot CLI runner, per design open question): stamp `tenant_id='default'` on all points in `ascendai-768` and `ascendai-1536`, create keyword payload index on `tenant_id` per collection
- [ ] 7.2 Same task: move MinIO objects from `markdown/` and `documents/` to `tenant/default/markdown/` and `tenant/default/documents/` (copy + delete, idempotent, skips already-moved keys, supports `--direction=down`)
- [ ] 7.3 Same task (optional flag): re-key existing AscendMemory entries from `{userId}` to `default:{userId}`
- [ ] 7.4 Test: run the task twice against seeded stores — assert idempotence (second run is a no-op) and that a `default`-tenant search retrieves pre-migration documents

## 8. Verification and documentation

- [ ] 8.1 End-to-end check against a live stack: ingest as tenant A, prompt as tenant B with `attachSources=true` — assert zero RAG hits, `sources: []`, no presigned URL for tenant A's objects, and separate chat histories
- [ ] 8.2 Run `./gradlew build test integrationTest` clean
- [ ] 8.3 Update `AscendAgent/AGENTS.md` (key dependencies / conventions) and `docs/architecture/` with an ADR for logical tenant isolation via mandatory discriminators
- [ ] 8.4 Update `docs/api/request/AscendAI/` Bruno collection examples where object keys or identifiers changed shape
