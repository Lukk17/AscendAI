## Purpose

Provides the primary chat interface where users send prompts and receive streaming AI responses within a conversation, backed by the AscendAgent REST and server-sent events API.

## ADDED Requirements

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
The app SHALL allow the user to type a message in the composer and send it to the AscendAgent prompt endpoint.

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
- **THEN** the app SHALL display the error message in a system message bubble and re-enable the composer

### Requirement: Pre-stream validation errors are surfaced
The app SHALL handle HTTP 4xx responses returned before any server-sent events bytes are written.

#### Scenario: Invalid provider combination
- **WHEN** the backend returns `400 Bad Request` before the stream starts
- **THEN** the app SHALL display the error message from the JSON `ApiError` body as a dismissible notification

#### Scenario: Conversation not found
- **WHEN** the backend returns `404 Not Found` for the conversation
- **THEN** the app SHALL navigate back to the conversation list and display an error notification

### Requirement: Custom ChatController bridges the conversation API
The app SHALL implement a custom `ChatController` (extending the `flutter_chat_core` `ChatController` interface) that persists messages through the AscendAgent conversation endpoints rather than in-memory only.

#### Scenario: Controller loads initial messages
- **WHEN** the chat screen initializes with a `conversationId`
- **THEN** the controller SHALL load the most recent page of messages from the conversation history endpoint and populate the list

#### Scenario: Controller disposes cleanly
- **WHEN** the user navigates away from the chat screen
- **THEN** the controller SHALL cancel any active server-sent events connection and release resources
