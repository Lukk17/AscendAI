## 1. Database - conversations schema and backfill

- [ ] 1.1 Create `apps/ascend-agent/src/main/resources/db/changelog/<NN>-conversations.xml` (`<NN>` is the next free two-digit number after the highest changelog present at implementation time) and register it in `db.changelog-master.yaml`: changeset creating `conversations` (`id` UUID PK, `tenant_id` VARCHAR(255) nullable, `user_id` VARCHAR(255) not null, `title` VARCHAR(255) not null, `created_at` / `updated_at` TIMESTAMP not null) plus index on `user_id`. Verify: task 1.5 passes.
- [ ] 1.2 Changeset adding nullable `chat_history.conversation_id` (UUID). Verify: task 1.5 passes.
- [ ] 1.3 Backfill changeset (SQL): insert one `conversations` row per distinct `chat_history.user_id` (title `Imported conversation`, `created_at` = MIN(created_at), `updated_at` = MAX(created_at), id via `gen_random_uuid()`), then `UPDATE chat_history SET conversation_id = c.id FROM conversations c WHERE chat_history.user_id = c.user_id`. Verify: task 1.5 passes.
- [ ] 1.4 Constraint changesets (separate from backfill): `NOT NULL` on `conversation_id`, FK to `conversations.id`, index `idx_chat_history_conversation_id`; add `rollback` blocks to every changeset in 1.1-1.4. Verify: task 1.5 passes and `liquibase rollback` of the new changesets leaves the schema at the previous level.
- [ ] 1.5 Migration test (Testcontainers Postgres): seed pre-migration `chat_history` rows for two users at the changelog level that precedes `<NN>`, run Liquibase, assert one `Imported conversation` row per user and every history row linked with non-null `conversation_id`. Verify: `./gradlew integrationTest --tests "*ConversationMigrationIT"` is green.

## 2. Domain - conversation entity, repository, service

- [ ] 2.1 Add a `Conversation` Spring Data JDBC entity (`@Table("conversations")`, `@Id`) in `model/` and `ConversationRepository extends CrudRepository` in `repository/`, with hand-written native `@Query` methods (no JPA, no derived paging) for: page by `user_id` ordered by `updated_at` desc, `findByIdAndUserId`, top-1 by `user_id` ordered by `updated_at` desc). Verify: a Testcontainers repository test returns the right page, owner match and most-recent row.
- [ ] 2.2 Add conversation-keyed queries to `ChatHistoryRepository`: recent history by `conversation_id`, paginated chronological messages by `conversation_id`, bulk delete by `conversation_id`. Verify: the same repository test covers each new query.
- [ ] 2.3 Create `ConversationService` in `service/`: `resolve(userId, conversationId)` implementing supplied-id ownership check (404 via exception → `ApiError`), most-recent fallback, and auto-create; `touch(conversationId)` bumping `updated_at` on message append. Verify: task 2.6 passes.
- [ ] 2.4 Implement auto-title in `ConversationService`: trim first prompt, truncate to 80 chars at a word boundary with ellipsis; explicit-create default `New conversation`. Verify: task 2.6 passes.
- [ ] 2.5 Implement `delete(userId, conversationId)`: Redis `DEL chat:<id>` first, then `chat_history` rows + `conversations` row in one transaction; foreign id → 404 without deleting. Verify: task 2.6 passes.
- [ ] 2.6 Unit tests for resolution (owned / foreign / omitted-with-existing / omitted-with-none), auto-title truncation edge cases, and delete ordering. Verify: `./gradlew test --tests "*ConversationServiceTest"` is green.

## 3. Re-key chat memory by conversation id

- [ ] 3.1 Change `AscendChatService` / `ChatHistoryService` to resolve the conversation up front and pass the conversation UUID into `PersistentChatMemory.get(...)` / `add(...)`; call `ConversationService.touch(...)` on save. Verify: task 3.4 passes.
- [ ] 3.2 Point `PersistentChatMemory.loadFromPostgres` / `persistToDb` at the `conversation_id` queries (keep writing `user_id` alongside for audit queries); keep Redis key format `chat:<conversationId>` untouched. Verify: task 3.4 passes.
- [ ] 3.2a Add a `conversationId` (UUID) field to `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/model/ChatHistory.java`, mapped to `chat_history.conversation_id`, and set it on every row `PersistentChatMemory.persistToDb` writes. Verify: task 3.4 asserts the column is written.
- [ ] 3.2b In `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/memory/ChatHistoryCompactionService.java`, make `applyToPostgres` set both `userId` and `conversationId` on the summary row it inserts, so the row passes the `NOT NULL` constraint from 1.4 and stays visible to the conversation's history queries. Verify: task 3.2c passes.
- [ ] 3.2c Test in `ChatHistoryCompactionServiceTest`: after a compaction the inserted summary row carries the owning user id and the conversation UUID, and a Testcontainers test shows the insert succeeds against the `NOT NULL` column. Verify: `./gradlew test --tests "*ChatHistoryCompactionServiceTest"` and the integration test are green.
- [ ] 3.3 Verify `ChatHistoryCompactionService` prefix replacement operates on `conversation_id`-scoped rows and the compaction trigger counts only that conversation's turns. Verify: a compaction test with two conversations of one user compacts only the targeted one.
- [ ] 3.4 Update existing `PersistentChatMemory` / `ChatHistoryService` / compaction tests for conversation-UUID keying; add a test that two conversations of one user have isolated histories. Verify: `./gradlew test` is green.
- [ ] 3.5 Confirm semantic-memory extraction still receives the userId (not the conversation id) in `AscendChatService`. Verify: a unit test asserts the extractor receives the user id.

## 4. Prompt endpoints - conversationId field

- [ ] 4.1 Add optional `conversationId` `@RequestParam` to `PromptController.prompt(...)` with `@Parameter` docs; resolve via `ConversationService` and return 404 `ApiError` for unknown/foreign ids before any model call. Verify: task 4.3 passes.
- [ ] 4.2 Add `conversationId` to `CustomMetadata` (additive, `@JsonInclude(NON_NULL)` preserved) and populate it on the synchronous response. Verify: task 4.3 passes.
- [ ] 4.3 Regression test: synchronous request without `conversationId` yields a response structurally identical to today's apart from the additive metadata field; request with a foreign id yields 404. Verify: `./gradlew test --tests "*PromptControllerTest"` is green.

## 5. Streaming endpoint

- [ ] 5.1 Add SSE event DTOs in `dto/` (`delta` `{content}`, `sources` `{sources[]}`, `done` `{metadata, conversationId}`, `error` `{status, code, message}`). Verify: a JSON serialization test per event type.
- [ ] 5.2 Implement streaming execution in `service/chat/` (new `StreamingChatExecutor` or `stream(...)` beside `ChatExecutor.execute(...)`): resolve provider via `ChatModelResolver`, apply the prompt-cache strategy with single undecorated retry on cache-config failure before first token, map `ChatClient.stream()` output to `delta` events. Verify: task 7.1 passes.
- [ ] 5.3 Wire post-stream side effects in the Flux termination hooks: accumulate deltas, persist one UserMessage + one AssistantMessage via `ChatHistoryService`, dispatch compaction with the request's `CompactionOverride`, fire semantic-memory extraction; on client cancel, persist at most once and stop the subscription. Verify: tasks 7.1 and 7.5 pass, and a cancel test persists at most one assistant message.
- [ ] 5.4 Emit the `sources` event by reusing `RagRetrievalService.buildSourceRefs` so each entry has the same `SourceFile` shape as the synchronous response (`downloadUrl`, `expiresAt`, `documentId`, `contentPath`, per add-document-management-api D8) before `done` when `attachSources=true`; emit terminal `error` event on mid-stream failure. Verify: tasks 7.2 and 7.3 pass.
- [ ] 5.5 Add `POST /api/v1/ai/prompt/stream` to `PromptController` (or a sibling controller) returning `Flux<ServerSentEvent<String>>` with `Cache-Control: no-store` and `X-Accel-Buffering: no`; run the same pre-stream validations as the sync endpoint (vision check, compaction-provider check, conversation ownership) returning plain JSON 4xx. Verify: tasks 7.1 and 7.2 pass and the response carries both headers.
- [ ] 5.6 OpenAPI annotations for the stream operation documenting the four event types. Verify: `/v3/api-docs` lists the stream operation with the four event types.

## 6. Conversation management API

- [ ] 6.1 Add request/response DTOs: page envelope `{items, page, size, totalItems, totalPages}`, conversation summary `{id, title, createdAt, updatedAt}`, message item `{role, content, createdAt}`, create/rename bodies with validation (`title` non-blank, ≤ 255). Verify: a validation test rejects a blank title and one of 256 characters.
- [ ] 6.2 Implement `ConversationController` under `/api/v1/conversations`: `GET` list (page/size, default 20, max 100, `updated_at` desc), `POST` create (201 + `Location`), `GET /{id}/messages` (chronological, paginated), `PATCH /{id}` rename, `DELETE /{id}` (204). Verify: task 7.4 passes.
- [ ] 6.3 Enforce user scoping on every operation (foreign id → 404) using the same `X-User-Id` / default-id resolution as `PromptController`. Verify: a MockMvc test returns 404 for a foreign id on every operation.
- [ ] 6.4 OpenAPI annotations for all five operations. Verify: `/v3/api-docs` lists all five operations.

## 7. Tests - integration

- [ ] 7.1 SSE integration test (Testcontainers stack, stubbed/local provider): POST to `/api/v1/ai/prompt/stream`, assert `Content-Type: text/event-stream`, at least one `delta` event, exactly one terminal `done` event carrying `conversationId`, and that concatenated deltas equal the persisted assistant message. Verify: the test is green.
- [ ] 7.2 SSE error-path tests: pre-stream 400 for unknown `compactionProvider` as plain JSON; mid-stream provider failure produces exactly one `error` event and no `done`. Verify: the tests are green.
- [ ] 7.3 SSE `attachSources=true` test: one `sources` event before `done` whose entries each carry non-blank `downloadUrl`, `expiresAt`, `documentId` and `contentPath`. Verify: the test is green.
- [ ] 7.4 Conversation CRUD integration tests: create → list ordering → rename → messages pagination → delete cascade (assert Redis key gone, zero `chat_history` rows, 404 on subsequent prompt with the deleted id). Verify: the tests are green.
- [ ] 7.5 Sync/stream parity test: same prompt through both endpoints in two conversations persists structurally identical history. Verify: the test is green.
- [ ] 7.6 Run `./gradlew test integrationTest` and fix regressions. Verify: both tasks are green.

## 8. Documentation and API collection

- [ ] 8.1 Update `apps/ascend-agent/AGENTS.md`: document `/api/v1/ai/prompt/stream` (event schema), the `conversationId` field, and the `/api/v1/conversations` API in the architecture/API sections. Verify: the file names the stream endpoint, the event schema and every conversation operation.
- [ ] 8.2 Add Bruno requests under `docs/api/request/AscendAI/ascend-agent/`: stream prompt (with SSE note), list conversations, create, get messages, rename, delete. Verify: `bru run` of each request against a local stack returns the expected status.
- [ ] 8.3 Add an ADR in `apps/ascend-agent/docs/architecture/decisions/`, numbered with the next free number at implementation time (ADR-010 is already taken), recording the SSE-endpoint-over-content-negotiation and conversation-resolution decisions. Verify: the ADR file exists and the decisions index lists it.
- [ ] 8.4 Tick the checkboxes in this file as each task passes its check. Verify: no task is ticked without its check passing.
