# Design — add-chat-streaming-and-conversations

## Context

The chat surface is a single blocking multipart endpoint, `POST /api/v1/ai/prompt` in
`apps/ascend-ai-agent/src/main/java/com/lukk/ascend/ai/agent/controller/PromptController.java`. It resolves the userId from the
`X-User-Id` header (default `app.user.default-id`), delegates to `AscendChatService.prompt(...)`
(`service/chat/AscendChatService.java`), which assembles system messages (`ChatContextAssembler`), loads history
(`ChatHistoryService.loadHistory(userId)` → `PersistentChatMemory.get(userId, 100)`), executes the blocking
`ChatClient.call()` inside `ChatExecutor` (with prompt-cache decoration + one undecorated retry), saves the turn
(`ChatHistoryService.saveHistory` → `PersistentChatMemory.add` → async compaction), and fires semantic-memory
extraction. The response is a JSON `AiResponse{content, metadata, sources[]}` (`dto/AiResponse.java`,
`@JsonInclude(NON_NULL)`).

Chat memory identity: `conversationId == userId` everywhere. Redis key is `"chat:" + conversationId`
(`memory/PersistentChatMemory.java`), Postgres rows live in `chat_history(user_id, role, content, created_at)`
(`db/changelog/01-initial-schema.xml`). There is exactly one conversation per user with no lifecycle API.
`PersistentChatMemory.clear(...)` today deletes only the Redis key, never Postgres rows.

No streaming exists anywhere in the codebase — no `Flux`, no `SseEmitter`, no `text/event-stream` producer. Spring AI
1.1.5's `ChatClient` supports `.stream()` returning `Flux<ChatResponse>`; providers are resolved per request through
`service/provider/ChatModelResolver.java`, so the streaming path can reuse the exact same resolution.

Parallel sibling changes constrain this design:

- `add-auth-and-identity` will replace `X-User-Id` with a JWT-derived userId. This design assumes "an authenticated
  userId is available per request" and keeps the header as the interim carrier. No auth is specced here.
- `add-tenant-isolation` will add tenant scoping. The `conversations` table ships a nullable `tenant_id` column now so
  that change is a column-populate, not a table rebuild.
- The Flutter client (mobile + web) is a separate future change. This change delivers only the API foundation; no UI.

## Goals / Non-Goals

**Goals:**

- Token-level SSE streaming for chat with a stable, versionable event schema the Flutter client can bind to.
- First-class conversation entity: create, list, resume, rename, delete — with per-conversation chat history in both
  Redis and Postgres.
- Full behavioral parity between the streaming and synchronous paths: RAG, MCP tools, prompt caching, history
  persistence, compaction, semantic-memory extraction, `attachSources`.
- Zero contract break for existing callers of `POST /api/v1/ai/prompt`.
- Lossless migration of existing per-user history into the conversation model.

**Non-Goals:**

- Any UI (Flutter client is a separate change).
- Authentication/authorization (owned by `add-auth-and-identity`); tenant scoping (owned by `add-tenant-isolation`);
  usage metering, audit trails, document management (owned by their sibling changes).
- WebSocket transport, resumable/replayable streams, or multi-consumer fan-out of one generation.
- Conversation sharing, folders, tags, search, or archival states.
- Streaming for the ingestion or memory endpoints.

## Decisions

### D1 — Separate `POST /api/v1/ai/prompt/stream` endpoint, not Accept-header negotiation

A dedicated path is chosen over `Accept: text/event-stream` content negotiation on the existing endpoint.

- The existing endpoint consumes `multipart/form-data` and declares `produces = "application/json"` at the class level;
  overloading it with dual produces-types risks regressing the byte-compatibility guarantee that
  `rag-source-attachments` specs already pin down.
- A separate mapping keeps the synchronous method literally untouched (its tests keep passing unmodified) and gives the
  Bruno collection and OpenAPI two cleanly documented operations.
- Alternative considered: `Accept`-based negotiation on one path — rejected because Spring MVC's negotiation combined
  with multipart requests and the existing `@RequestMapping(produces=...)` makes error responses (415/406) ambiguous,
  and the two operations genuinely differ in response contract.

The stream endpoint accepts the same multipart fields as `/prompt` (`prompt`, `image`, `document`, `provider`, `model`,
`embeddingProvider`, `attachSources`, `compactionProvider`, `compactionModel`, `X-User-Id` header) plus the new
optional `conversationId` — which the synchronous endpoint also gains.

### D2 — SSE event schema: named events with JSON payloads

The stream is `text/event-stream` with SSE `event:` names and JSON `data:` payloads:

| Event     | Payload                                                                        | Cardinality                      |
| --------- | ------------------------------------------------------------------------------ | -------------------------------- |
| `delta`   | `{"content": "<token fragment>"}`                                             | 0..n, in generation order        |
| `sources` | `{"sources": [SourceFile...]}` (same `SourceFile` shape as the sync response — `documentId` + `contentPath`, per the presign-resolution amendment)  | 0..1, only when `attachSources`  |
| `done`    | `{"metadata": CustomMetadata, "conversationId": "<uuid>"}`                     | exactly 1 on success, terminal   |
| `error`   | `{"status": <int>, "code": "<machine code>", "message": "<human text>"}`      | exactly 1 on failure, terminal   |

- Named events (rather than one event type with a discriminator field) map directly onto `EventSource`/Flutter SSE
  client listeners and keep each payload minimal.
- `done` carries the metadata + conversationId so `attachSources` and token-usage reporting keep working; `sources` is
  emitted before `done` once RAG resolution and registry-id resolution complete (the client downloads each source
  through the authenticated `/api/v1/documents/{id}/content` endpoint, not a presigned MinIO URL).
- Errors after the stream has started cannot change the HTTP status (already 200, headers sent) — hence the terminal
  `error` event mirrors the `ApiError` shape (`status`, `code`, `message`). Pre-stream validation failures (unknown
  `compactionProvider`, vision-unsupported image, unknown `conversationId`) are rejected before any SSE bytes are
  written, as plain JSON `ApiError` with the proper 4xx status — same behavior as the sync endpoint.

### D3 — `Flux<ServerSentEvent<String>>` on Spring MVC, no WebFlux migration

The controller method returns `Flux<ServerSentEvent<String>>`. Spring MVC natively adapts reactive return types
(Reactor is already on the classpath transitively via Spring AI) and writes them as SSE without converting the app to
WebFlux.

- Alternative: `SseEmitter` + manual thread — rejected: `ChatClient.stream()` already yields a `Flux<ChatResponse>`, so
  bridging to `SseEmitter` adds a hand-rolled subscription/completion/error state machine for no benefit.
- Alternative: migrate the app to WebFlux — rejected as massively out of scope (blocking JPA/Redis/MinIO stack).
- The post-stream side effects (history save, compaction dispatch, semantic-memory extraction) run in the `Flux`
  completion hook on a bounded-elastic scheduler, accumulating the full assistant text from the deltas, so persisted
  history is identical to the sync path's.
- A new `StreamingChatExecutor` (or a `stream(...)` method beside `ChatExecutor.execute(...)` in `service/chat/`)
  reuses `ChatModelResolver`, the assembled system messages, and the prompt-cache strategy decoration. Cache-config
  failure fallback (retry once undecorated, per the `prompt-caching` spec) applies before first token; once tokens flow
  the stream is committed.

### D4 — Conversation entity and identity resolution

New table `conversations` (Liquibase changelog `02-conversations.xml`):

| Column       | Type          | Notes                                                        |
| ------------ | ------------- | ------------------------------------------------------------ |
| `id`         | UUID PK       | generated server-side                                        |
| `tenant_id`  | VARCHAR(255)  | nullable; unused until `add-tenant-isolation`                |
| `user_id`    | VARCHAR(255)  | not null, indexed                                            |
| `title`      | VARCHAR(255)  | not null                                                     |
| `created_at` | TIMESTAMP     | not null                                                     |
| `updated_at` | TIMESTAMP     | not null, bumped on every message append and rename          |

`chat_history` gains `conversation_id UUID` (FK → `conversations.id`, indexed). The existing `user_id` column stays —
it is denormalized but keeps audit/GDPR queries ("everything this user ever said") one-table simple for the sibling
compliance change.

Identity resolution on both prompt endpoints:

1. `conversationId` supplied → must exist AND belong to the requesting userId, else 404 (404 not 403, to avoid leaking
   existence of other users' conversations).
2. `conversationId` omitted → the user's most-recently-updated conversation is used; if the user has none, one is
   auto-created. This exactly preserves today's one-thread behavior for legacy callers (Bruno tests, e2e specs) with no
   request change.

Auto-title: a conversation created implicitly by a prompt is titled with the first prompt's text, trimmed and truncated
to 80 characters (word-boundary truncation with an ellipsis). Explicit creation (`POST /api/v1/conversations`) accepts
an optional title, defaulting to `"New conversation"`. No LLM call for titling — YAGNI; a smarter titler can replace
the truncation later without an API change.

`PersistentChatMemory` keeps its `ChatMemory` interface but its `conversationId` parameter now genuinely means the
conversation UUID; the Redis key format `"chat:" + conversationId` is unchanged. Rationale: the class is already
written against `conversationId` — only the callers (`ChatHistoryService`, `AscendChatService`) stop passing the raw
userId. Semantic-memory extraction stays keyed by userId (memories belong to the user, not a thread).

### D5 — Conversation management API shape

Per `/api-design` conventions — plural nouns, pagination via `page`/`size`, most-recent-first default sort:

| Operation                                        | Method + Path                                | Success                          |
| ------------------------------------------------ | -------------------------------------------- | -------------------------------- |
| List conversations (paginated, `updated_at` desc)| `GET /api/v1/conversations?page&size`        | 200, page envelope               |
| Create conversation                               | `POST /api/v1/conversations`                 | 201 + `Location` header          |
| List messages (paginated, chronological)          | `GET /api/v1/conversations/{id}/messages?page&size` | 200, page envelope        |
| Rename conversation                               | `PATCH /api/v1/conversations/{id}`           | 200, updated representation      |
| Delete conversation + all history                 | `DELETE /api/v1/conversations/{id}`          | 204                              |

- All operations scope on the request's userId; cross-user ids return 404.
- Page envelope: `{items: [...], page, size, totalItems, totalPages}` — a stable DTO, not Spring's raw `Page`
  serialization (which is version-unstable and marked unsupported by Spring Data).
- Delete removes, in order: Redis key `chat:<id>`, Postgres `chat_history` rows by `conversation_id`, the
  `conversations` row — Postgres deletions in one transaction; Redis best-effort first (a leftover Redis key without a
  Postgres backing row would resurrect ghost history on hydrate, so Redis goes first and the key also has a TTL safety
  net).
- `PUT` vs `PATCH` for rename: `PATCH` chosen — title is the only mutable field today; `PUT` would imply full-resource
  replacement semantics we do not offer.

### D6 — Migration of existing history

Changelog `02-conversations.xml` (SQL changesets where Liquibase XML lacks the construct):

1. Create `conversations`; add nullable `chat_history.conversation_id`.
2. Backfill: `INSERT INTO conversations (id, user_id, title, created_at, updated_at) SELECT gen_random_uuid(),
   user_id, 'Imported conversation', MIN(created_at), MAX(created_at) FROM chat_history GROUP BY user_id`, then
   `UPDATE chat_history SET conversation_id = c.id FROM conversations c WHERE chat_history.user_id = c.user_id`.
   (`gen_random_uuid()` is built into PostgreSQL 13+; no extension needed.)
3. Tighten: `NOT NULL` on `conversation_id`, FK, index — separate changesets so a failed backfill halts before
   constraints.

Redis needs no migration: old `chat:<userId>` keys simply stop being read and expire via the existing
`app.memory.chat-history.ttl`; the first `get` under the new key hydrates from Postgres, matching the already-specced
hydrate path. Rollback: Liquibase `rollback` blocks drop the column/table; pre-migration Postgres data is untouched by
the backfill (additive column only).

## Risks / Trade-offs

- [Client disconnects mid-stream leaving a half-turn] → the completion/cancellation hook persists whatever assistant
  text was generated before cancellation (matching how CLI chat tools behave); the turn is never half-written because
  persistence happens once, after stream termination, not per delta.
- [Provider stream never emits usage metadata (some OpenAI-compatible backends omit it on stream)] → `done.metadata`
  fields are nullable/omitted per `@JsonInclude(NON_NULL)`; the event itself is always sent.
- [Proxy/container buffering breaks SSE] → set `Cache-Control: no-store` and `X-Accel-Buffering: no` on the stream
  response; document the requirement in the Bruno request.
- [Legacy-caller fallback ("most recent conversation") surprises a client that expected a fresh thread] → documented
  explicitly in OpenAPI; the Flutter client will always pass `conversationId`; fallback exists purely for
  backward compatibility.
- [Backfill on a large `chat_history` table locks writes] → single-statement set-based backfill, index added after
  backfill; table is small in every current deployment (single-user), and the changesets are separated so an operator
  can pre-create the column in advance if scale demands.
- [Two execution paths (blocking + streaming) drift apart] → both paths share `ChatContextAssembler`, history
  load/save, and the cache-strategy resolver; the streaming executor contains only the transport difference. A
  parity integration test asserts both paths persist identical history for the same prompt.
- [`updated_at` bump on every message adds a write per turn] → trivially cheap next to the LLM call; required for
  most-recent-first listing.

## Migration Plan

1. Ship changelog `02-conversations.xml` (create + backfill + constraints) — runs automatically via Liquibase on boot.
2. Deploy the agent build where callers of `PersistentChatMemory` pass conversation UUIDs.
3. Old Redis keys age out via TTL; no manual step.
4. Rollback: revert the deployment; Liquibase rollback drops `conversations` and the `conversation_id` column —
   original `chat_history` rows and `user_id` keying remain intact, and the previous build reads them exactly as
   before.

## Open Questions

- None blocking. Whether `done.metadata` should also carry per-turn cost estimates is deferred to
  `add-usage-metering-and-quotas`.
