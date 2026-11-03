# chat-streaming Delta Specification

## ADDED Requirements

### Requirement: SSE streaming prompt endpoint

The agent SHALL expose `POST /api/v1/ai/prompt/stream` consuming `multipart/form-data` and producing
`text/event-stream`. The endpoint SHALL accept the same form fields as `POST /api/v1/ai/prompt` - `prompt` (required),
`image`, `document`, `provider`, `model`, `embeddingProvider`, `attachSources`, `compactionProvider`,
`compactionModel` - plus the optional `conversationId` field, and SHALL take the caller from the resolved identity of
`add-keycloak-login`, the same one the synchronous endpoint uses, never from an `X-User-Id` header. The response SHALL be a Server-Sent Events stream whose events follow the schema defined in the
"SSE event schema" requirement. The endpoint SHALL be documented in the OpenAPI specification. The longest time one
stream answer may run SHALL be a setting of the agent read from its environment, never left to the default of the
embedded server.

#### Scenario: Basic streamed answer

- **WHEN** a caller sends `POST /api/v1/ai/prompt/stream` with `prompt=Tell me a story` and header `Accept: text/event-stream`
- **THEN** the response status is 200 with `Content-Type: text/event-stream`
- **AND** the body contains one or more `delta` events followed by exactly one `done` event

#### Scenario: Stream endpoint honors provider and model selection

- **WHEN** a caller sends `provider=anthropic` and `model=claude-sonnet-4-5` to the stream endpoint
- **THEN** the streamed generation is produced by the `(anthropic, claude-sonnet-4-5)` client resolved through the same `ChatModelResolver` pathway as the synchronous endpoint

#### Scenario: A stream longer than the server default completes

- **WHEN** a stream answer runs longer than the embedded server's default async request timeout and shorter than the configured stream time
- **THEN** the stream ends with its `done` event

### Requirement: SSE event schema

The stream SHALL consist of named SSE events with JSON data payloads, in this order: zero or more `delta` events, an
optional single `sources` event, and exactly one terminal event (`done` on success, `error` on failure). A later
change MAY add a non-terminal event name of its own to this closed set when it lands, and MAY then send it anywhere
before the terminal event.

- `delta` - `{"content": "<token fragment>"}`; the concatenation of all `delta` payloads in order SHALL equal the full assistant answer text.
- `sources` - `{"sources": [SourceFile, ...]}` using the same `SourceFile` JSON shape as the synchronous response (each entry carries the same fields as a synchronous source entry: the mandatory non-blank presigned `downloadUrl` and `expiresAt`, plus the registry `documentId` and the relative `contentPath` `/api/v1/documents/{id}/content` (add-document-management-api design D8)); emitted at most once, before the terminal event, and only when `attachSources=true`.
- `done` - `{"metadata": <CustomMetadata>, "conversationId": "<uuid>"}`; terminal success event, always exactly one per successful stream. Later changes add fields to `metadata` in their own tasks: `fileChanges` and `contextTrimmed` (`add-agent-soul`), and `estimatedCostUsd` (`add-usage-metering-and-quotas`, company, owner decision 65.4 of 2026-10-04).
- `error` - the RFC 7807 problem detail that `upgrade-spring-boot-4` defines for every agent error, as a JSON object with `type` (`https://ascend.ai/errors/` followed by the code with every `_` replaced by `-`), `title` (the HTTP reason phrase of `status`), `status` (the HTTP status the synchronous endpoint would have answered for the same failure), `detail` (human-readable text), `instance` (the request path), a top-level snake case `code` and a top-level `traceId` (the trace id of the stream request, set the same way as on the synchronous answer, `upgrade-spring-boot-4` D19 point 3). Terminal failure event.

No event other than these four types and the types later changes add to this set SHALL be emitted.

#### Scenario: Delta concatenation equals the full answer

- **WHEN** a streamed request completes with `delta` payloads `["Hel", "lo ", "world"]`
- **THEN** the answer persisted to chat history for that turn is exactly `Hello world`

#### Scenario: Done event carries metadata and conversation id

- **WHEN** a streamed request completes successfully
- **THEN** the final event has SSE event name `done`
- **AND** its JSON payload contains a `conversationId` field holding the UUID of the conversation the turn was appended to
- **AND** its `metadata` object follows the same `CustomMetadata` shape as the synchronous response, with unavailable fields omitted rather than serialized as `null`

#### Scenario: Sources event when attachSources is true

- **WHEN** a caller sends `attachSources=true` to the stream endpoint and RAG retrieval returns at least one chunk above the similarity threshold
- **THEN** exactly one `sources` event is emitted before the `done` event
- **AND** each entry in its `sources` array contains non-blank `documentId`, `name`, `mimeType`, `contentPath`, `downloadUrl`, and `expiresAt` fields

#### Scenario: No sources event when attachSources is omitted

- **WHEN** a caller streams a prompt without the `attachSources` field
- **THEN** the stream contains no `sources` event

### Requirement: Pre-stream validation fails as a problem detail, mid-stream failure as terminal error event

The stream endpoint SHALL run all pre-model request validation before any SSE bytes are written and SHALL report
those failures as `application/problem+json` responses holding the RFC 7807 problem detail of `upgrade-spring-boot-4`
with the corresponding HTTP status and code - unknown `compactionProvider` (400, `unknown_compaction_provider`),
image sent to a non-vision model (415, `vision_unsupported`), unknown or foreign `conversationId` (404,
`conversation_not_found`) - exactly as the synchronous endpoint does. Later changes add their own pre-stream refusals
in their own tasks, for example `context_too_large` (413) of `add-agent-soul`. Failures that occur after streaming has begun SHALL be reported as a single terminal `error` event. The
stream SHALL then be closed and no further events emitted.

#### Scenario: Unknown compaction provider rejected before streaming

- **WHEN** a caller sends `compactionProvider=does-not-exist` to the stream endpoint
- **THEN** the response is HTTP 400 with `Content-Type: application/problem+json`
- **AND** the body has `code` `unknown_compaction_provider`, `type` `https://ascend.ai/errors/unknown-compaction-provider` and a `detail` naming the offending value
- **AND** no SSE event is emitted and no model call is dispatched

#### Scenario: Provider failure mid-stream

- **WHEN** the provider connection drops after several tokens have been streamed
- **THEN** the stream emits exactly one `error` event whose payload contains the `type`, `title`, `status`, `detail`, `instance`, `code` and `traceId` fields
- **AND** its `status`, `code` and `type` equal those of the problem detail the synchronous endpoint answers for the same provider failure
- **AND** its `traceId` is the trace id of the stream request
- **AND** the stream terminates with no `done` event

### Requirement: Streaming path has pipeline parity with the synchronous path

The streaming and the synchronous endpoint SHALL run every turn through one chat executor, and the synchronous
endpoint SHALL collect that executor's stream into its one blocking answer, so a streamed turn traverses the same
pipeline as a synchronous turn: system-message assembly (user instructions,
semantic memory, RAG context), chat-history loading, prompt-cache strategy decoration with the single undecorated
retry on cache-config failure, MCP tool availability, history persistence, async compaction dispatch, and
semantic-memory extraction. The changes of build group 4 that add parts to the prompt pipeline (`add-agent-soul`,
`add-self-improvement`) add them to the streaming path in their own tasks. The turn service SHALL be callable in process with a prepared identity and attachments, for
the relay of `add-openclaw-plugin-host`, with no new endpoint. After the stream terminates, the persisted chat history for the turn SHALL be identical in
structure (one UserMessage, one AssistantMessage) to what the synchronous endpoint would have persisted for the same
answer.

#### Scenario: History parity between sync and stream

- **WHEN** the same prompt is answered once via `/prompt` and once via `/prompt/stream` in two separate conversations
- **THEN** each conversation's persisted history contains exactly one UserMessage and one AssistantMessage for the turn
- **AND** the AssistantMessage text in the streamed conversation equals the concatenation of that stream's `delta` payloads

#### Scenario: Compaction and extraction fire after a streamed turn

- **WHEN** a streamed turn completes on a conversation whose raw turn count crosses the compaction trigger
- **THEN** `ChatHistoryCompactionService.maybeCompact(...)` is dispatched asynchronously for that conversation
- **AND** semantic-memory extraction is invoked for the requesting user, exactly as on the synchronous path

#### Scenario: Client disconnect persists the partial turn without corruption

- **WHEN** the client closes the SSE connection after receiving some `delta` events
- **THEN** the agent stops the generation subscription
- **AND** chat history for the turn is written at most once (never a half-written entry per delta)

### Requirement: Synchronous prompt endpoint remains unchanged

`POST /api/v1/ai/prompt` SHALL keep its existing request fields, response shape, status codes, and blocking semantics.
The only changes permitted by this capability are additive: the optional `conversationId` form field and a
`conversationId` value inside the response `metadata` object. Callers that do not send `conversationId` SHALL observe
responses structurally identical to today's, apart from the additive metadata field.

#### Scenario: Legacy synchronous caller unaffected

- **WHEN** a client written before this change sends `POST /api/v1/ai/prompt` with only `prompt` and a valid bearer token
- **THEN** the response is a blocking JSON `AiResponse` with `content` and `metadata` exactly as before

#### Scenario: Blocking answer collected from the stream stays the same

- **WHEN** the recorded set of turns of the characterization tests (a plain answer, a tool call, `attachSources=true`, a compaction override, the undecorated cache retry, a provider error and a vision refusal) is sent to `POST /api/v1/ai/prompt` after the switch to the one executor
- **THEN** every status and JSON body equals the one recorded from the blocking path before the switch, apart from the additive `conversationId` and generated ids and times
- **AND** no existing field is renamed, removed, retyped, or moved

#### Scenario: Synchronous response echoes the conversation id

- **WHEN** a client sends a synchronous prompt with a valid `conversationId`
- **THEN** the response `metadata` contains that same `conversationId`

### Requirement: Streaming and conversations are covered by end-to-end tests against the live stack

The ascend-ai-agent e2e suite SHALL check the conversation API, the pre-stream refusals and the terminal `error` event with deterministic Bruno tests that read no model output, seeding conversation history with psql and redis-cli where messages are needed. It SHALL check the `delta`, `sources` and `done` events, auto-titles and sync and stream parity with a deterministic spec on the scripted model of the shared harness, because the checks judge the structure of the stream and of the persisted rows, never the wording. The same spec SHALL check that a streamed turn sends the fixed fact that the scripted model gives the memory extractor to the memory service, which in the deterministic phase is the AscendMemory fake of the scripted model. The specs that need the harness SHALL run in its deterministic phase only. Pass criteria SHALL be statuses, headers, event types and fields, and persisted rows and keys, never a log line.

#### Scenario: Conversation management is checked without a model

- **WHEN** the conversation spec creates, lists, renames, pages the seeded messages of and deletes a conversation, and a second user tries the same on it
- **THEN** every answer matches the conversation API, the second user gets 404 `conversation_not_found` on each operation
- **AND** after delete the Redis key and every `chat_history` row of the conversation are gone

#### Scenario: Pre-stream refusals send no event

- **WHEN** the stream validation spec sends an unknown compaction provider and a foreign conversation id to the stream endpoint
- **THEN** each answer is a problem detail with no SSE event and no `chat_history` row

#### Scenario: A provider failure ends the live stream with one error event

- **WHEN** the stream validation spec sends the marker `E2E-SCRIPT-ERROR` to the scripted model, which refuses the call
- **THEN** the stream ends with exactly one `error` event and no `done` event
- **AND** the event's `code` equals the code the synchronous endpoint answers for the same request

#### Scenario: A live streamed turn is persisted as streamed

- **WHEN** the stream spec sends a first prompt with no conversation id to the scripted model
- **THEN** the stream carries at least one `delta` and exactly one `done` with `conversationId`
- **AND** the concatenated deltas equal the assistant message persisted for the auto-created conversation

#### Scenario: A streamed turn sends its memory to the memory service

- **WHEN** the stream spec sends a first prompt to the scripted model, which answers the memory extractor's request with a fixed fact
- **THEN** the scripted model's request log holds one `POST /ascend-memory/api/v1/memory/insert` whose body carries the spec's user and that fact
