## ADDED Requirements

### Requirement: AscendMemory search uses snake_case query parameters

`SemanticMemoryClient` SHALL invoke `GET ${baseUrl}/api/v1/memory/search` using the query parameter name `user_id` (snake_case) so that the request matches the AscendMemory FastAPI endpoint contract. The client SHALL NOT use `userId` (camelCase) for this endpoint.

#### Scenario: Search call URI

- **WHEN** `SemanticMemoryClient.search("frosty", "name", 5, "openai")` is invoked
- **THEN** the outgoing HTTP GET URL contains `user_id=frosty` (URL-encoded as needed) and does NOT contain `userId=`
- **AND** the call returns a non-error response (200) when AscendMemory is healthy

#### Scenario: End-to-end memory recall

- **WHEN** a fact has been previously inserted for user `frosty` and the user asks a question that should recall it
- **THEN** AscendAgent logs `Received N semantic memory items for user: 'frosty'` with N >= 1
- **AND** AscendAgent does NOT log `Semantic memory search failed for user 'frosty'. Status: 500 INTERNAL_SERVER_ERROR`

### Requirement: Wipe and delete operations are exposed by the client

`SemanticMemoryClient` SHALL expose `wipeUserMemory(userId, embeddingProvider)` and `deleteMemory(userId, memoryId, embeddingProvider)` methods that call the corresponding AscendMemory FastAPI endpoints (`POST /api/v1/memory/wipe` and `DELETE /api/v1/memory`). Bodies and query params SHALL use snake_case (`user_id`, `provider`).

#### Scenario: Wipe call

- **WHEN** `wipeUserMemory("frosty", "openai")` is invoked
- **THEN** the client POSTs to `/api/v1/memory/wipe` with body `{"user_id":"frosty","provider":"openai"}`
- **AND** a 200/204 response causes no exception

#### Scenario: Delete call

- **WHEN** `deleteMemory("frosty", "abc-123", "openai")` is invoked
- **THEN** the client issues an HTTP DELETE to `/api/v1/memory` (with the memory id and `user_id=frosty` in the appropriate location matching the FastAPI server)
- **AND** a 200/204 response causes no exception

### Requirement: User id validation at client entry

Every public method on `SemanticMemoryClient` SHALL validate that `userId` is non-null and non-blank. When invalid, the call SHALL log a single WARN and short-circuit (return empty list for `search`, no-op for `insert`/`wipe`/`delete`) without invoking the HTTP layer.

#### Scenario: Blank userId on search

- **WHEN** `search("", "name", 5, "openai")` is invoked
- **THEN** no HTTP call is made
- **AND** the method returns an empty list

#### Scenario: Null userId on insert

- **WHEN** `insertMemory(null, "fact", "openai")` is invoked
- **THEN** no HTTP call is made and the method returns normally

### Requirement: Default base URL matches docker-compose

`SemanticMemoryProperties` SHALL default `baseUrl` to `http://localhost:7020` so that an out-of-the-box AscendAgent run against the monorepo `docker-compose.yaml` connects to AscendMemory without overrides.

#### Scenario: Boot with no overrides

- **WHEN** AscendAgent boots with no `app.memory.semantic.base-url` override
- **THEN** `SemanticMemoryProperties.getBaseUrl()` returns `http://localhost:7020`

### Requirement: Failed-fact aggregation on extract+insert

When `SemanticMemoryExtractor` extracts N facts and inserts them into AscendMemory, it SHALL log a single summary line of the form `Inserted {ok}/{N} facts for user '{userId}' (failed: {n})` whenever any insert fails, and SHALL NOT silently drop failures.

#### Scenario: Two facts, one insert fails

- **WHEN** the extractor produces two facts and the second `insertMemory` call throws
- **THEN** logs include `Inserted 1/2 facts for user '<userId>' (failed: 1)` at WARN
- **AND** the user-facing prompt response is unaffected

### Requirement: AscendMemory insert request body uses snake_case keys

`SemanticMemoryClient` SHALL POST `/api/v1/memory/insert` with a JSON body whose keys are `user_id`, `text`, and `provider`. (This already matches today's behavior; the requirement pins it so it cannot regress.)

#### Scenario: Insert body shape

- **WHEN** `SemanticMemoryClient.insertMemory("frosty", "User's name is Luke", "openai")` is invoked
- **THEN** the outgoing JSON body equals `{"user_id":"frosty","text":"User's name is Luke","provider":"openai"}`
