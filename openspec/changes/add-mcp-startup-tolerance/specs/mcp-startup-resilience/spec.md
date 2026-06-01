## ADDED Requirements

### Requirement: Context refresh survives unreachable MCP servers

The AscendAgent application context SHALL complete `refresh()` and serve traffic on
`POST /api/v1/ai/prompt` regardless of how many of the configured
`spring.ai.mcp.client.streamable-http.connections` are unreachable at startup. A connection refused, a stalled
handshake, or any other initialisation failure on one or more MCP clients MUST NOT propagate as a
`BeanInstantiationException`, `UnsatisfiedDependencyException`, or any other fatal context-refresh exception.

#### Scenario: All configured MCP servers are reachable

- **WHEN** AscendAgent starts with every configured `streamable-http` connection backed by a running MCP server
- **THEN** the Spring context refreshes successfully
- **AND** `POST /api/v1/ai/prompt` returns HTTP 200
- **AND** the readiness banner reports every MCP server with `[Connected]`

#### Scenario: One configured MCP server is unreachable

- **WHEN** AscendAgent starts with one of the configured MCP servers down (TCP connection refused)
- **THEN** the Spring context refreshes successfully
- **AND** `POST /api/v1/ai/prompt` returns HTTP 200
- **AND** the readiness banner reports the down server with `[FAILED]` and the others with `[Connected]`

#### Scenario: All configured MCP servers are unreachable

- **WHEN** AscendAgent starts with every configured MCP server down
- **THEN** the Spring context refreshes successfully
- **AND** `POST /api/v1/ai/prompt` returns HTTP 200
- **AND** the readiness banner reports every MCP server with `[FAILED]`
- **AND** no MCP tool callbacks are advertised to the LLM

### Requirement: Per-client initialisation is bounded by a 5-second timeout

Each `McpSyncClient.initialize()` call performed by the startup runner SHALL be bounded by a per-client timeout,
default 5 seconds, configurable via the `app.mcp.startup.init-timeout` property. An initialise call that exceeds
the timeout SHALL be cancelled and the client recorded as `FAILED`.

#### Scenario: Healthy MCP server returns within timeout

- **WHEN** an MCP server's `initialize` handshake completes within 5 seconds
- **THEN** the client is recorded as `CONNECTED`
- **AND** its tools are advertised through the `ToolCallbackProvider`

#### Scenario: Slow or stalled MCP server exceeds timeout

- **WHEN** an MCP server's `initialize` handshake exceeds the configured `app.mcp.startup.init-timeout`
- **THEN** the initialise call is cancelled
- **AND** the client is recorded as `FAILED`
- **AND** total startup wall-clock time added by this client is at most the configured timeout value

#### Scenario: Timeout is operator-overridable

- **WHEN** the operator sets `app.mcp.startup.init-timeout=15s` and restarts
- **THEN** the per-client init handshake is allowed up to 15 seconds before cancellation
- **AND** the `spring.ai.mcp.client.request-timeout` value (used for tool calls) is unchanged

### Requirement: Tool callback provider filters by initialised-client state

The `ToolCallbackProvider` consumed by `ChatExecutor` SHALL only advertise callbacks whose owning `McpSyncClient`
is in `CONNECTED` state in the `McpClientStatusRegistry`. Tool callbacks from uninitialised or failed clients MUST
NOT appear in `getToolCallbacks()`.

#### Scenario: Mixed client states

- **GIVEN** two configured MCP servers, one in `CONNECTED` state and one in `FAILED` state
- **WHEN** `ChatExecutor` calls `toolCallbackProvider.getToolCallbacks()`
- **THEN** only the tool callbacks owned by the `CONNECTED` client are returned
- **AND** the LLM never receives a tool definition that would route to the `FAILED` client

#### Scenario: All clients failed

- **GIVEN** every configured MCP server is in `FAILED` state
- **WHEN** `ChatExecutor` calls `toolCallbackProvider.getToolCallbacks()`
- **THEN** an empty array is returned
- **AND** the LLM is invoked without any MCP tools

### Requirement: Readiness banner renders per-server MCP status

The readiness-log banner emitted by `StartupLogConfig` on
`AvailabilityChangeEvent<ReadinessState.ACCEPTING_TRAFFIC>` SHALL contain an `MCP servers:` section with one line
per configured `streamable-http` connection. Each line MUST follow the format
`<connection-name>: <url> [Connected | FAILED]` with the 4-space / 6-space indentation defined in
[coding-standards](../../../.agents/skills/coding-standards/SKILL.md). The exception detail of failed clients
MUST NOT appear in the banner.

#### Scenario: Banner with mixed states

- **GIVEN** three configured connections, two `CONNECTED` and one `FAILED`
- **WHEN** the readiness banner is emitted
- **THEN** the banner contains exactly three lines under `MCP servers:`, one per connection
- **AND** the two reachable connections show `[Connected]`
- **AND** the unreachable connection shows `[FAILED]`
- **AND** the connection-refused stack trace is logged at `DEBUG` level only, not in the banner

#### Scenario: Banner contains no MCP-tools summary line

- **WHEN** the readiness banner is emitted
- **THEN** the old single-line `MCP tools: [Connected] N tools: [...]` summary is absent
- **AND** the per-server section is the authoritative view of MCP integration state

### Requirement: Configuration uses Spring AI's built-in deferral flag

The application SHALL set `spring.ai.mcp.client.initialized=false` in
[application.yaml](../../../AscendAgent/src/main/resources/application.yaml). The project MUST NOT replace,
override, or fork Spring AI's `McpClientAutoConfiguration` or `SyncMcpToolCallbackProvider` beans.

#### Scenario: Spring AI version upgrade within the 1.1.x line

- **GIVEN** the project upgrades from Spring AI 1.1.5 to a later 1.1.x patch
- **WHEN** the new patch ships
- **THEN** the change requires no code edits to AscendAgent's MCP integration
- **AND** the `initialized=false` flag continues to defer auto-config-driven init

#### Scenario: Auto-built MCP clients still construct normally

- **WHEN** the Spring context refreshes with `initialized=false`
- **THEN** `McpClientAutoConfiguration` constructs every configured `McpSyncClient`
- **AND** the transport, sampling, roots, and request-timeout on each client match the project's YAML config
- **AND** no `McpSyncClient.initialize()` call is made by the auto-config factory
