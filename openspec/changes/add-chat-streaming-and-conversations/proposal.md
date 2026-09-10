# Add Chat Streaming and Conversations

## Why

AscendAI's chat surface today is a single blocking call and a single eternal thread per user. `POST /api/v1/ai/prompt` (`apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/controller/PromptController.java`) holds the HTTP connection until the full LLM answer is assembled — 10-60 s on long RAG turns — and chat memory is keyed by `conversationId == userId` (`memory/PersistentChatMemory.java`, Redis key `chat:<userId>`, Postgres `chat_history.user_id`), so every user has exactly one conversation, forever, with no way to list it, name it, start a fresh one, or delete it.

The upcoming Flutter client (mobile + web — a separate future change; no UI is specced here) needs the two API primitives every modern chat product has:

1. **Token streaming** — perceived latency drops from "whole answer" to "first token". Spring AI 1.1.5's `ChatClient` already exposes `.stream()` returning a `Flux`; we currently use only the blocking `.call()` path. There is no SSE/Flux/streaming code anywhere in the agent today.
2. **Real conversations** — list past conversations, resume one, rename it, delete it. Without a conversation entity, the client cannot render a conversation drawer, and compaction/memory can never be scoped tighter than "everything this user ever said".

Doing conversations now also unblocks the parallel changes: `add-tenant-isolation` needs a conversation table to hang a tenant column on, and `add-audit-and-gdpr-compliance` needs a deletable per-conversation history unit.

## What Changes

- **New SSE streaming endpoint** `POST /api/v1/ai/prompt/stream` (multipart/form-data, same fields as `/prompt` plus optional `conversationId`) emitting `text/event-stream` with a defined event schema: `delta` (token fragments), `sources` (RAG source attachments when `attachSources=true`), `done` (terminal event carrying metadata + conversationId), `error` (terminal failure event). Backed by `ChatClient.stream()` through the existing provider-resolution, context-assembly, prompt-cache, and history-persistence pipeline. The `sources` event carries the same `SourceFile` shape as the synchronous response, which under the presign-resolution amendment means the registry `documentId` and the relative `contentPath` (`/api/v1/documents/{id}/content`) rather than a presigned MinIO URL.
- **Existing synchronous endpoint unchanged** — `POST /api/v1/ai/prompt` keeps its exact request/response shape; it gains only the optional `conversationId` form field and a `conversationId` echo inside response metadata (additive).
- **New `conversations` table** (Liquibase): `id` (UUID), `tenant_id` (nullable placeholder for `add-tenant-isolation`), `user_id`, `title`, `created_at`, `updated_at`. `chat_history` gains an indexed `conversation_id` foreign key.
- **Chat memory re-keyed by conversation id** — Redis key becomes `chat:<conversationId>` where the id is the conversation UUID; Postgres reads/writes filter on `conversation_id`. Compaction and semantic-memory extraction keep working, now scoped per conversation (extraction remains user-scoped, as memories belong to the user).
- **Auto-create and auto-title** — a prompt without `conversationId` resolves to the user's most-recent conversation (created on the fly if none exists, preserving today's one-thread behavior for legacy callers); a brand-new conversation is titled from the first prompt text.
- **Conversation management REST API** under `/api/v1/conversations`: list (paginated, most-recent-first), create, get messages (paginated), rename, delete (removes the conversation row, its Postgres history rows, and its Redis key).
- **Data migration** — existing per-user history migrates into one conversation row per user; old `chat:<userId>` Redis keys are left to expire via the existing TTL (Postgres hydrate repopulates under the new key).
- **BREAKING (internal only)**: `PersistentChatMemory` callers must pass a conversation UUID instead of a raw user id. No public API contract breaks; all REST changes are additive.

## Capabilities

### New Capabilities

- `chat-streaming`: SSE token-streaming endpoint — event schema (`delta`/`sources`/`done`/`error`), pipeline parity with the synchronous path, and unchanged behavior of the existing `/prompt` endpoint.
- `conversation-management`: conversation entity, auto-create/auto-title lifecycle, per-conversation chat-history keying, and the `/api/v1/conversations` CRUD + pagination API including full history deletion.

### Modified Capabilities

- `chat-history-persistence`: the Redis TTL requirement is re-stated per conversation key — keys are `chat:<conversationId>` (conversation UUID) instead of `chat:<userId>`; TTL semantics themselves are unchanged.
- `chat-history-compaction`: the REST override-fields requirement (`compactionProvider`/`compactionModel`) now covers both `POST /api/v1/ai/prompt` and `POST /api/v1/ai/prompt/stream`; compaction scope is explicitly the conversation, not the user's lifetime history.

(`chat-history-persistence-toggle`, `prompt-caching`, and `rag-source-attachments` requirements are already stated in terms of `conversationId` or are orthogonal to conversation identity — no requirement-level change; verified against `openspec/specs/`.)

## Impact

- **New code (ascend-ai-agent)**: streaming controller method + SSE event DTOs (`controller/`, `dto/`), `ConversationController` + request/response DTOs, `Conversation` entity + `ConversationRepository` (`model/`, `repository/`), `ConversationService` (resolution, auto-title, delete cascade) in `service/`, streaming execution path beside `ChatExecutor` in `service/chat/`.
- **Changed code (ascend-ai-agent)**: `PromptController` (new `conversationId` field), `AscendChatService` / `ChatHistoryService` / `PersistentChatMemory` (conversation-id keying), `CustomMetadata` (additive `conversationId`), `ChatHistoryRepository` (conversation-keyed queries), `ChatHistoryCompactionService` (unchanged trigger logic, conversation-scoped ids flow through).
- **Database**: new Liquibase changelog `02-conversations.xml` under `apps/ascend-agent/src/main/resources/db/changelog/` — `conversations` table, `chat_history.conversation_id` column + backfill + FK + index.
- **Dependencies**: none new — Spring MVC supports `Flux<ServerSentEvent>` return types with Reactor already on the classpath via Spring AI.
- **Docs / API collection**: `apps/ascend-agent/AGENTS.md` API description, Bruno requests under `docs/api/request/AscendAI/ascend-agent/` for the stream endpoint and conversation CRUD.
- **Sibling changes**: identity stays `X-User-Id` until `add-auth-and-identity` lands (JWT-supplied userId slots into the same parameter); `tenant_id` column ships nullable and unused until `add-tenant-isolation`.
- **Depends on `add-document-management-api`** (build-order): the `sources` event carries the registry `documentId` and the `/api/v1/documents/{id}/content` path from the presign-resolution amendment, so the document registry and the content endpoint from that change must be in place before this change's `sources` event is implemented. The `delta`/`done`/`error` events and the conversation model have no such dependency.
- **Tests**: SSE integration test (delta + done event assertions), conversation CRUD + ownership tests, Liquibase migration test over pre-existing `chat_history` rows, regression test that the synchronous endpoint response is byte-compatible.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/api-design`
- `/jpa-patterns`
- `/database-migrations`
- `/springboot-tdd`
