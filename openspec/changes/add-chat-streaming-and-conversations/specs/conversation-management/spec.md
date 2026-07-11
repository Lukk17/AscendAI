# conversation-management Delta Specification

## ADDED Requirements

### Requirement: Conversation entity and schema

The agent SHALL persist conversations in a `conversations` table created by a new Liquibase changelog with columns:
`id` (UUID, primary key, generated server-side), `tenant_id` (VARCHAR, nullable — reserved for the tenant-isolation
change, unused here), `user_id` (VARCHAR, not null, indexed), `title` (VARCHAR(255), not null), `created_at`
(TIMESTAMP, not null), and `updated_at` (TIMESTAMP, not null). The `chat_history` table SHALL gain an indexed
`conversation_id` UUID column with a foreign key to `conversations.id`. `updated_at` SHALL be bumped whenever a
message is appended to the conversation and whenever it is renamed.

#### Scenario: Schema after migration

- **WHEN** the application boots against a database at the previous changelog level
- **THEN** Liquibase creates the `conversations` table with the columns above
- **AND** `chat_history.conversation_id` exists, is NOT NULL, and carries a foreign key to `conversations.id`

#### Scenario: Message append bumps updated_at

- **WHEN** a prompt turn is appended to an existing conversation
- **THEN** that conversation's `updated_at` is set to the append time
- **AND** `created_at` is unchanged

### Requirement: Chat history is keyed by conversation id

Chat-history reads and writes SHALL be keyed by the conversation UUID instead of the raw user id: the Redis key SHALL
be `chat:<conversationId>` and Postgres history queries SHALL filter on `chat_history.conversation_id`. Two
conversations belonging to the same user SHALL have fully isolated histories. Semantic-memory extraction SHALL remain
keyed by user id (memories belong to the user, not to a single conversation).

#### Scenario: Two conversations of one user are isolated

- **WHEN** user `frosty` sends prompts into conversation A and conversation B
- **THEN** loading history for conversation A returns only A's messages
- **AND** the Redis keys `chat:<A-uuid>` and `chat:<B-uuid>` exist independently

#### Scenario: Semantic memory stays user-scoped

- **WHEN** user `frosty` states a fact in conversation A and later asks about it in conversation B
- **THEN** the semantic-memory search for the conversation-B prompt runs with `userId=frosty` and can surface the fact extracted from conversation A

### Requirement: Conversation resolution on prompt endpoints

Both `POST /api/v1/ai/prompt` and `POST /api/v1/ai/prompt/stream` SHALL accept an optional `conversationId` form
field. When supplied, the conversation MUST exist and belong to the requesting user; otherwise the endpoint SHALL
respond 404 with an `ApiError` body before any model call. When omitted, the agent SHALL use the requesting user's
most-recently-updated conversation, auto-creating one if the user has none — preserving the previous single-thread
behavior for callers that never send the field.

#### Scenario: Supplied conversation id routes the turn

- **WHEN** a caller sends a prompt with `conversationId=<uuid>` owned by the requesting user
- **THEN** the turn's history is loaded from and appended to exactly that conversation

#### Scenario: Foreign conversation id returns 404

- **WHEN** user `frosty` sends a prompt with a `conversationId` that belongs to user `blaze`
- **THEN** the response is HTTP 404 with an `ApiError` body
- **AND** no model call is dispatched and no history is written

#### Scenario: Omitted conversation id falls back to most recent

- **WHEN** a user with two existing conversations sends a prompt without `conversationId`
- **THEN** the turn is appended to the conversation with the latest `updated_at`

#### Scenario: First prompt of a new user auto-creates a conversation

- **WHEN** a user with zero conversations sends a prompt without `conversationId`
- **THEN** a new conversation row is created for that user before the turn is persisted
- **AND** the response (metadata or `done` event) carries the new conversation's UUID

### Requirement: Auto-title from the first prompt

A conversation created implicitly by a prompt SHALL be titled with that prompt's text, whitespace-trimmed and
truncated to at most 80 characters at a word boundary with a trailing ellipsis when truncated. A conversation created
explicitly via the management API SHALL use the caller-provided title, defaulting to `New conversation` when the title
is omitted or blank. No LLM call SHALL be made for titling.

#### Scenario: Short prompt becomes the title verbatim

- **WHEN** a new conversation is auto-created by the prompt `What is the weather in Warsaw?`
- **THEN** the conversation title is `What is the weather in Warsaw?`

#### Scenario: Long prompt is truncated at a word boundary

- **WHEN** a new conversation is auto-created by a 300-character prompt
- **THEN** the stored title is at most 80 characters, ends with an ellipsis, and does not cut a word in half

### Requirement: List conversations API

`GET /api/v1/conversations` SHALL return the requesting user's conversations sorted by `updated_at` descending,
paginated via `page` (0-based, default 0) and `size` (default 20, maximum 100) query parameters. The response SHALL be
a stable page envelope `{items, page, size, totalItems, totalPages}` where each item contains `id`, `title`,
`createdAt`, and `updatedAt`. Conversations of other users SHALL never appear.

#### Scenario: Most-recent-first ordering

- **WHEN** a user with conversations last updated at T1 < T2 < T3 calls `GET /api/v1/conversations`
- **THEN** the response items are ordered T3, T2, T1

#### Scenario: Pagination window

- **WHEN** a user with 25 conversations calls `GET /api/v1/conversations?page=1&size=10`
- **THEN** the response contains items 11-20 of the ordering, with `totalItems=25` and `totalPages=3`

#### Scenario: Other users' conversations are invisible

- **WHEN** user `frosty` lists conversations while user `blaze` has conversations of their own
- **THEN** no conversation of `blaze` appears in `frosty`'s response

### Requirement: Conversation messages API

`GET /api/v1/conversations/{id}/messages` SHALL return the conversation's persisted messages in chronological order,
paginated with the same `page`/`size` envelope as the list endpoint. Each item SHALL contain `role`, `content`, and
`createdAt`. Requests for a conversation not owned by the requesting user SHALL return 404.

#### Scenario: Messages in chronological order

- **WHEN** a conversation contains 4 turns and the owner calls `GET /api/v1/conversations/{id}/messages`
- **THEN** the response items appear oldest-first with alternating `user` / `assistant` roles

#### Scenario: Foreign conversation messages return 404

- **WHEN** user `frosty` requests messages of a conversation owned by `blaze`
- **THEN** the response is HTTP 404 and contains no message content

### Requirement: Create and rename conversations

`POST /api/v1/conversations` SHALL create a conversation for the requesting user with an optional `title` in the JSON
body, responding 201 with the created representation and a `Location` header. `PATCH /api/v1/conversations/{id}` SHALL
update the title (non-blank, at most 255 characters), responding 200 with the updated representation; a blank or
over-length title SHALL be rejected with 400.

#### Scenario: Explicit creation

- **WHEN** a caller sends `POST /api/v1/conversations` with `{"title": "Trip planning"}`
- **THEN** the response is HTTP 201 with a `Location` header ending in the new conversation's UUID
- **AND** the body contains `id`, `title` = `Trip planning`, `createdAt`, and `updatedAt`

#### Scenario: Rename

- **WHEN** the owner sends `PATCH /api/v1/conversations/{id}` with `{"title": "Renamed"}`
- **THEN** the response is HTTP 200 and a subsequent list call shows the new title

#### Scenario: Blank title rejected

- **WHEN** the owner sends a `PATCH` with `{"title": "   "}`
- **THEN** the response is HTTP 400 with an `ApiError` body and the stored title is unchanged

### Requirement: Delete conversation removes all its history

`DELETE /api/v1/conversations/{id}` SHALL respond 204 and remove the Redis key `chat:<id>`, all `chat_history` rows
with that `conversation_id`, and the `conversations` row itself. The Postgres deletions SHALL run in a single
transaction. Deleting a conversation not owned by the requesting user SHALL return 404 and delete nothing. A deleted
conversation id used on a prompt endpoint SHALL return 404.

#### Scenario: Delete cascades across both backends

- **WHEN** the owner deletes a conversation that has Redis-cached and Postgres-persisted history
- **THEN** the response is HTTP 204
- **AND** the Redis key `chat:<id>` no longer exists
- **AND** `chat_history` contains zero rows for that `conversation_id`
- **AND** the `conversations` row is gone

#### Scenario: Foreign delete is refused

- **WHEN** user `frosty` attempts to delete a conversation owned by `blaze`
- **THEN** the response is HTTP 404
- **AND** `blaze`'s conversation and history rows are untouched

### Requirement: Existing history migrates into one conversation per user

The Liquibase migration SHALL backfill existing data: for every distinct `user_id` present in `chat_history`, exactly
one `conversations` row SHALL be created (title `Imported conversation`, `created_at` = the user's earliest history
row, `updated_at` = the latest), and every `chat_history` row SHALL be linked to its user's conversation before the
`NOT NULL` and foreign-key constraints are applied. Old Redis keys of the form `chat:<userId>` SHALL NOT be migrated;
they expire via the existing TTL while reads under the new key hydrate from Postgres.

#### Scenario: Backfill links every legacy row

- **WHEN** the migration runs against a database where users `frosty` (10 rows) and `blaze` (4 rows) have history
- **THEN** `conversations` contains exactly one row per user titled `Imported conversation`
- **AND** all 14 `chat_history` rows have a non-null `conversation_id` pointing at their owner's conversation

#### Scenario: Post-migration prompt continues the imported thread

- **WHEN** user `frosty` sends a prompt without `conversationId` after the migration
- **THEN** the turn is appended to `frosty`'s imported conversation
- **AND** the loaded history includes the pre-migration messages hydrated from Postgres
