## ADDED Requirements

### Requirement: Downstream services require a bearer service token on REST surfaces

AscendMemory, ascend-audio-scribe, ascend-web-hunter, ascend-ocr, and ascend-weather-mcp SHALL reject any REST request that does not carry `Authorization: Bearer <SERVICE_AUTH_TOKEN>` with HTTP 401, where `SERVICE_AUTH_TOKEN` is injected via environment variable. Token comparison SHALL be constant-time. Liveness/readiness endpoints (`/health`, and `/ready` / `/metrics` where present) SHALL remain unauthenticated so Docker healthchecks and Prometheus scrapes keep working. The token value SHALL never appear in logs or in checked-in configuration defaults.

#### Scenario: Destructive memory endpoint rejects tokenless calls

- **WHEN** `POST /api/v1/memory/wipe` is called on AscendMemory without an `Authorization` header while `SERVICE_AUTH_TOKEN` is set
- **THEN** the response status is 401
- **AND** no memory is deleted from Qdrant

#### Scenario: Correct token is accepted

- **WHEN** `GET /api/v1/memory/search` is called with `Authorization: Bearer <the configured token>`
- **THEN** the request is processed normally (non-401 response)

#### Scenario: OCR job routes reject tokenless calls

- **WHEN** `POST /v1/ocr/jobs`, `GET /v1/ocr/jobs/{job_id}`, `GET /v1/ocr/jobs` or `DELETE /v1/ocr/jobs/{job_id}` is called on ascend-ocr without an `Authorization` header while `SERVICE_AUTH_TOKEN` is set
- **THEN** the response status is 401
- **AND** no job record is created, read, listed or cancelled
- **AND** `GET /health` and `GET /ready` still answer without a token

#### Scenario: Wrong token is rejected

- **WHEN** any protected REST endpoint on any of the five services is called with `Authorization: Bearer wrong-value`
- **THEN** the response status is 401

#### Scenario: Health stays open

- **WHEN** `GET /health` is called on each Python service without credentials
- **THEN** the response status is 200

### Requirement: Downstream services require the bearer service token on MCP surfaces

The MCP surface of each downstream service (FastMCP Streamable HTTP endpoints on the Python services, and the Spring AI MCP endpoint on ascend-weather-mcp) SHALL enforce the same bearer-token check as the REST surface, so the MCP transport is not an authentication bypass.

#### Scenario: Tokenless MCP call is rejected

- **WHEN** an MCP `tools/call` request is sent to a downstream service's MCP endpoint without an `Authorization` header while `SERVICE_AUTH_TOKEN` is set
- **THEN** the request is rejected with an HTTP 401 (no tool executes)

#### Scenario: MCP call with the token succeeds

- **WHEN** the same MCP request carries `Authorization: Bearer <the configured token>`
- **THEN** the tool call executes normally

### Requirement: Enforcement posture follows token presence

When `SERVICE_AUTH_TOKEN` is set, enforcement SHALL be active. When it is unset or blank: in the docker/compose posture the service SHALL fail fast at startup rather than boot with an open surface, and in a bare local run (uvicorn / bootRun without the variable) the service SHALL log a single startup WARN that inbound auth is disabled and accept requests, preserving the existing developer workflow.

#### Scenario: Docker posture refuses to boot open

- **WHEN** a downstream service container starts in the compose stack with `SERVICE_AUTH_TOKEN` unset
- **THEN** the process exits with a non-zero status and a clear error message before serving traffic

#### Scenario: Bare local run warns and stays open

- **WHEN** a service is started directly via uvicorn or bootRun without `SERVICE_AUTH_TOKEN`
- **THEN** it serves requests without requiring a token
- **AND** the startup log contains a WARN that inbound authentication is disabled

### Requirement: ascend-ai-agent attaches the service token on all outbound calls

ascend-ai-agent SHALL send `Authorization: Bearer <SERVICE_AUTH_TOKEN>` on every outbound request to the downstream services: the AscendMemory REST client, the ascend-ocr ingestion client, and every MCP client connection to one of our own MCP servers (ascend-audio-scribe, weather, ascend-web-hunter). The token SHALL never be sent to an MCP server that is not one of ours. Once `add-mcp-tool-servers` gives each server entry a `trust` field, our own servers SHALL be exactly the entries with `trust: internal`, and the token SHALL be set through that change's connection customizer. With the compose stack fully secured, a chat turn that exercises memory and an MCP tool SHALL complete without any downstream 401.

#### Scenario: MCP tool call carries the token

- **WHEN** a prompt causes ascend-ai-agent to invoke a ascend-weather-mcp tool in the secured compose stack
- **THEN** the MCP HTTP request from the agent carries the bearer service token
- **AND** the tool result reaches the model (no 401 in the tool-call path)

#### Scenario: An outside MCP server never receives the token

- **WHEN** a prompt causes ascend-ai-agent to call a tool of an MCP server that is not one of ours, which `add-mcp-tool-servers` marks `trust: external`
- **THEN** the MCP HTTP request to that server carries no service token

#### Scenario: End-to-end secured chat turn

- **WHEN** a chat turn triggers a semantic-memory search and insert against AscendMemory with all services enforcing the token
- **THEN** the turn completes with HTTP 200 and no downstream call is rejected with 401

### Requirement: Service token enforcement is covered by each service's end-to-end suite

The service token rule SHALL be proved once in the `ascend-python-common` library (REST, MCP and the fail-fast posture), by one wiring test per Python service, and by the filter test and a start-up posture test of ascend-weather-mcp, with no throwaway container and no token spec of its own per service (owner answer 91.3 of 2026-10-08). Every existing spec of the suites of AscendMemory, ascend-ocr, ascend-audio-scribe, ascend-web-hunter and ascend-weather-mcp SHALL send the service token, so each suite run against the live stack shows that the running service demands it.

#### Scenario: Tokenless calls are refused and change nothing

- **WHEN** a service's wiring test calls a REST route and `/mcp` without a token and with a wrong token
- **THEN** each call answers 401
- **AND** the persisted state the call would change (Qdrant points, job records, transcript files, session keys) is unchanged

#### Scenario: Health stays open in the live stack

- **WHEN** a wiring test calls `/health` without a token
- **THEN** the answer is 200

#### Scenario: A service refuses to boot open

- **WHEN** the library's posture test or the weather start-up test runs with the compose posture signalled and no `SERVICE_AUTH_TOKEN`
- **THEN** the service fails to start before it serves a request

#### Scenario: A suite run without the token fails

- **WHEN** a service suite runs against the live stack with `SERVICE_AUTH_TOKEN` unset
- **THEN** its first protected request answers 401
