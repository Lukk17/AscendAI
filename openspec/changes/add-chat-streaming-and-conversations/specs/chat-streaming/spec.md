# chat-streaming Delta Specification

## ADDED Requirements

### Requirement: SSE streaming prompt endpoint

The agent SHALL expose `POST /api/v1/ai/prompt/stream` consuming `multipart/form-data` and producing
`text/event-stream`. The endpoint SHALL accept the same form fields as `POST /api/v1/ai/prompt` — `prompt` (required),
`image`, `document`, `provider`, `model`, `embeddingProvider`, `attachSources`, `compactionProvider`,
`compactionModel` — plus the optional `conversationId` field, and the `X-User-Id` header with the same default-id
fallback. The response SHALL be a Server-Sent Events stream whose events follow the schema defined in the
"SSE event schema" requirement. The endpoint SHALL be documented in the OpenAPI specification.

#### Scenario: Basic streamed answer

- **WHEN** a caller sends `POST /api/v1/ai/prompt/stream` with `prompt=Tell me a story` and header `Accept: text/event-stream`
- **THEN** the response status is 200 with `Content-Type: text/event-stream`
- **AND** the body contains one or more `delta` events followed by exactly one `done` event

#### Scenario: Stream endpoint honors provider and model selection

- **WHEN** a caller sends `provider=anthropic` and `model=claude-sonnet-4-5` to the stream endpoint
- **THEN** the streamed generation is produced by the `(anthropic, claude-sonnet-4-5)` client resolved through the same `ChatModelResolver` pathway as the synchronous endpoint

### Requirement: SSE event schema

The stream SHALL consist of named SSE events with JSON data payloads, in this order: zero or more `delta` events, an
optional single `sources` event, and exactly one terminal event (`done` on success, `error` on failure).

- `delta` — `{"content": "<token fragment>"}`; the concatenation of all `delta` payloads in order SHALL equal the full assistant answer text.
- `sources` — `{"sources": [SourceFile, ...]}` using the same `SourceFile` JSON shape as the synchronous response (per the presign-resolution amendment, each entry carries the registry `documentId` and the relative `contentPath` `/api/v1/documents/{id}/content`, not a presigned MinIO URL); emitted at most once, before the terminal event, and only when `attachSources=true`.
- `done` — `{"metadata": <CustomMetadata>, "conversationId": "<uuid>"}`; terminal success event, always exactly one per successful stream.
- `error` — `{"status": <int>, "code": "<machine-readable code>", "message": "<human-readable text>"}`; terminal failure event.

No event other than these four types SHALL be emitted.

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
- **AND** each entry in its `sources` array contains non-blank `documentId`, `name`, `mimeType`, and `contentPath` fields

#### Scenario: No sources event when attachSources is omitted

- **WHEN** a caller streams a prompt without the `attachSources` field
- **THEN** the stream contains no `sources` event

### Requirement: Pre-stream validation fails as plain JSON, mid-stream failure as terminal error event

The stream endpoint SHALL run all pre-model request validation before any SSE bytes are written and SHALL report
those failures as plain JSON `ApiError` responses with the corresponding HTTP status — unknown `compactionProvider`
(400), image sent to a non-vision model (415), unknown or foreign `conversationId` (404) — exactly as the synchronous
endpoint does. Failures that occur after streaming has begun SHALL be reported as a single terminal `error` event; the
stream SHALL then be closed and no further events emitted.

#### Scenario: Unknown compaction provider rejected before streaming

- **WHEN** a caller sends `compactionProvider=does-not-exist` to the stream endpoint
- **THEN** the response is HTTP 400 with `Content-Type: application/json` and an `ApiError` body naming the offending field
- **AND** no SSE event is emitted and no model call is dispatched

#### Scenario: Provider failure mid-stream

- **WHEN** the provider connection drops after several tokens have been streamed
- **THEN** the stream emits exactly one `error` event whose payload contains `status`, `code`, and `message` fields
- **AND** the stream terminates with no `done` event

### Requirement: Streaming path has pipeline parity with the synchronous path

A streamed turn SHALL traverse the same pipeline as a synchronous turn: system-message assembly (user instructions,
semantic memory, RAG context), chat-history loading, prompt-cache strategy decoration with the single undecorated
retry on cache-config failure, MCP tool availability, history persistence, async compaction dispatch, and
semantic-memory extraction. After the stream terminates, the persisted chat history for the turn SHALL be identical in
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

- **WHEN** a client written before this change sends `POST /api/v1/ai/prompt` with only `prompt` and `X-User-Id`
- **THEN** the response is a blocking JSON `AiResponse` with `content` and `metadata` exactly as before
- **AND** no existing field is renamed, removed, retyped, or moved

#### Scenario: Synchronous response echoes the conversation id

- **WHEN** a client sends a synchronous prompt with a valid `conversationId`
- **THEN** the response `metadata` contains that same `conversationId`
