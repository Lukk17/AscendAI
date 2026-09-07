# ADR-008: MCP Startup Tolerance

**Status:** Accepted

**Date:** 2026-06-15

**OpenSpec change:** `openspec/changes/add-mcp-startup-tolerance`

---

## Context

AscendAgent configures three MCP servers (AudioScribe, WeatherMCP, ascend-web-hunter) via
`spring.ai.mcp.client.streamable-http.connections`. Spring AI 1.1.5's `McpClientAutoConfiguration` calls
`McpSyncClient.initialize()` on every configured client during context refresh. If any server is unreachable at
startup, the entire Spring context fails to refresh, taking the whole API gateway offline for a peripheral
dependency.

Spring AI's own MCP Security documentation calls out this initialise-at-startup behaviour as a "known limitation
requiring workarounds for user-based authentication." No `failure-tolerance` flag exists in either 1.1.x or 2.0.x.

## Decision

Use Spring AI's built-in `spring.ai.mcp.client.initialized=false` deferral flag combined with a small
`McpClientStartupInitializer` component that performs the initialisation loop after the context refreshes.

This was chosen over the alternative of replacing the `mcpSyncClients` bean entirely with a custom implementation
that wraps `McpClientAutoConfiguration`'s transport-building internals. Replacing the bean would require reproducing
Spring AI's internal `McpClient.sync(transport).build()` logic including `WebClientStreamableHttpTransport`
construction, per-connection request timeout, name/version metadata, sampling and roots config, and
`WebClient.Builder` propagation. That approach binds the project to Spring AI's exact 1.1.5 class layout and makes
future minor-version upgrades risky.

## Tool callback filtering

`SyncMcpToolCallbackProvider.getToolCallbacks()` calls `mcpClient.listTools()` on all injected clients. Uninitialised
clients throw `IllegalStateException` when `listTools()` is called. The `FilteredToolCallbackProvider` component
(`@Primary`) holds the full `List<McpSyncClient>` and the `McpClientStatusRegistry`. At `getToolCallbacks()` time it
builds a fresh `SyncMcpToolCallbackProvider` over only the `CONNECTED` clients.

This client-list filter approach avoids a fragile callback-to-client reverse lookup. The Spring AI 1.1.5
`SyncMcpToolCallback` class does not expose its owning client publicly; any reverse lookup would require reflection
or reliance on the tool-name format, both of which are brittle across Spring AI versions.

The `McpSyncClient.getClientInfo()` method returns `McpSchema.Implementation`, whose `title()` field contains the
bare connection name as set by `McpClientAutoConfiguration.connectedClientName()`. The connection name is
`"<spring.ai.mcp.client.name> - <connectionKey>"` as the `name()` field and the bare `<connectionKey>` as
`title()`. The `FilteredToolCallbackProvider` and `McpClientStartupInitializer` both use `getClientInfo().title()`
as the lookup key against `McpStreamableHttpClientProperties.getConnections()`.

## Per-client init timeout

The MCP handshake is a single JSON-RPC `initialize` round-trip. The per-client init timeout defaults to `5s`
(configurable via `app.mcp.startup.init-timeout`). This is longer than the 2-second general dependency-probe
timeout defined in `coding-standards` because the MCP handshake is heavier than a TCP connect probe. The
`request-timeout: 300s` value remains unchanged for tool calls (some MCP tools do long-running work like
transcription).

## Consequences

- The Spring context refreshes successfully regardless of MCP server availability at boot time.
- The readiness banner changes from a single `MCP tools:` line to a multi-line `MCP servers:` section. Log-parsing
  tooling that expected the old format needs updating.
- An MCP server that is unreachable at startup requires an agent restart to become available; there is no automatic
  retry (deferred to a future change).
- Operators can raise `app.mcp.startup.init-timeout` if a healthy server triggers a false-negative due to cold-start
  latency.
