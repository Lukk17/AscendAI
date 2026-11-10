# Design - add-chat-streaming-and-conversations

## Context

The chat surface is a single blocking multipart endpoint, `POST /api/v1/ai/prompt` in
`apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/controller/PromptController.java`. It resolves the userId from the
`X-User-Id` header (default `app.user.default-id`), delegates to `AscendChatService.prompt(...)`
(`service/chat/AscendChatService.java`), which assembles system messages (`ChatContextAssembler`), loads history
(`ChatHistoryService.loadHistory(userId)` → `PersistentChatMemory.get(userId, 100)`), executes the blocking
`ChatClient.call()` inside `ChatExecutor` (with prompt-cache decoration + one undecorated retry), saves the turn
(`ChatHistoryService.saveHistory` → `PersistentChatMemory.add` → async compaction), and fires semantic-memory
extraction. The response is a JSON `AiResponse{content, metadata, sources[]}` (`dto/AiResponse.java`,
`@JsonInclude(NON_NULL)`).

Chat memory identity: `conversationId == userId` everywhere. Redis key is `"chat:" + conversationId`
(`memory/PersistentChatMemory.java`), Postgres rows live in `chat_history(user_id, role, content, created_at)`
(the initial schema, today `db/changelog/01-initial-schema.xml`, which `upgrade-spring-boot-4` moves to Flyway). There
is exactly one conversation per user with no lifecycle API.
`PersistentChatMemory.clear(...)` today deletes only the Redis key, never Postgres rows.

No streaming exists anywhere in the codebase - no `Flux`, no `SseEmitter`, no `text/event-stream` producer. Spring AI's
`ChatClient` supports `.stream()` returning `Flux<ChatResponse>`; providers are resolved per request through
`service/provider/ChatModelResolver.java`, so the streaming path can reuse the exact same resolution. This change lands
after `upgrade-spring-boot-4`, which moves the agent to Spring AI 2.0.1. There the stream still exists, but options are
builders, tools run through `ToolCallingAdvisor` and `streamToolCallResponses` is removed, so every streaming decision
below is checked again on 2.0.1 (task 5.2).

Parallel sibling changes constrain this design:

- `add-keycloak-login` (build group 3, position 3) lands before this change (build group 3, position 9 of the owner
  build order of 2026-10-04). Every endpoint here takes the caller from its resolved identity, never from `X-User-Id`,
  adds its own rows to its authorization matrix, and reads the tenant through its `TenantContext`.
- `add-tenant-isolation` (company, build group 5) adds tenant enforcement later. The `conversations` table carries
  `tenant_id VARCHAR(64) NOT NULL` now, written from `TenantContext.currentTenantId()` (`default` in the personal
  deployment), with no foreign key, so that change adds only the foreign key and its checks.
- The agent changes of build group 4 land after this change. Those that extend it, each in its own tasks (moved there
  from task group 9 of this change by the dependency fix of 2026-10-05): `add-agent-subagents` (run events, the
  disconnect rule, a conversation's runs), `add-agent-soul` (one prompt layout and context budget,
  `RequestProvenance`), `add-action-approvals` (`approval_required`, a conversation's pending approvals),
  `add-openclaw-plugin-host` (in process turn service, conversation binding), `add-scheduled-tasks`
  (`scheduled_job.origin_conversation_id`) and `add-self-improvement` (evidence and triggers at stream end). Each
  decision below names the part it leaves open for them.
- The Flutter client (mobile + web) is a separate future change. This change delivers only the API foundation; no UI.

## Goals / Non-Goals

**Goals:**

- Token-level SSE streaming for chat with a stable, versionable event schema the Flutter client can bind to.
- First-class conversation entity: create, list, resume, rename, delete - with per-conversation chat history in both
  Redis and Postgres.
- One chat executor for both endpoints, so the streaming and synchronous paths cannot drift: RAG, MCP tools, prompt
  caching, history persistence, compaction, semantic-memory extraction and `attachSources` exist once (owner answer
  89.1 of 2026-10-08, D3).
- Zero contract break for existing callers of `POST /api/v1/ai/prompt`, proven by tests that the blocking answer stays
  the same (D3).

**Non-Goals:**

- Any UI (Flutter client is a separate change).
- Authentication/authorization (owned by `add-keycloak-login`); tenant scoping (owned by `add-tenant-isolation`);
  usage metering, audit trails, document management (owned by their sibling changes).
- WebSocket transport, resumable/replayable chat streams, or multi-consumer fan-out of one generation. A run started by
  a turn outlives the stream, and a client follows it after the stream ended through `GET /api/v1/runs/{id}/events` of
  `add-agent-subagents`, which is resubscribed with `Last-Event-ID`. That stream belongs to that change.
- Conversation sharing, folders, tags, search, or archival states.
- Streaming for the ingestion or memory endpoints.

## Decisions

### D1 - Separate `POST /api/v1/ai/prompt/stream` endpoint, not Accept-header negotiation

A dedicated path is chosen over `Accept: text/event-stream` content negotiation on the existing endpoint.

- The existing endpoint consumes `multipart/form-data` and declares `produces = "application/json"` at the class level;
  overloading it with dual produces-types risks regressing the byte-compatibility guarantee that
  `rag-source-attachments` specs already pin down.
- A separate mapping keeps the synchronous contract untouched (its controller tests keep passing unmodified, and the
  tests of D3 prove the blocking answer stays the same) and gives the Bruno collection and OpenAPI two cleanly
  documented operations.
- Alternative considered: `Accept`-based negotiation on one path - rejected because Spring MVC's negotiation combined
  with multipart requests and the existing `@RequestMapping(produces=...)` makes error responses (415/406) ambiguous,
  and the two operations genuinely differ in response contract.

The stream endpoint accepts the same multipart fields as `/prompt` (`prompt`, `image`, `document`, `provider`, `model`,
`embeddingProvider`, `attachSources`, `compactionProvider`, `compactionModel`) plus the new optional
`conversationId` - which the synchronous endpoint also gains. The caller is the resolved identity of
`add-keycloak-login`, as on the synchronous endpoint.

### D2 - SSE event schema: named events with JSON payloads

The stream is `text/event-stream` with SSE `event:` names and JSON `data:` payloads:

| Event     | Payload                                                                        | Cardinality                      |
| --------- | ------------------------------------------------------------------------------ | -------------------------------- |
| `delta`   | `{"content": "<token fragment>"}`                                             | 0..n, in generation order        |
| `sources` | `{"sources": [SourceFile...]}` (same `SourceFile` shape as the sync response: `downloadUrl`, `expiresAt`, `documentId`, `contentPath`, per add-document-management-api D8)  | 0..1, only when `attachSources`  |
| `done`    | `{"metadata": CustomMetadata, "conversationId": "<uuid>"}`                     | exactly 1 on success, terminal   |
| `error`   | RFC 7807 problem detail: `{"type": "https://ascend.ai/errors/<code with dashes>", "title": "<reason phrase>", "status": <int>, "detail": "<human text>", "instance": "<request path>", "code": "<snake case code>", "traceId": "<32 hex trace id>"}` | exactly 1 on failure, terminal   |

- Named events (rather than one event type with a discriminator field) map directly onto `EventSource`/Flutter SSE
  client listeners and keep each payload minimal.
- `done` carries the metadata + conversationId so `attachSources` and token-usage reporting keep working; `sources` is
  emitted before `done` once RAG resolution and registry-id resolution complete (the client may open the presigned `downloadUrl`
  or fetch the authenticated `/api/v1/documents/{id}/content` path, both are always present).
  add-passage-level-citations later adds a `citations` event, emitted before `sources`; that change owns it.
- The event set is closed: this change defines `delta`, `sources`, `done` and `error`. A later change that needs an
  event adds its name, payload and OpenAPI entry to this closed set in its own tasks when it lands (owner answer 93 of
  2026-10-08, review item S3-11): `add-agent-subagents` adds `run_started` and `subagent_status` (the run view, when
  the turn starts a run and when that run changes, read from the shared run store so a run on another agent instance
  reaches the stream), `add-action-approvals` adds `approval_required` (the approval view, when a call in the turn
  needs approval), and add-passage-level-citations adds `citations`. Each is sent before the terminal `done` or
  `error`. This change reserves no name for them.
- `add-agent-soul` (build group 4) lands later and adds `fileChanges` (every change or proposal of the request) and
  `contextTrimmed` (the trim report of its context budget) to `done.metadata`, both in `CustomMetadata`.
- `add-usage-metering-and-quotas` (company, build group 5) adds `estimatedCostUsd` to `done.metadata` later, the
  estimated cost in US dollars of the turn's own model calls, unless `app.usage.cost-estimate.enabled` is `false` or a
  model of the turn has no price (owner decision 65.4 of 2026-10-04, its D15). This change does not wait for it.
- Error body (owner decision of 2026-10-02): every REST error of the agent is the RFC 7807 problem detail that
  `upgrade-spring-boot-4` defines (its D19 and its `agent-error-responses` spec) and builds in one factory method from
  its `ApiErrorCode` enum: `type` (`https://ascend.ai/errors/` followed by the code with every `_` replaced by `-`),
  `title` (the HTTP reason phrase), `status`, `detail`, `instance` (the request path) and a top-level snake case
  `code`, plus the top-level `traceId` field, the trace id of the request (`upgrade-spring-boot-4` D19 point 3,
  owner decision 51.3 of 2026-10-03, `add-observability` D12), sent as `application/problem+json`, with no
  `timestamp`. This change adds no error body of its own.
- Errors after the stream has started cannot change the HTTP status (already 200, headers sent) - hence the terminal
  `error` event carries the same problem detail JSON the synchronous endpoint would have answered for that failure,
  built by the same factory method, with `status` and `code` of that failure (for example 502 `provider_error`)
  and `traceId`, the trace id of the stream request. A mid-stream failure can surface on a reactive thread where
  no span is current, so the stream builds the `error` payload inside the observation of its request, and the
  `traceId` of the event is the trace of that request, the same one the synchronous answer would carry. It is
  never left out or set to an invented value on this path (`upgrade-spring-boot-4` D19 point 3).
  Pre-stream validation failures (unknown `compactionProvider`, vision-unsupported image, unknown `conversationId`,
  and, added by `add-agent-soul` when it lands, a prompt whose protected part is over the context budget, 413
  `context_too_large`) are rejected before any SSE bytes are written, as an `application/problem+json` response with the proper 4xx
  status - same behavior as the sync endpoint.
- New codes this change adds to `ApiErrorCode`: `conversation_not_found` (404, an unknown or foreign
  `conversationId` on a prompt endpoint or a conversation operation) and `invalid_title` (400, a blank title or one
  over 255 characters on create or rename). Every other code it answers already exists in D19.

### D3 - `Flux<ServerSentEvent<String>>` on Spring MVC, no WebFlux migration

The controller method returns `Flux<ServerSentEvent<String>>`. Spring MVC natively adapts reactive return types
(Reactor is already on the classpath transitively via Spring AI) and writes them as SSE without converting the app to
WebFlux.

- Alternative: `SseEmitter` + manual thread - rejected: `ChatClient.stream()` already yields a `Flux<ChatResponse>`, so
  bridging to `SseEmitter` adds a hand-rolled subscription/completion/error state machine for no benefit.
- Alternative: migrate the app to WebFlux - rejected as massively out of scope (blocking Spring Data JDBC, Redis and object storage stack).
- The post-stream side effects (history save, compaction dispatch, semantic-memory extraction) run in the `Flux`
  completion hook on a bounded-elastic scheduler, accumulating the full assistant text from the deltas. Both endpoints
  run them through this one hook.
- One chat executor (owner answer 89.1 of 2026-10-08): `StreamingChatExecutor` in `service/chat/` is the only chat
  executor of the agent, and the class `ChatExecutor` is removed. It reuses `ChatModelResolver`, the assembled system
  messages, and the prompt-cache strategy decoration. Cache-config failure fallback (retry once undecorated, per the
  `prompt-caching` spec) applies before first token. Once tokens flow the stream is committed. `POST /api/v1/ai/prompt`
  calls the same executor and collects its `Flux` into one `AiResponse`: `content` is the concatenation of the
  deltas, `metadata` is built from the last `ChatResponse` of the stream the way the blocking call built it from its
  one response (model, token usage, tools used, cache information), and `sources` are the same `buildSourceRefs`
  entries. History save, compaction, memory extraction, cache fallback and tool tracking therefore exist once. The
  executor asks every provider for token usage on the stream through each provider's own stream option of the 2.0
  builders, so the collected `metadata` keeps the usage fields the blocking call had.
- Proof that the blocking answer stays the same: before the switch, characterization tests record the
  `POST /api/v1/ai/prompt` answer of today's blocking path for a fixed set of turns on stubbed models of every
  configured provider (a plain answer, a turn with one MCP tool call, `attachSources=true`, a compaction override, the
  undecorated cache retry, a provider error and a vision refusal), and after the switch the same tests must give the
  same status and the same JSON body, apart from the additive `conversationId` and the generated ids and times, which
  the tests normalise. A field that cannot stay the same (for example a provider that sends no usage on a stream) stops
  the task and is put to the owner before anything else changes. The parity integration test of the earlier plan is
  dropped, because one executor cannot drift from itself.
- Spring AI 2.0.1 (`upgrade-spring-boot-4`): the executor builds its options with the builders of 2.0, runs tools
  through `ToolCallingAdvisor` on the stream as on the blocking call, and does not use `streamToolCallResponses`,
  which 2.0 removed.
- One prompt layout (`add-agent-soul` D4, D6 and D15, build group 4, which lands later and does this in its own
  tasks): the one executor then builds its message list through `PromptLayout` and `ContextBudget`, so the summary of
  a conversation sits in the dynamic block for both endpoints. It computes the request's `RequestProvenance` before
  the first model call and puts its holder into the tool context under `request_provenance`. The compaction delta spec of this change keeps its requirement.
- Self-improvement (`add-self-improvement` D3, build group 4, which lands later and does this in its own tasks): the
  one executor then captures the evidence and records the triggers at stream end, for both endpoints, and offers
  `request_self_review`. The conversation id becomes the review's conversation key.
- The turn service is callable in process with a prepared identity and attachments, so the relay of
  `add-openclaw-plugin-host` reads the `delta` and terminal events of a turn without a new endpoint.
- The stream answer is an asynchronous request of Spring MVC, so Spring MVC's async request timeout ends a stream
  that runs longer than it. The agent sets it explicitly as the setting `spring.mvc.async.request-timeout`
  (environment variable `SPRING_MVC_ASYNC_REQUESTTIMEOUT`, D7), so no default of the server decides how long a turn
  may stream. Its default is `300s` (owner answer 103.5 of 2026-10-09). Task 5.8 reads the effective default of the
  pinned Spring Boot and its embedded server at implementation time and records it in the ADR of task 8.3.

### D4 - Conversation entity and identity resolution

New table `conversations` (Flyway migration `V<n>__conversations.sql` under `db/migration/`, where `<n>` is the next free version at implementation time):

| Column       | Type          | Notes                                                        |
| ------------ | ------------- | ------------------------------------------------------------ |
| `id`         | UUID PK       | generated server-side                                        |
| `tenant_id`  | VARCHAR(64)   | not null, from `TenantContext.currentTenantId()`, no foreign key |
| `user_id`    | VARCHAR(255)  | not null, indexed                                            |
| `title`      | VARCHAR(255)  | not null                                                     |
| `created_at` | TIMESTAMP     | not null                                                     |
| `updated_at` | TIMESTAMP     | not null, bumped on every message append and rename          |

`chat_history` gains `conversation_id UUID` (FK → `conversations.id`, indexed). The existing `user_id` column stays -
it is denormalized but keeps audit/GDPR queries ("everything this user ever said") one-table simple for the sibling
compliance change.

Identity resolution on both prompt endpoints:

1. `conversationId` supplied → must exist AND belong to the requesting userId, else 404 (404 not 403, to avoid leaking
   existence of other users' conversations).
2. `conversationId` omitted → the user's most-recently-updated conversation is used; if the user has none, one is
   auto-created. This exactly preserves today's one-thread behavior for legacy callers (Bruno tests, e2e specs) with no
   request change. Several agent instances run at once (owner answer 87 of 2026-10-08), so the read and the create
   run in one transaction that first takes a transaction advisory lock keyed by the tenant and the user
   (`pg_advisory_xact_lock`), and two prompts without a `conversationId` that reach two instances at the same moment
   never create two conversations. The fallback stays (review item S3-10 not applied, rule R3 of owner answers 92 and
   93): it is the one-thread behaviour that old callers see today.

Auto-title: a conversation created implicitly by a prompt is titled with the first prompt's text, trimmed and truncated
to 80 characters (word-boundary truncation with an ellipsis), the setting `app.conversations.auto-title-max-length`
(D7). Explicit creation (`POST /api/v1/conversations`) accepts
an optional title, defaulting to `"New conversation"`. No LLM call for titling - YAGNI; a smarter titler can replace
the truncation later without an API change.

`PersistentChatMemory` keeps its `ChatMemory` interface but its `conversationId` parameter now genuinely means the
conversation UUID; the Redis key format `"chat:" + conversationId` is unchanged. Rationale: the class is already
written against `conversationId` - only the callers (`ChatHistoryService`, `AscendChatService`) stop passing the raw
userId. Semantic-memory extraction stays keyed by userId (memories belong to the user, not a thread).

### D5 - Conversation management API shape

Per `/api-design` conventions - plural nouns, pagination via `page`/`size` (default size 20, largest 100, the settings
`app.conversations.page.default-size` and `app.conversations.page.max-size` of D7, for the list and the messages
alike), most-recent-first default sort:

| Operation                                        | Method + Path                                | Success                          |
| ------------------------------------------------ | -------------------------------------------- | -------------------------------- |
| List conversations (paginated, `updated_at` desc)| `GET /api/v1/conversations?page&size`        | 200, page envelope               |
| Create conversation                               | `POST /api/v1/conversations`                 | 201 + `Location` header          |
| List messages (paginated, chronological)          | `GET /api/v1/conversations/{id}/messages?page&size` | 200, page envelope        |
| Rename conversation                               | `PATCH /api/v1/conversations/{id}`           | 200, updated representation      |
| Delete conversation + all history                 | `DELETE /api/v1/conversations/{id}`          | 204                              |

- All operations scope on the request's userId; cross-user ids return 404.
- Conversations started from a chat platform by `add-openclaw-plugin-host` are listed and read like any other. No
  field is added to the list or messages response.
- Page envelope: `{items: [...], page, size, totalItems, totalPages}` - a stable DTO, not Spring's raw `Page`
  serialization (which is version-unstable and marked unsupported by Spring Data).
- Delete removes, in order: Redis key `chat:<id>`, Postgres `chat_history` rows by `conversation_id`, the
  `conversations` row - Postgres deletions in one transaction; Redis best-effort first (a leftover Redis key without a
  Postgres backing row would resurrect ghost history on hydrate, so Redis goes first and the key also has a TTL safety
  net).
- Delete and the agent changes of build group 4: each of them lands later and adds its step in its own tasks. Before
  the Redis key:
  1. cancel the conversation's pending approvals with decided by `system` (`add-action-approvals`), before its runs
     are cancelled,
  2. cancel the conversation's runs that are not final (`add-agent-subagents`),
  3. close the conversation's open sandbox chat workspace with reason `CONVERSATION_GONE` (`add-agent-sandbox`).
  Then, in the same Postgres transaction as the history rows: delete its `subagent_run` rows (`add-agent-subagents`,
  which owns this rule in its own tasks, dependency fix of 2026-10-05), delete its `approval_request` rows
  (`add-action-approvals`) and its `sandbox_workspace` rows (`add-agent-sandbox`), whose `conversation_id` columns
  carry the same foreign key rule as `subagent_run` (owner answer 76.6 of 2026-10-08), set
  `scheduled_job.origin_conversation_id` to null for it (`add-scheduled-tasks`: jobs are owned by their user, not by a
  conversation, so they keep running), and remove its chat platform binding, which the `ON DELETE CASCADE` of the
  foreign key from `channel_conversation` to `conversations(id)` of `add-openclaw-plugin-host` does with no code here.
  After the commit, `add-agent-sandbox` deletes the output archives of the deleted `sandbox_workspace` rows.
- `subagent_run.conversation_id` (`add-agent-subagents` D13): owner answer 27 (no old data to keep) closes the open
  question on it: the column is a `UUID`, stays nullable (null only for the run
  kinds D13 of `add-agent-subagents` allows), and gets the foreign key `fk_subagent_run_conversation` to
  `conversations.id` with no delete action, because conversation delete removes the rows itself in its transaction.
  No old row is kept or converted. `add-agent-subagents` lands after this change, so it creates the column as `UUID`
  with the key from its first migration, and this change has no migration for it (dependency fix of 2026-10-05).
- `PUT` vs `PATCH` for rename: `PATCH` chosen - title is the only mutable field today; `PUT` would imply full-resource
  replacement semantics we do not offer.

### D6 - One migration, no existing data kept

The owner decided on 2026-10-02 (confirmed by owner answer 73.1 of 2026-10-06) that there is no existing data to
keep. This holds only until the first real customer deployment. So the schema change is one Flyway versioned SQL
migration, `V<n>__conversations.sql` under `db/migration/`, where `<n>` is the next free version at implementation
time. In order:

1. Empty `chat_history`. Rows written before this change belong to no conversation, and nothing is copied.
2. Create `conversations`.
3. Add `chat_history.conversation_id` as `UUID NOT NULL` with the foreign key to `conversations.id` and the index
   `idx_chat_history_conversation_id`.

Flyway runs the migration in one Postgres transaction, so a failure leaves the schema unchanged. Old `chat:<userId>`
Redis keys are never read again and expire through the existing `app.memory.chat-history.ttl`. There is no backfill,
no second migration and no rollback script.

### D7 - Settings of this change (owner rule 98 of 2026-10-08)

Every value of this change that has a default is a setting: `application.yaml` writes `key: ${ENV:default}`, the
`@ConfigurationProperties` record `ConversationProperties` (prefix `app.conversations`) carries the same default in
code, the `ascend-agent` service of `compose.yaml` writes `- ENV=${ENV:-default}`, and
`apps/ascend-agent/docs/CONFIGURATION.md` gets one row per setting whose description ends with "Added by
`add-chat-streaming-and-conversations`.". ENV is Spring Boot's canonical environment form of the key.

| Key | Environment variable | Default | What it does |
| --- | --- | --- | --- |
| `app.conversations.page.default-size` | `APP_CONVERSATIONS_PAGE_DEFAULTSIZE` | `20` | Page size of the conversation list and the messages list when no `size` is sent |
| `app.conversations.page.max-size` | `APP_CONVERSATIONS_PAGE_MAXSIZE` | `100` | Largest `size` of both lists |
| `app.conversations.auto-title-max-length` | `APP_CONVERSATIONS_AUTOTITLEMAXLENGTH` | `80` | Largest length of a title taken from the first prompt |
| `spring.mvc.async.request-timeout` | `SPRING_MVC_ASYNC_REQUESTTIMEOUT` | `300s` (owner answer 103.5 of 2026-10-09, task 5.8) | Longest time one stream answer may run |

The application refuses to start when a size or length is zero or negative, when the default page size is greater
than the largest, and when the auto-title length is greater than 255, the width of `conversations.title`. Kept as
constants, because they are not operational: the title width 255 (a column width that only a migration changes, and
the validation limit of create and rename that follows it), the default title `New conversation` (a text of the API,
not a tuning value), the Redis key format `chat:<id>`, the event names, the header values `Cache-Control: no-store`
and `X-Accel-Buffering: no`, the gateway directive `flush_interval -1` (the "flush at once" mode SSE needs, not a
duration), the advisory lock key form, and the error codes. The existing `app.memory.chat-history.ttl` is not added
by this change, so its row comes from the inventory of `fix-linux-docker-host-access`.

## Risks / Trade-offs

- [Client disconnects mid-stream leaving a half-turn] → the completion/cancellation hook persists whatever assistant
  text was generated before cancellation (matching how CLI chat tools behave); the turn is never half-written because
  persistence happens once, after stream termination, not per delta. Ending the turn cancels the runs the turn started
  in the foreground, recorded as `cancelledBy = parent`, and leaves its background runs working
  (`add-agent-subagents` D17).
- [Provider stream never emits usage metadata (some OpenAI-compatible backends omit it on stream)] → `done.metadata`
  fields are nullable/omitted per `@JsonInclude(NON_NULL)`; the event itself is always sent.
- [Proxy/container buffering breaks SSE] → the gateway of `harden-cloud-deployment` proxies `POST /api/v1/ai/prompt/stream`
  with `flush_interval -1` and without a read timeout that could cut a stream (task 5.7, moved here from that change),
  and the agent sets `Cache-Control: no-store` and `X-Accel-Buffering: no` on the stream response; document the requirement in the Bruno request.
- [Legacy-caller fallback ("most recent conversation") surprises a client that expected a fresh thread] → documented
  explicitly in OpenAPI; the Flutter client will always pass `conversationId`; fallback exists purely for
  backward compatibility.
- [The blocking answer changes when it is collected from a stream] → the characterization tests of D3 record
  today's blocking answers first and must pass unchanged after the switch, and a field that cannot stay the same is
  put to the owner before the switch lands (owner answer 89.1 of 2026-10-08).
- [Several agent instances] → the SSE stream of a turn is written by the instance that runs the turn to the client
  connection it holds, and every state the stream reads (conversation rows, chat history in Postgres and Redis, and the
  run and approval events that later changes add from their shared stores) is shared, so a client sees the same
  stream whichever instance it reached. A client disconnect cancels the turn on the instance that holds the
  connection, and the cancel of the runs the turn started is written to their shared rows by `add-agent-subagents`
  (owner answer 87 of 2026-10-08).
- [`updated_at` bump on every message adds a write per turn] → trivially cheap next to the LLM call; required for
  most-recent-first listing.

## Migration Plan

1. Ship `V<n>__conversations.sql` (D6), run automatically via Flyway on boot. It deletes the existing chat history.
2. Deploy the agent build where callers of `PersistentChatMemory` pass conversation UUIDs.
3. Old Redis keys age out via TTL. No manual step.
4. No rollback that restores data. Flyway runs forward only, and the deleted history is not kept (owner decision of
   2026-10-02, confirmed by owner answer 73.1 of 2026-10-06, valid only until the first real customer
   deployment).

## Owner decisions of 2026-10-06

Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory
is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores.
This change keeps its empty `chat_history` and its unread old `chat:<userId>` Redis keys (D6), and it needs none of
today's data.

## Owner decisions of 2026-10-07

Answer 75.1: the owner approved the fixes of the review of 2026-10-07. In this change they fix item 17 (the stream
validation spec of task 10.3 and the stream spec of task 10.4 judge only structure, so they run on the scripted model
of `close-agent-test-gaps` in its harness phase, with `E2E-SCRIPT-ERROR` for the error row) and item 56 (the closed
Open Question on `estimatedCostUsd` says the field comes with `add-usage-metering-and-quotas` and this change does not
wait for it).

## Owner decisions of 2026-10-08

Answer 76.3 (partly): the Bruno request names `stream-provider-error` and `prompt-provider-error` of the stream
validation spec of task 10.3 stay as they are. The answer keeps only the names, not their folders.

Answer 76.6: `approval_request.conversation_id` of `add-action-approvals` and `sandbox_workspace.conversation_id` of
`add-agent-sandbox` get the same foreign key to `conversations(id)` and the same delete rule as
`subagent_run.conversation_id`. Each of the two changes extends the conversation delete of D5 in its own tasks, and
the delete steps of D5 list both.

Answer 76.10: spec 10.4 checks again that AscendMemory holds a point after a streamed turn, on the scripted model.
The scripted model answers the memory extractor's request, recognised by the start of its system prompt as in
`close-agent-test-gaps` D5, with a fixed fact, and the spec checks that AscendMemory holds it (task 10.4, the
`chat-streaming` requirement on end-to-end tests). The spec is updated in place, and the gap note under task group 10
no longer lists it.

Answer 76.2: the scripted model of the shared harness of `close-agent-test-gaps` is Mockoon. Spec 10.4 adds its rules
to the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json`, with its reply
files in `responses/chat-streaming/` and its vector file in `embeddings/chat-streaming/` under
`apps/ascend-agent/e2e/fixtures/scripted-model/` (task 10.4).

Answer 77.1: no test-only provider in AscendMemory. In the deterministic phase only, the test stack sets AscendMemory's
existing `OPENAI_BASE_URL` to the scripted model, and the provider `scripted` sends the embedding provider name
`openai`, so the fact of spec 10.4 is embedded through the scripted model into `ascend_memory_1536` with a 1536 long
vector. The AI-run phase uses the real `OPENAI_BASE_URL`, and the spec wipes its user's memories in its Post-run
cleanup (task 10.4). This closes the open question that answer 76.10 raised. (Superseded for AscendMemory by owner
answer 91.1 of 2026-10-08: AscendMemory is faked under `/ascend-memory/` of the scripted model, its `OPENAI_BASE_URL`
stays fixed, and spec 10.4 checks the insert call in the request log.)

Answer 78.1: the provider `scripted` uses `default-embedding: openai`, and the deterministic phase overlay points the
agent's own embedding entry `openai` at Mockoon. There is no separate scripted embedding entry, and every vector file
of this change is 1536 long (`ascendai-1536` and `ascend_memory_1536`).

Answer 78.2 (superseded for AscendMemory by owner answer 91.1 of 2026-10-08, and for the agent by owner answer 98.1
of 2026-10-08: no `e2e` profile exists, the overlay is copied into the running agent, which is restarted, the end
step recreates the agent from the image, and AscendMemory is never restarted, `close-agent-test-gaps` D7): the deterministic phase has two
restarts of AscendMemory and the agent, each followed by a check (`close-agent-test-gaps` D7). The start restart sets the scripted model's address as AscendMemory's `OPENAI_BASE_URL`,
a non-blank `OPENAI_API_KEY` and the agent's `e2e` profile, and the end restart, which runs even when a spec fails,
brings back the real address and settings. The deterministic specs of tasks 10.3 and 10.4 run between them, and the
AI-run spec of task 10.7 starts only after the end check has passed.

Answer 78.4: the subfolder name `chat-streaming` of the scripted model's reply files and vector files stays.

Approved fix of 2026-10-08 (superseded by owner answer 91.1 of 2026-10-08: no deterministic spec wipes memories):
every deterministic spec of this change that runs a scripted chat turn wipes in AscendMemory the memories of its
users in its Reset state and Post-run cleanup (`POST /api/v1/memory/wipe` with the
provider `openai` and the service token), because the memory extraction of a scripted turn embeds through the scripted
model into `ascend_memory_1536` (task 10.3, task 10.4 already did).

Answer 79.1 and 79.2 (the AscendMemory part and the dummy key are superseded by owner answer 91.1 of 2026-10-08,
the container names stay): the start restart of `close-agent-test-gaps` D7 sets AscendMemory's `OPENAI_BASE_URL` to
`http://e2e-scripted-model:3000/v1` and the dummy `OPENAI_API_KEY` `e2e-scripted-not-a-real-key` in the shell of that
one command, and the end check confirms the key is no longer this value. The harness containers on the stack's
network are `e2e-scripted-model` (the scripted model, at `http://e2e-scripted-model:3000`) and `e2e-fake-mcp` (the fake
MCP server). Spec 10.4 embeds its fact through `e2e-scripted-model`, and the AI-run spec of task
10.7 starts only after the end check.

Answer 85.1: every key and secret lives in the repository `.env` file, never in the shell. No spec of this change
exports a secret (tasks 10.3 and 10.4). (Since owner answer 98.1 of 2026-10-08 the deterministic phase sets nothing in
the shell at all: it copies the overlay into the running agent, `close-agent-test-gaps` D7.)

Answer 88 (rule R2): the company additions to this change stay as planned: `estimatedCostUsd` of `add-usage-metering-and-quotas` in `done.metadata` and the tenant checks of `add-tenant-isolation` on the `conversations` table.

Answer 87 (rule R1): several agent instances run at once. The SSE stream is written by the instance that runs the turn
and reads only shared state, the omitted-id fallback creates at most one conversation per user under a Postgres
advisory lock, and the run and approval events that later changes add come from their shared stores (D2, D4, Risks).
The chat history cache in Redis is shared already, and this change adds no in-process cache.

Answer 89.1: one chat executor. `StreamingChatExecutor` is the only executor, `POST /api/v1/ai/prompt` collects its
`Flux` into one `AiResponse`, `ChatExecutor` is removed, characterization tests prove the blocking answer stays the
same, and the parity test of task 7.5 is dropped (Goals, D1, D3, tasks 5.2, 7.5 and 7.7). Every later change that
names `ChatExecutor` reads it as this one executor (sent as a broadcast in the round 93 inbox).

Answer 91.1: the deterministic phase of `close-agent-test-gaps` D7 recreates only the agent, AscendMemory is faked in
the Mockoon container `e2e-scripted-model` under `/ascend-memory/`, AscendMemory's `OPENAI_BASE_URL` stays fixed, there
is no dummy key, and no deterministic spec wipes memories. Spec 10.4 checks that the scripted model's request log holds
one `POST /ascend-memory/api/v1/memory/insert` whose body carries the spec user's id and the fixed fact, in place of a
stored memory point, and specs 10.3 and 10.4 wipe no memories. The agent's own scripted embeddings still go to
`ascendai-1536`, so the vector files stay 1536 long. The real mem0 path is proved by the AI-run specs.

Answer 91.3: no spec of this change only re-tests a lower test. The conversation spec (task 10.1), the stream
validation spec (task 10.3) and the stream spec (task 10.4) are the one deterministic API spec each of their
capabilities keeps, and the gateway streaming spec (task 10.7) runs with a real model.

Answer 93: review item S3-11, the event names `run_started`, `subagent_status` and `approval_required` are no longer
reserved here, and `add-agent-subagents` and `add-action-approvals` add them with their own tasks (D2). Review item
S3-10 (a missing `conversationId` always creating a new conversation) is not applied, because it would change what old
callers see today (rule R3).

Answer 94.5: the new change `scale-ocr-and-audio-across-containers` takes build group 3, position 5, directly after `harden-cloud-deployment`, so this change moves from position 8 to position 9 (`openspec/BUILD_ORDER.md`), and the positions of the other moved changes it names were moved by one too. Its dependencies and its tasks do not change. It stays the last change of the base group.

Answer 98: every value of this change with a default is a setting with its environment variable, the same default in
code, a `${VAR:-default}` line on the `ascend-agent` service of `compose.yaml` and a row in
`apps/ascend-agent/docs/CONFIGURATION.md` ending with "Added by `add-chat-streaming-and-conversations`." (D7, tasks 2.4,
5.8, 6.2 and 8.5). Made external: `APP_CONVERSATIONS_PAGE_DEFAULTSIZE` (`20`), `APP_CONVERSATIONS_PAGE_MAXSIZE`
(`100`), `APP_CONVERSATIONS_AUTOTITLEMAXLENGTH` (`80`) and `SPRING_MVC_ASYNC_REQUESTTIMEOUT` (value not decided, task
5.8). Kept as constants, because they are not operational: the title width 255, the default title, the Redis key
format, the event names, the stream header values, the gateway `flush_interval -1` mode, the advisory lock key form
and the error codes (D7). This change plans no SSE heartbeat and no other stream timeout.

Answer 98.1: no test line in `compose.yaml` and no `e2e` profile. The deterministic phase of specs 10.3 and 10.4 copies
the overlay into the running agent and restarts it, and its end step recreates the agent from the image, as
`close-agent-test-gaps` D7 writes out. The records of answers 78.2 and 85.1 now say so.

## Owner decisions of 2026-10-09

Answer 103.5: the async request timeout of the stream answer, the setting `spring.mvc.async.request-timeout` with
the environment variable `SPRING_MVC_ASYNC_REQUESTTIMEOUT`, has the default `300s`, the same value in
`application.yaml` and in the `${SPRING_MVC_ASYNC_REQUESTTIMEOUT:-300s}` line on the `ascend-agent` service of
`compose.yaml`, with its row in `apps/ascend-agent/docs/CONFIGURATION.md` (owner rule 98 of 2026-10-08, D3, D7, tasks
5.8 and 8.5). The value is no longer put to the owner at implementation. The Answer 98 record above, which says
"value not decided", is superseded on this point.

## Open Questions

- Closed (owner answer 91.1 of 2026-10-08, which replaces answer 77.1): in the deterministic phase AscendMemory is faked
  in the one Mockoon container `e2e-scripted-model` under `/ascend-memory/` and is never restarted, so spec 10.4 checks
  the insert call in the request log of that fake (`close-agent-test-gaps` D7).

- Closed (owner decision 65.4 of 2026-10-04): `estimatedCostUsd`, the estimated cost of the turn, is not part of
  this change. `add-usage-metering-and-quotas` (company, build group 5) adds it to `done.metadata` later in its own
  tasks (its D15), configurable through its `app.usage.cost-estimate.enabled` and on by default, priced from
  `infra/pricing/pricing.yaml` through the cost meter of `add-agent-subagents`. This change does not wait for either
  change, and its `done.metadata` carries no cost field until then.

Closed: the foreign key from `subagent_run.conversation_id` to `conversations.id`, asked by the edit of
`add-agent-subagents`. Owner answer 27: no old data to keep, so the column is a `UUID` with the key, created by
`add-agent-subagents` from its first migration, because it lands after this change (D5).
