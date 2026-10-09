## MODIFIED Requirements

### Requirement: Tool callback provider filters by initialised-client state

The `ToolCallbackProvider` consumed by `ChatExecutor` SHALL only advertise callbacks whose owning `McpSyncClient`
is in `CONNECTED` state in the `McpClientStatusRegistry`. Tool callbacks from uninitialised or failed clients MUST
NOT appear in `getToolCallbacks()`. A client whose connection belongs to a deployment module that is not active
SHALL get no connection: it SHALL never be initialised, SHALL never be retried, SHALL have no entry in the
`McpClientStatusRegistry`, and its tool callbacks MUST NOT appear in `getToolCallbacks()`. The filtered provider SHALL
be the only `ToolCallbackProvider` bean in the application context, so no injection point can reach an unfiltered
view of the MCP tool set.

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

#### Scenario: Client of an inactive module

- **GIVEN** the `ascend-web-hunter` connection belongs to the module `web-search` and `web-search` is not active
- **WHEN** the startup loop runs and `ChatExecutor` calls `toolCallbackProvider.getToolCallbacks()`
- **THEN** no initialise request is sent to its URL and the registry holds no entry for it
- **AND** no `web_` tool callback is returned

#### Scenario: No unfiltered provider is reachable from the context

- **WHEN** the Spring context has refreshed with the MCP client enabled
- **THEN** the only `ToolCallbackProvider` bean is the filtered wrapper
- **AND** no `SyncMcpToolCallbackProvider` or `AsyncMcpToolCallbackProvider` bean is registered
- **AND** an injection point that collects `List<ToolCallbackProvider>` therefore sees only the filtered view

### Requirement: A session that goes stale after startup is reconnected once, then demoted

A client recorded `CONNECTED` at startup whose MCP session the server has since forgotten SHALL be reconnected once
per request before its tools are excluded. The reconnect SHALL be serialised per client and bounded by the same
`app.mcp.startup.init-timeout` used at boot. A client whose reconnect fails, or whose discovery still fails after
the reconnect, SHALL be recorded `FAILED` in the `McpClientStatusRegistry`. From then on requests SHALL NOT attempt
discovery against it, and only the background retry SHALL try it again.

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
- **AND** the background retry tries it again at its next interval
- **AND** the tools of every other `CONNECTED` client are still returned

#### Scenario: Two concurrent requests hit the same stale client

- **GIVEN** a `CONNECTED` client whose session has gone stale
- **WHEN** two requests call `getToolCallbacks()` at the same time
- **THEN** `initialize()` is called on that client exactly once
- **AND** both requests receive the client's tools

### Requirement: Readiness banner renders per-server MCP status

The readiness-log banner emitted by `StartupLogConfig` on
`AvailabilityChangeEvent<ReadinessState.ACCEPTING_TRAFFIC>` SHALL contain an `MCP servers:` section with one line
per configured `streamable-http` connection of an active deployment module, followed by one
`Aggregate: N/M connected` counter line. Each per-connection line MUST follow the format
`<connection-name>: <url> [Connected | FAILED]`, with the connection name padded to a common width so the URL column
aligns, and with the 4-space / 6-space indentation defined in
[coding-standards](../../../../../.agents/skills/coding-standards/SKILL.md). A connection of a module that is not
active gets no connection, so it MUST NOT have a line in the section and MUST NOT be counted in `M` of the aggregate
line. The `Modules:` block of the same banner shows which modules are active. The exception detail of failed clients
MUST NOT appear in the banner.

#### Scenario: Banner with mixed states

- **GIVEN** three configured connections of active modules, two `CONNECTED` and one `FAILED`
- **WHEN** the readiness banner is emitted
- **THEN** the banner contains exactly three per-connection lines under `MCP servers:`, one per connection, followed
  by a single `Aggregate: N/M connected` counter line
- **AND** the two reachable connections show `[Connected]`
- **AND** the unreachable connection shows `[FAILED]`
- **AND** the URL column is aligned across the per-connection lines
- **AND** the connection-refused stack trace is logged at `DEBUG` level only, not in the banner

#### Scenario: Banner with a connection of an inactive module

- **GIVEN** three configured connections, two `CONNECTED` and one whose module is not active
- **WHEN** the readiness banner is emitted
- **THEN** the banner contains exactly two per-connection lines under `MCP servers:`, both `[Connected]`
- **AND** the aggregate line reads `Aggregate: 2/2 connected`

#### Scenario: Banner contains no MCP-tools summary line

- **WHEN** the readiness banner is emitted
- **THEN** the old single-line `MCP tools: [Connected] N tools: [...]` summary is absent
- **AND** the per-server section is the authoritative view of MCP integration state

## ADDED Requirements

### Requirement: A failed client is retried in the background

A client of an active module recorded `FAILED`, at startup or later, SHALL be retried in the background every
`app.mcp.reconnect.interval` (default 60 seconds). Each attempt SHALL call `initialize()` under the same per-client
gate as the stale-session reconnect and SHALL be bounded by `app.mcp.startup.init-timeout`. A client that answers
SHALL be recorded `CONNECTED`, its tools SHALL be offered from the next request on without a restart, and one INFO
line SHALL name it. A client that does not answer SHALL stay `FAILED` and SHALL write at most one DEBUG line per
attempt. A retry SHALL never block a chat request, SHALL never propagate an exception, and SHALL never fail the
application. This replaces the earlier behaviour in which a `FAILED` client was never tried again.

#### Scenario: Server comes back after startup

- **GIVEN** `ascend-weather-mcp` is down when the agent starts, so its client is recorded `FAILED`
- **WHEN** the server comes up and one retry interval passes
- **THEN** the client is recorded `CONNECTED` and one INFO line names it
- **AND** the next chat request is offered its `weather_` tools

#### Scenario: Server stays down

- **GIVEN** a `FAILED` client whose server stays down
- **WHEN** several retry intervals pass
- **THEN** the client stays `FAILED` and no WARN or ERROR line is written per attempt
- **AND** each attempt ends within `app.mcp.startup.init-timeout`
- **AND** chat requests in the meantime are answered without waiting for the retry

#### Scenario: Client of an inactive module is never retried

- **GIVEN** the `ascend-audio-scribe` connection belongs to the module `audio` and `audio` is not active
- **WHEN** several retry intervals pass
- **THEN** no request is sent to its URL
