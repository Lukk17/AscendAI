## Purpose

Provides the primary chat interface where users send prompts and receive streaming AI responses within a conversation, backed by the ascend-ai-agent REST and server-sent events API.

## ADDED Requirements

### Requirement: Agent calls have a time limit
Every REST call of the app to the ascend-ai-agent, and the wait for the response headers of every stream, SHALL end after `ASCEND_HTTP_TIMEOUT_SECONDS` seconds (a build-time setting, default 30). An open stream body SHALL NOT be limited. A call that passes the limit SHALL be reported to the user as a failed call.

#### Scenario: Agent does not answer
- **WHEN** a REST call gets no answer within 30 seconds with the default setting
- **THEN** the app SHALL end the call and show that it failed

#### Scenario: Long stream is not cut
- **WHEN** a stream answered with its headers and keeps sending events for longer than 30 seconds
- **THEN** the app SHALL keep reading the stream until its terminal event

### Requirement: Chat widget renders conversation messages
The app SHALL display messages in a scrollable, animated list using the `flutter_chat_ui` `Chat` widget with a reversed list layout so the newest messages appear at the bottom near the composer.

#### Scenario: Empty conversation
- **WHEN** the user opens a conversation that has no messages
- **THEN** the chat area SHALL be empty with the composer input visible and ready for typing

#### Scenario: Existing messages loaded from API
- **WHEN** the user opens a conversation with existing messages
- **THEN** the app SHALL fetch messages from `GET /api/v1/conversations/{id}/messages` and display them in chronological order (oldest at top, newest at bottom)

#### Scenario: Paginated history loading
- **WHEN** the user scrolls upward past the oldest loaded message
- **THEN** the app SHALL fetch the next page of older messages from the conversation history endpoint and prepend them to the list without scroll position jump

### Requirement: User can send a text prompt
The app SHALL allow the user to type a message in the composer and send it to the ascend-ai-agent prompt endpoint.

#### Scenario: Sending a text-only prompt
- **WHEN** the user types a message and presses send
- **THEN** the app SHALL immediately insert the user message into the chat list, send `POST /api/v1/ai/prompt/stream` with the message text and the current `conversationId`, and display the assistant response as it streams in

#### Scenario: Composer clears after send
- **WHEN** the user sends a message
- **THEN** the composer input field SHALL be cleared and the chat SHALL scroll to the bottom

### Requirement: Streaming assistant responses display token by token
The app SHALL consume server-sent events from the streaming prompt endpoint and render the assistant response progressively.

#### Scenario: Successful streaming response
- **WHEN** the backend emits `delta` events with partial content
- **THEN** the app SHALL append each delta to the current assistant message bubble in real time, producing a typewriter effect

#### Scenario: Stream completes
- **WHEN** the backend emits a `done` event
- **THEN** the app SHALL finalize the assistant message, persist the `conversationId` from the done payload, and re-enable the composer

#### Scenario: Stream error mid-response
- **WHEN** the backend emits an `error` event during streaming
- **THEN** the app SHALL display the `detail` of the event's problem detail payload in a system message bubble and re-enable the composer

### Requirement: Pre-stream validation errors are surfaced
The app SHALL handle HTTP 4xx responses returned before any server-sent events bytes are written. Every error body of the agent, and the payload of the `error` event, is the RFC 7807 problem detail that `upgrade-spring-boot-4` defines (`application/problem+json` with `type`, `title`, `status`, `detail`, `instance` and a top-level `code`). The app SHALL parse that body into one typed error holding `status`, `code` and `detail`, SHALL decide what to do from `status` and `code`, and SHALL show `detail` to the user. When a body cannot be parsed as a problem detail, the app SHALL show a generic error text with the HTTP status.

#### Scenario: Invalid provider combination
- **WHEN** the backend returns `400 Bad Request` with `Content-Type: application/problem+json` before the stream starts
- **THEN** the app SHALL display the `detail` of the problem detail body as a dismissible notification

#### Scenario: Conversation not found
- **WHEN** the backend returns `404 Not Found` with `code` `conversation_not_found` for the conversation
- **THEN** the app SHALL navigate back to the conversation list and display an error notification

#### Scenario: Error body that is not a problem detail
- **WHEN** a proxy in front of the agent returns `502 Bad Gateway` with an HTML body
- **THEN** the app SHALL display a generic error notification naming status 502 and SHALL NOT fail

### Requirement: Custom ChatController bridges the conversation API
The app SHALL implement a custom `ChatController` (extending the `flutter_chat_core` `ChatController` interface) that persists messages through the ascend-ai-agent conversation endpoints rather than in-memory only.

#### Scenario: Controller loads initial messages
- **WHEN** the chat screen initializes with a `conversationId`
- **THEN** the controller SHALL load the most recent page of messages from the conversation history endpoint and populate the list

#### Scenario: Controller disposes cleanly
- **WHEN** the user navigates away from the chat screen
- **THEN** the controller SHALL cancel any active server-sent events connection and release resources

### Requirement: The app connects directly to a configurable agent address
The app SHALL be a standalone client that calls the ascend-ai-agent API directly at a base URL set at build time with `--dart-define=ASCEND_API_URL=<url>`, defaulting to `http://localhost:9917` for local development. The app SHALL NOT depend on a reverse proxy or on being served by the agent. On the web build, streaming SHALL read the response body of the `POST /api/v1/ai/prompt/stream` request through fetch-based streaming (`package:web`), never `EventSource` and never `dart:html`.

#### Scenario: Phone on the same network
- **WHEN** the app is built with `--dart-define=ASCEND_API_URL=http://192.168.1.20:9917` and run on a phone on the same network as the agent host
- **THEN** listing conversations and sending a streamed prompt SHALL succeed against that address

#### Scenario: Web build streams through fetch
- **WHEN** the web build sends a prompt
- **THEN** the app SHALL issue one `POST` to `/api/v1/ai/prompt/stream` and render `delta` events as they arrive

### Requirement: The stream parser accepts later event types
The app SHALL read the non-terminal stream events `run_started` and `subagent_status` (each `{"run": <run view>}`, defined by `add-agent-subagents`) and `approval_required` (`{"approval": <approval view>}`, defined by `add-action-approvals`) in addition to `delta`, `citations`, `sources`, `done` and `error`. An event whose name the app does not know SHALL be skipped without ending the stream, without an error message and without changing the assistant message.

#### Scenario: Run events during a streamed answer
- **WHEN** the stream sends `delta`, then `run_started`, then `subagent_status`, then more `delta` events and `done`
- **THEN** the assistant message SHALL hold the text of every `delta` in order, and the stream SHALL end normally on `done`

#### Scenario: Unknown event name
- **WHEN** the stream sends an event named `future_event` between two `delta` events
- **THEN** the app SHALL skip it, show no error, and keep appending the following `delta` text

### Requirement: An approval card shows each approval the turn asks for
When the stream sends an `approval_required` event, the app SHALL insert an approval card into the conversation that shows the approval's kind, its preview, its exact arguments, its expiry time in the device's local time, an Approve button, a Deny button, and a "Remember this choice" switch that SHALL be shown only when `rememberable` is true. Pressing a button SHALL send `POST /api/v1/approvals/{id}/approve` or `POST /api/v1/approvals/{id}/deny` with `argumentsDigest` from the approval view shown on the card, `remember` from the switch (false when the switch is not shown) and `channel` `app`. The card SHALL then show the outcome. A refusal SHALL show the `detail` of its problem detail. A 409 with `code` `approval_already_decided` SHALL show "Already decided" and reload the view from `GET /api/v1/approvals/{id}`, and a 409 with `code` `approval_digest_mismatch` SHALL reload the view and ask the owner to read it again before deciding. Every `approval_required` event SHALL also refresh the pending approvals list.

#### Scenario: Approve with remember
- **WHEN** an `approval_required` event arrives with `rememberable` true and the owner turns on the switch and presses Approve
- **THEN** the app SHALL send `POST /api/v1/approvals/{id}/approve` with the card's `argumentsDigest`, `remember` true and `channel` `app`, and the card SHALL show that the action was approved

#### Scenario: Switch hidden when the choice cannot be remembered
- **WHEN** an `approval_required` event arrives with `rememberable` false
- **THEN** the card SHALL show no "Remember this choice" switch, and a decision SHALL send `remember` false

#### Scenario: Already decided elsewhere
- **WHEN** the owner presses Deny and the agent answers 409 with `code` `approval_already_decided`
- **THEN** the card SHALL show "Already decided" and the decision read again from `GET /api/v1/approvals/{id}`
