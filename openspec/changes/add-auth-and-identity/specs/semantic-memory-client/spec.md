## ADDED Requirements

### Requirement: Outbound requests carry the service bearer token

`SemanticMemoryClient` SHALL attach `Authorization: Bearer <SERVICE_AUTH_TOKEN>` to every HTTP request it issues to AscendMemory (`search`, `insertMemory`, `wipeUserMemory`, `deleteMemory`), sourcing the token from configuration injected via environment variable. When the token is not configured (dev / bare local run), the client SHALL send requests without the header, matching AscendMemory's open dev posture. The token value SHALL never be logged.

#### Scenario: Search request carries the token

- **WHEN** `SemanticMemoryClient.search("frosty", "name", 5, "openai")` is invoked with a configured service token
- **THEN** the outgoing HTTP request contains header `Authorization: Bearer <the configured token>`
- **AND** the existing query-parameter contract (`user_id=frosty`) is unchanged

#### Scenario: Wipe request carries the token

- **WHEN** `wipeUserMemory("frosty", "openai")` is invoked with a configured service token
- **THEN** the POST to `/api/v1/memory/wipe` carries the bearer header and the unchanged snake_case body

#### Scenario: No token configured means no header

- **WHEN** any client method is invoked with no service token configured
- **THEN** the outgoing request has no `Authorization` header
- **AND** no error or WARN-per-request is produced
