## 1. Database — conversations schema and backfill

- [ ] 1.1 Create `apps/ascend-ai-agent/src/main/resources/db/changelog/02-conversations.xml` and register it in `db.changelog-master.yaml`: changeset creating `conversations` (`id` UUID PK, `tenant_id` VARCHAR(255) nullable, `user_id` VARCHAR(255) not null, `title` VARCHAR(255) not null, `created_at` / `updated_at` TIMESTAMP not null) plus index on `user_id`
- [ ] 1.2 Changeset adding nullable `chat_history.conversation_id` (UUID)
- [ ] 1.3 Backfill changeset (SQL): insert one `conversations` row per distinct `chat_history.user_id` (title `Imported conversation`, `created_at` = MIN(created_at), `updated_at` = MAX(created_at), id via `gen_random_uuid()`), then `UPDATE chat_history SET conversation_id = c.id FROM conversations c WHERE chat_history.user_id = c.user_id`
- [ ] 1.4 Constraint changesets (separate from backfill): `NOT NULL` on `conversation_id`, FK to `conversations.id`, index `idx_chat_history_conversation_id`; add `rollback` blocks to every changeset in 1.1-1.4
- [ ] 1.5 Migration test (Testcontainers Postgres): seed pre-migration `chat_history` rows for two users at changelog level 01, run Liquibase, assert one `Imported conversation` row per user and every history row linked with non-null `conversation_id`

## 2. Domain — conversation entity, repository, service

- [ ] 2.1 Add `Conversation` JPA entity in `model/` and `ConversationRepository` in `repository/` (finders: page by `user_id` ordered by `updated_at` desc, `findByIdAndUserId`, top-1 by `user_id` ordered by `updated_at` desc)
- [ ] 2.2 Add conversation-keyed queries to `ChatHistoryRepository`: recent history by `conversation_id`, paginated chronological messages by `conversation_id`, bulk delete by `conversation_id`
- [ ] 2.3 Create `ConversationService` in `service/`: `resolve(userId, conversationId)` implementing supplied-id ownership check (404 via exception → `ApiError`), most-recent fallback, and auto-create; `touch(conversationId)` bumping `updated_at` on message append
- [ ] 2.4 Implement auto-title in `ConversationService`: trim first prompt, truncate to 80 chars at a word boundary with ellipsis; explicit-create default `New conversation`
- [ ] 2.5 Implement `delete(userId, conversationId)`: Redis `DEL chat:<id>` first, then `chat_history` rows + `conversations` row in one transaction; foreign id → 404 without deleting
- [ ] 2.6 Unit tests for resolution (owned / foreign / omitted-with-existing / omitted-with-none), auto-title truncation edge cases, and delete ordering

## 3. Re-key chat memory by conversation id

- [ ] 3.1 Change `AscendChatService` / `ChatHistoryService` to resolve the conversation up front and pass the conversation UUID into `PersistentChatMemory.get(...)` / `add(...)`; call `ConversationService.touch(...)` on save
- [ ] 3.2 Point `PersistentChatMemory.loadFromPostgres` / `persistToDb` at the `conversation_id` queries (keep writing `user_id` alongside for audit queries); keep Redis key format `chat:<conversationId>` untouched
- [ ] 3.3 Verify `ChatHistoryCompactionService` prefix replacement operates on `conversation_id`-scoped rows and the compaction trigger counts only that conversation's turns
- [ ] 3.4 Update existing `PersistentChatMemory` / `ChatHistoryService` / compaction tests for conversation-UUID keying; add a test that two conversations of one user have isolated histories
- [ ] 3.5 Confirm semantic-memory extraction still receives the userId (not the conversation id) in `AscendChatService`

## 4. Prompt endpoints — conversationId field

- [ ] 4.1 Add optional `conversationId` `@RequestParam` to `PromptController.prompt(...)` with `@Parameter` docs; resolve via `ConversationService` and return 404 `ApiError` for unknown/foreign ids before any model call
- [ ] 4.2 Add `conversationId` to `CustomMetadata` (additive, `@JsonInclude(NON_NULL)` preserved) and populate it on the synchronous response
- [ ] 4.3 Regression test: synchronous request without `conversationId` yields a response structurally identical to today's apart from the additive metadata field; request with a foreign id yields 404

## 5. Streaming endpoint

- [ ] 5.1 Add SSE event DTOs in `dto/` (`delta` `{content}`, `sources` `{sources[]}`, `done` `{metadata, conversationId}`, `error` `{status, code, message}`)
- [ ] 5.2 Implement streaming execution in `service/chat/` (new `StreamingChatExecutor` or `stream(...)` beside `ChatExecutor.execute(...)`): resolve provider via `ChatModelResolver`, apply the prompt-cache strategy with single undecorated retry on cache-config failure before first token, map `ChatClient.stream()` output to `delta` events
- [ ] 5.3 Wire post-stream side effects in the Flux termination hooks: accumulate deltas, persist one UserMessage + one AssistantMessage via `ChatHistoryService`, dispatch compaction with the request's `CompactionOverride`, fire semantic-memory extraction; on client cancel, persist at most once and stop the subscription
- [ ] 5.4 Emit the `sources` event (reusing the existing source-attachment resolution and `SourceFile` shape) before `done` when `attachSources=true`; emit terminal `error` event on mid-stream failure
- [ ] 5.5 Add `POST /api/v1/ai/prompt/stream` to `PromptController` (or a sibling controller) returning `Flux<ServerSentEvent<String>>` with `Cache-Control: no-store` and `X-Accel-Buffering: no`; run the same pre-stream validations as the sync endpoint (vision check, compaction-provider check, conversation ownership) returning plain JSON 4xx
- [ ] 5.6 OpenAPI annotations for the stream operation documenting the four event types

## 6. Conversation management API

- [ ] 6.1 Add request/response DTOs: page envelope `{items, page, size, totalItems, totalPages}`, conversation summary `{id, title, createdAt, updatedAt}`, message item `{role, content, createdAt}`, create/rename bodies with validation (`title` non-blank, ≤ 255)
- [ ] 6.2 Implement `ConversationController` under `/api/v1/conversations`: `GET` list (page/size, default 20, max 100, `updated_at` desc), `POST` create (201 + `Location`), `GET /{id}/messages` (chronological, paginated), `PATCH /{id}` rename, `DELETE /{id}` (204)
- [ ] 6.3 Enforce user scoping on every operation (foreign id → 404) using the same `X-User-Id` / default-id resolution as `PromptController`
- [ ] 6.4 OpenAPI annotations for all five operations

## 7. Tests — integration

- [ ] 7.1 SSE integration test (Testcontainers stack, stubbed/local provider): POST to `/api/v1/ai/prompt/stream`, assert `Content-Type: text/event-stream`, at least one `delta` event, exactly one terminal `done` event carrying `conversationId`, and that concatenated deltas equal the persisted assistant message
- [ ] 7.2 SSE error-path tests: pre-stream 400 for unknown `compactionProvider` as plain JSON; mid-stream provider failure produces exactly one `error` event and no `done`
- [ ] 7.3 SSE `attachSources=true` test: one `sources` event before `done` with well-formed `SourceFile` entries
- [ ] 7.4 Conversation CRUD integration tests: create → list ordering → rename → messages pagination → delete cascade (assert Redis key gone, zero `chat_history` rows, 404 on subsequent prompt with the deleted id)
- [ ] 7.5 Sync/stream parity test: same prompt through both endpoints in two conversations persists structurally identical history
- [ ] 7.6 Run `./gradlew test integrationTest` and fix regressions

## 8. Documentation and API collection

- [ ] 8.1 Update `apps/ascend-ai-agent/AGENTS.md`: document `/api/v1/ai/prompt/stream` (event schema), the `conversationId` field, and the `/api/v1/conversations` API in the architecture/API sections
- [ ] 8.2 Add Bruno requests under `docs/api/request/AscendAI/ascend-agent/`: stream prompt (with SSE note), list conversations, create, get messages, rename, delete
- [ ] 8.3 Add an ADR in `apps/ascend-ai-agent/docs/architecture/decisions/` recording the SSE-endpoint-over-content-negotiation and conversation-resolution decisions
- [ ] 8.4 Update `openspec/changes/add-chat-streaming-and-conversations/tasks.md` checkboxes as work proceeds
