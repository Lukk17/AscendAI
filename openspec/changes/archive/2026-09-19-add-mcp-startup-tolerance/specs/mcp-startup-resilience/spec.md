## ADDED Requirements

### Requirement: Context refresh survives unreachable MCP servers

The ascend-ai-agent application context SHALL complete `refresh()` and serve traffic on
`POST /api/v1/ai/prompt` regardless of how many of the configured
`spring.ai.mcp.client.streamable-http.connections` are unreachable at startup. A connection refused, a stalled
handshake, or any other initialisation failure on one or more MCP clients MUST NOT propagate as a
`BeanInstantiationException`, `UnsatisfiedDependencyException`, or any other fatal context-refresh exception.

#### Scenario: All configured MCP servers are reachable

- **WHEN** ascend-ai-agent starts with every configured `streamable-http` connection backed by a running MCP server
- **THEN** the Spring context refreshes successfully
- **AND** `POST /api/v1/ai/prompt` returns HTTP 200
- **AND** the readiness banner reports every MCP server with `[Connected]`

#### Scenario: One configured MCP server is unreachable

- **WHEN** ascend-ai-agent starts with one of the configured MCP servers down (TCP connection refused)
- **THEN** the Spring context refreshes successfully
- **AND** `POST /api/v1/ai/prompt` returns HTTP 200
- **AND** the readiness banner reports the down server with `[FAILED]` and the others with `[Connected]`

#### Scenario: All configured MCP servers are unreachable

- **WHEN** ascend-ai-agent starts with every configured MCP server down
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
NOT appear in `getToolCallbacks()`. The filtered provider SHALL be the only `ToolCallbackProvider` bean in the
application context, so no injection point can reach an unfiltered view of the MCP tool set.

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

#### Scenario: No unfiltered provider is reachable from the context

- **WHEN** the Spring context has refreshed with the MCP client enabled
- **THEN** the only `ToolCallbackProvider` bean is the filtered wrapper
- **AND** no `SyncMcpToolCallbackProvider` or `AsyncMcpToolCallbackProvider` bean is registered
- **AND** an injection point that collects `List<ToolCallbackProvider>` therefore sees only the filtered view

### Requirement: A session that goes stale after startup is reconnected once, then demoted

A client recorded `CONNECTED` at startup whose MCP session the server has since forgotten SHALL be reconnected once
per request before its tools are excluded. The reconnect SHALL be serialised per client and bounded by the same
`app.mcp.startup.init-timeout` used at boot. A client whose reconnect fails, or whose discovery still fails after
the reconnect, SHALL be recorded `FAILED` in the `McpClientStatusRegistry`.

#### Scenario: Stale session recovers on the retry

- **GIVEN** a `CONNECTED` client whose first `listTools()` call fails with a stale-session error
- **WHEN** `getToolCallbacks()` runs
- **THEN** the client is reconnected once and its tools are returned from the retry
- **AND** the client stays `CONNECTED` in the registry

#### Scenario: Stale session does not recover

- **GIVEN** a `CONNECTED` client whose reconnect fails, or whose retry after the reconnect fails
- **WHEN** `getToolCallbacks()` runs
- **THEN** that client's tools are excluded from the returned array
- **AND** the client is recorded `FAILED`, so later requests no longer attempt discovery against it
- **AND** the tools of every other `CONNECTED` client are still returned

#### Scenario: Two concurrent requests hit the same stale client

- **GIVEN** a `CONNECTED` client whose session has gone stale
- **WHEN** two requests call `getToolCallbacks()` at the same time
- **THEN** `initialize()` is called on that client exactly once
- **AND** both requests receive the client's tools

### Requirement: Readiness banner renders per-server MCP status

The readiness-log banner emitted by `StartupLogConfig` on
`AvailabilityChangeEvent<ReadinessState.ACCEPTING_TRAFFIC>` SHALL contain an `MCP servers:` section with one line
per configured `streamable-http` connection, followed by one `Aggregate: N/M connected` counter line. Each
per-connection line MUST follow the format `<connection-name>: <url> [Connected | FAILED]`, with the connection
name padded to a common width so the URL column aligns, and with the 4-space / 6-space indentation defined in
[coding-standards](../../../../../.agents/skills/coding-standards/SKILL.md). The exception detail of failed clients
MUST NOT appear in the banner.

#### Scenario: Banner with mixed states

- **GIVEN** three configured connections, two `CONNECTED` and one `FAILED`
- **WHEN** the readiness banner is emitted
- **THEN** the banner contains exactly three per-connection lines under `MCP servers:`, one per connection, followed
  by a single `Aggregate: N/M connected` counter line
- **AND** the two reachable connections show `[Connected]`
- **AND** the unreachable connection shows `[FAILED]`
- **AND** the URL column is aligned across the per-connection lines
- **AND** the connection-refused stack trace is logged at `DEBUG` level only, not in the banner

#### Scenario: Banner contains no MCP-tools summary line

- **WHEN** the readiness banner is emitted
- **THEN** the old single-line `MCP tools: [Connected] N tools: [...]` summary is absent
- **AND** the per-server section is the authoritative view of MCP integration state

### Requirement: Configuration uses Spring AI's built-in deferral flag

The application SHALL set `spring.ai.mcp.client.initialized=false` and
`spring.ai.mcp.client.toolcallback.enabled=false` in
[application.yaml](../../../../../apps/ascend-agent/src/main/resources/application.yaml). The project MUST NOT replace,
override, or fork Spring AI's `McpClientAutoConfiguration` or the `SyncMcpToolCallbackProvider` class. Switching off
`McpToolCallbackAutoConfiguration` through its own documented property is the supported way to keep the unfiltered
provider bean out of the context.

#### Scenario: Spring AI version upgrade within the 1.1.x line

- **GIVEN** the project upgrades from Spring AI 1.1.5 to a later 1.1.x patch
- **WHEN** the new patch ships
- **THEN** the change requires no code edits to ascend-ai-agent's MCP integration
- **AND** the `initialized=false` flag continues to defer auto-config-driven init

#### Scenario: Auto-built MCP clients still construct normally

- **WHEN** the Spring context refreshes with `initialized=false`
- **THEN** `McpClientAutoConfiguration` constructs every configured `McpSyncClient`
- **AND** the transport, sampling, roots, and request-timeout on each client match the project's YAML config
- **AND** no `McpSyncClient.initialize()` call is made by the auto-config factory
- **AND** no auto-configured `SyncMcpToolCallbackProvider` bean is created

### Requirement: The startup loop cannot fail the application start

The `ApplicationReadyEvent` listener that drives per-client initialisation SHALL NOT propagate any exception. Every
per-client step, including connection-name resolution and URL resolution, SHALL sit inside the per-client
try/catch.

#### Scenario: A client cannot even report its own identity

- **GIVEN** a configured MCP client whose `getClientInfo()` call throws
- **WHEN** the startup loop runs
- **THEN** the application start completes
- **AND** that client is recorded `FAILED` under a distinct placeholder name with an `unknown` URL
- **AND** the remaining clients are still initialised
