## Why

ascend-ai-agent currently fails to boot when **any** configured MCP server is unreachable on its first connection
attempt. The `McpClientAutoConfiguration` bean factory calls `McpSyncClient.initialize()` on every configured client
during context refresh; a single `Connection refused` propagates as `BeanInstantiationException` for
`mcpSyncClients`, then `UnsatisfiedDependencyException` for `chatExecutor`, then the entire Spring context fails to
refresh and the process exits.

This contradicts the agent's role as the central orchestrator. The agent should advertise the tools from the MCP
servers that are reachable and degrade gracefully when others are down. The user-side fix is currently to start
every MCP server before ascend-ai-agent, which is fragile in local dev and unworkable in a real deployment.

## What Changes

- Flip `spring.ai.mcp.client.initialized` from its default (`true`) to **`false`** in
  [apps/ascend-agent/src/main/resources/application.yaml](../../../apps/ascend-agent/src/main/resources/application.yaml). Spring
  AI's auto-config still builds the per-connection `McpSyncClient` beans, but it no longer calls `.initialize()` on
  them at context refresh, so an unreachable server can't throw during bean creation.
- Add a new `McpClientStartupInitializer` component (Spring 21+ class in
  `com.lukk.ascend.ai.agent.config.mcp`) that listens for `ApplicationReadyEvent`, iterates the autowired
  `List<McpSyncClient>`, calls `.initialize()` on each one inside a bounded try/catch, and records per-client status
  in a new `McpClientStatusRegistry` bean.
- Add `McpClientStatusRegistry` with one entry per configured connection: `name`, `url`, `state`
  (`CONNECTED | FAILED`). Reads return an immutable snapshot. Failure detail stays out of the registry and is
  logged by the initialiser at `DEBUG`.
- Extend [StartupLogConfig](../../../apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/config/StartupLogConfig.java)
  to render a dedicated `MCP servers:` section in the readiness banner, reading from the registry: one line per
  connection, format `<name>: <url> [Connected | FAILED]`, plus one `Aggregate: N/M connected` counter line.
  Replaces the current single-line `MCP tools:` summary.
- Filter `ToolCallbackProvider` advertised tools to only those from initialized clients. The current
  `SyncMcpToolCallbackProvider` lists tools from every `McpSyncClient` regardless of state; for uninitialized
  clients this throws on first use. The fix is a `@Primary` wrapper bean that discovers tools per `CONNECTED`
  client, plus `spring.ai.mcp.client.toolcallback.enabled: false` so Spring AI's own unfiltered provider bean never
  enters the context and `@Primary` is not the only thing standing between the model and a dead server's tools.
- Recover a session that went stale after boot: one reconnect-and-retry per client per request, serialised per
  client, with a client that still fails demoted to `FAILED` in the registry.
- Document the new behaviour in
  [apps/ascend-agent/docs/architecture/arc42/08-crosscutting-concepts.md](../../../apps/ascend-agent/docs/architecture/arc42/08-crosscutting-concepts.md)
  under "Model Context Protocol (MCP)": startup tolerance is now part of the design, not an emergent property.

Not in scope (deferred to a future change):

- Automatic retry of failed clients on a schedule.
- Runtime re-initialisation when a downed MCP server comes back online.
- Upgrading Spring AI to 2.0 (still milestone, both 1.1.x and 2.0.x target Spring Boot 3.4 / 3.5 — Spring Boot 4 is
  not yet supported by stable Spring AI).
- Filing an upstream issue with Spring AI for a built-in `spring.ai.mcp.client.failure-tolerance` flag.

## Capabilities

### New Capabilities

- `mcp-startup-resilience`: Behaviour for how the agent reacts when configured MCP servers are unreachable at
  startup. Covers the `initialized=false` deferral, the per-client initialisation loop, the status registry, the
  readiness-banner section, and the tool-callback filter.

### Modified Capabilities

(None. No existing capability spec covers MCP integration at the requirement level. The new capability stands on
its own.)

## Impact

**Code**

- `apps/ascend-agent/src/main/resources/application.yaml`: one new property, one removed-default behaviour.
- `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/config/mcp/McpClientStartupInitializer.java`: new file.
- `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/config/mcp/McpClientStatusRegistry.java`: new file.
- `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/config/mcp/FilteredToolCallbackProvider.java`: new file
  (discovers tools per CONNECTED client, filters by status).
- `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/config/mcp/FallbackToolCallbackProvider.java`: new file
  (empty provider when the MCP client is switched off).
- `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/config/mcp/McpConnectionNames.java`: new file
  (connection-name resolution shared by the initialiser and the filtered provider).
- `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/config/properties/McpStartupProperties.java`: new file
  (`app.mcp.startup.init-timeout`).
- `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/config/StartupLogConfig.java`: extend to render the new
  `MCP servers:` section. Keep the rest of the readiness-banner contract intact.

**Tests**

- New unit tests `McpClientStartupInitializerTest`, `McpClientStatusRegistryTest`, `McpConnectionNamesTest`, and
  `FilteredToolCallbackProviderTest`: the init loop, per-client failure isolation, the timeout branch and its
  wall-clock bound, URL resolution, `FAILED` recording, the registry snapshot contract, connection-name resolution,
  and the reconnect path including its per-client serialisation.
- New integration test `McpStartupToleranceIT` under
  `apps/ascend-agent/src/test/java/com/lukk/ascend/ai/agent/integration/`: boots the context with every configured
  connection redirected at an unbound localhost port. Asserts context refresh succeeds, the registry holds one
  entry per connection keyed by the bare connection name and carrying its configured URL, every entry is `FAILED`,
  the filtered provider advertises nothing, the context holds no unfiltered MCP provider bean, and
  `POST /api/v1/ai/prompt` returns 200 with the chat model stubbed.
- New integration test `McpStartupTimeoutIT`: one connection points at a server that accepts the TCP connection and
  never answers, with `app.mcp.startup.init-timeout=200ms`. Asserts the connection was accepted, the client is
  recorded `FAILED`, and no tools are advertised.
- Extend the existing `StartupBannerIT` to assert the real `MCP servers:` line format, the aligned URL column, the
  `Aggregate: N/M connected` line, and the absence of the old `MCP tools:` summary.

**Docs**

- `apps/ascend-agent/docs/architecture/arc42/08-crosscutting-concepts.md`: MCP section gains a "Startup tolerance"
  subsection.
- `apps/ascend-agent/docs/architecture/decisions/`: new ADR `ADR-008-mcp-startup-tolerance.md` recording the decision
  trade-off (config flag + small runner vs. fully custom client builder), since both options were considered.

**Operational**

- No new external dependencies. No new configuration the user must supply (the flag flip is internal).
- Startup latency on the happy path is unchanged (initialisation still happens, just via the explicit runner
  rather than the auto-config). On the unhappy path, startup latency is bounded by the per-client probe timeout
  (see design.md open question about 2 s vs 5 s vs reusing `request-timeout: 300s`).
- The readiness banner shape changes: `MCP tools:` line is replaced by a multi-line `MCP servers:` section. Any
  observability tooling that grep'd the old line needs updating; this is documented in the ADR.

**Relevant skills for implementation**: `/springboot-patterns`, `/java-coding-standards`, `/code-reviewer`,
`/coding-standards` (for the readiness-banner update).
