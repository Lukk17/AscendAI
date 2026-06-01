## Why

AscendAgent currently fails to boot when **any** configured MCP server is unreachable on its first connection
attempt. The `McpClientAutoConfiguration` bean factory calls `McpSyncClient.initialize()` on every configured client
during context refresh; a single `Connection refused` propagates as `BeanInstantiationException` for
`mcpSyncClients`, then `UnsatisfiedDependencyException` for `chatExecutor`, then the entire Spring context fails to
refresh and the process exits.

This contradicts the agent's role as the central orchestrator. The agent should advertise the tools from the MCP
servers that are reachable and degrade gracefully when others are down. The user-side fix is currently to start
every MCP server before AscendAgent, which is fragile in local dev and unworkable in a real deployment.

## What Changes

- Flip `spring.ai.mcp.client.initialized` from its default (`true`) to **`false`** in
  [AscendAgent/src/main/resources/application.yaml](../../../AscendAgent/src/main/resources/application.yaml). Spring
  AI's auto-config still builds the per-connection `McpSyncClient` beans, but it no longer calls `.initialize()` on
  them at context refresh, so an unreachable server can't throw during bean creation.
- Add a new `McpClientStartupInitializer` component (Spring 21+ class in
  `com.lukk.ascend.ai.agent.config.mcp`) that listens for `ApplicationReadyEvent`, iterates the autowired
  `List<McpSyncClient>`, calls `.initialize()` on each one inside a bounded try/catch, and records per-client status
  in a new `McpClientStatusRegistry` bean.
- Add `McpClientStatusRegistry` with one entry per configured connection: `name`, `url`, `state`
  (`CONNECTED | FAILED | DISABLED`), optional `errorMessage` (kept off the banner, available at DEBUG).
- Extend [StartupLogConfig](../../../AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/StartupLogConfig.java)
  to render a dedicated `MCP servers:` section in the readiness banner, reading from the registry: one line per
  connection, format `<name>: <url> [Connected | FAILED]`. Replaces the current single-line `MCP tools:` summary.
- Filter `ToolCallbackProvider` advertised tools to only those from initialized clients. The current
  `SyncMcpToolCallbackProvider` lists tools from every `McpSyncClient` regardless of state; for uninitialized
  clients this throws on first use. The fix is a wrapper bean that delegates to the auto-built provider but skips
  callbacks whose owning client is not in `CONNECTED` state.
- Document the new behaviour in
  [AscendAgent/docs/architecture/arc42/08-crosscutting-concepts.md](../../../AscendAgent/docs/architecture/arc42/08-crosscutting-concepts.md)
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

- `AscendAgent/src/main/resources/application.yaml`: one new property, one removed-default behaviour.
- `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/mcp/McpClientStartupInitializer.java`: new file.
- `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/mcp/McpClientStatusRegistry.java`: new file.
- `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/mcp/FilteredToolCallbackProvider.java`: new file
  (wraps the Spring AI auto-built provider, filters by status).
- `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/StartupLogConfig.java`: extend to render the new
  `MCP servers:` section. Keep the rest of the readiness-banner contract intact.

**Tests**

- New integration test `McpStartupToleranceIT` under
  `AscendAgent/src/test/java/com/lukk/ascend/ai/agent/integration/`: boots context with one valid `streamable-http`
  connection pointing at a Testcontainers-stubbed MCP server and one invalid connection pointing at an unbound
  localhost port. Asserts context refresh succeeds, the registry contains one `CONNECTED` and one `FAILED` entry,
  the `FilteredToolCallbackProvider` advertises only the working client's tools, and the readiness banner emits
  the expected `MCP servers:` section.
- Extend the existing `StartupBannerIT` to assert the new section layout (skill 4-space indent, `[Connected]` /
  `[FAILED]` markers, one URL per line).

**Docs**

- `AscendAgent/docs/architecture/arc42/08-crosscutting-concepts.md`: MCP section gains a "Startup tolerance"
  subsection.
- `AscendAgent/docs/architecture/decisions/`: new ADR `ADR-008-mcp-startup-tolerance.md` recording the decision
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
