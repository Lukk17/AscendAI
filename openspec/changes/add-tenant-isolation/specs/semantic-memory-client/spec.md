## ADDED Requirements

### Requirement: Tenant-qualified user id on every AscendMemory call

`SemanticMemoryClient` SHALL compose the outbound `user_id` value as `{tenantId}:{userId}` for every AscendMemory operation (search, insert, wipe, delete), where `{tenantId}` is resolved from the request's tenant context in exactly one place inside the client. Because AscendMemory partitions memories by `user_id`, this namespacing guarantees memories cannot be read or written across tenants without any AscendMemory service change. Calls without a resolved tenant context SHALL fail with an error (or short-circuit as a logged no-op for fire-and-forget inserts) and SHALL NOT send an unqualified `user_id`.

#### Scenario: Memories do not cross tenants

- **WHEN** a fact is inserted during a chat by user `frosty` of tenant `acme`, and user `frosty` of tenant `globex` later asks a question that would recall it
- **THEN** the search for `globex` uses `user_id=globex:frosty` and returns zero items derived from `acme`'s fact

#### Scenario: No unqualified user id leaves the agent

- **WHEN** any `SemanticMemoryClient` method executes with tenant context `acme` and userId `frosty`
- **THEN** the outgoing HTTP request carries `user_id` equal to `acme:frosty`
- **AND** it never carries the bare value `frosty`

## MODIFIED Requirements

### Requirement: AscendMemory search uses snake_case query parameters

`SemanticMemoryClient` SHALL invoke `GET ${baseUrl}/api/v1/memory/search` using the query parameter name `user_id` (snake_case) so that the request matches the AscendMemory FastAPI endpoint contract. The client SHALL NOT use `userId` (camelCase) for this endpoint. The parameter value SHALL be the tenant-qualified id `{tenantId}:{userId}`.

#### Scenario: Search call URI

- **WHEN** `SemanticMemoryClient.search("frosty", "name", 5, "openai")` is invoked with tenant context `acme`
- **THEN** the outgoing HTTP GET URL contains `user_id=acme:frosty` (URL-encoded as needed) and does NOT contain `userId=`
- **AND** the call returns a non-error response (200) when AscendMemory is healthy

#### Scenario: End-to-end memory recall

- **WHEN** a fact has been previously inserted for user `frosty` of tenant `acme` and the user asks a question that should recall it
- **THEN** ascend-ai-agent logs `Received N semantic memory items for user: 'frosty'` with N >= 1
- **AND** ascend-ai-agent does NOT log `Semantic memory search failed for user 'frosty'. Status: 500 INTERNAL_SERVER_ERROR`

### Requirement: Wipe and delete operations are exposed by the client

`SemanticMemoryClient` SHALL expose `wipeUserMemory(userId, embeddingProvider)` and `deleteMemory(userId, memoryId, embeddingProvider)` methods that call the corresponding AscendMemory FastAPI endpoints (`POST /api/v1/memory/wipe` and `DELETE /api/v1/memory`). Bodies and query params SHALL use snake_case (`user_id`, `provider`), and the `user_id` value SHALL be the tenant-qualified id `{tenantId}:{userId}`.

#### Scenario: Wipe call

- **WHEN** `wipeUserMemory("frosty", "openai")` is invoked with tenant context `acme`
- **THEN** the client POSTs to `/api/v1/memory/wipe` with body `{"user_id":"acme:frosty","provider":"openai"}`
- **AND** a 200/204 response causes no exception

#### Scenario: Delete call

- **WHEN** `deleteMemory("frosty", "abc-123", "openai")` is invoked with tenant context `acme`
- **THEN** the client issues an HTTP DELETE to `/api/v1/memory` (with the memory id and `user_id=acme:frosty` in the appropriate location matching the FastAPI server)
- **AND** a 200/204 response causes no exception

### Requirement: AscendMemory insert request body uses snake_case keys

`SemanticMemoryClient` SHALL POST `/api/v1/memory/insert` with a JSON body whose keys are `user_id`, `text`, and `provider`. The `user_id` value SHALL be the tenant-qualified id `{tenantId}:{userId}`.

#### Scenario: Insert body shape

- **WHEN** `SemanticMemoryClient.insertMemory("frosty", "User's name is Luke", "openai")` is invoked with tenant context `acme`
- **THEN** the outgoing JSON body equals `{"user_id":"acme:frosty","text":"User's name is Luke","provider":"openai"}`
