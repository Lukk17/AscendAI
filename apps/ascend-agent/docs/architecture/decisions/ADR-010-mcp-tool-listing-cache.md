# ADR-010: Short-Lived Cache of the MCP Tool Listing

## Status

Accepted, 2026-09-24

## Context

`ChatExecutor` builds a `ChatClient` for every prompt and asks the `ToolCallbackProvider` for the tools to advertise. `FilteredToolCallbackProvider` (ADR-008) answered that by calling `listTools()` on every connected MCP server, one network round trip per server, before the model was even called. With three servers configured, every chat request paid three round trips for metadata that almost never changes.

The filter also carries two correctness duties that a cache must not weaken. A server the `McpClientStatusRegistry` reports as `FAILED` must never have a tool advertised to the model, and a stale session found during listing is reconnected once, with the server demoted to `FAILED` if that also fails.

## Decision

`McpToolCallbackCache` holds the last filtered listing and serves it while three things still hold:

1. The set of connected server names read from the registry equals the set the listing was taken for. A server dropping out or reconnecting changes the key, so the next prompt relists and sees the correct tools immediately.
2. No `McpToolsChangedEvent` arrived since the listing started. Spring AI 1.1.5 registers `McpSyncToolsChangeEventEmmiter` on every sync client, which publishes that event when a server sends `notifications/tools/list_changed`. The cache listens for it and drops the entry. An invalidation generation stops a listing that was already in flight from being stored after the notification.
3. The expiry, `app.mcp.tool-cache.ttl`, has not passed. The default is 60 seconds.

A listing during which the connected set changed, for example because the reconnect path demoted a server, is returned to its caller but not stored, so the next prompt lists again under the new set.

The 60 second default was chosen because the compose stack's MCP containers are health-checked every 30 seconds. After a restart, a server is not reported healthy for at least one interval, so 60 seconds (two intervals) keeps tool staleness on the same scale as the stack's own restart detection. A conversation sends a prompt every few seconds to tens of seconds, so the cost falls from three round trips per prompt to three per minute. Setting the property to `0s` turns the cache off and every prompt lists tools, which is the old behaviour.

## Alternatives Considered

### Alternative 1: Keep listing on every prompt

- Pros: always fresh, and the stale-session reconnect runs before every model call.
- Cons: three round trips per prompt, and they are paid before the model can start.
- Why not: the metadata changes on a redeploy, not per request.

### Alternative 2: Cache until a tools-changed notification, with no expiry

- Pros: the fewest round trips.
- Cons: a restarted server gets a new session, and a notification cannot reach the old one. A server redeployed with a different tool set would keep its old tools until the agent restarts.
- Why not: the notification alone cannot cover restarts, so a backstop expiry is required.

### Alternative 3: Use Spring AI's own `SyncMcpToolCallbackProvider` cache

- Pros: already listens for `McpToolsChangedEvent`.
- Cons: it has no expiry and knows nothing about the registry, and ADR-008 deliberately keeps it out of the context so no unfiltered provider can bypass the status filter.
- Why not: it cannot drop a failed server's tools.

## Consequences

### Positive

- A prompt with an unchanged connected set pays no listing round trips until the expiry passes.
- A failed server's tools disappear on the very next prompt, because the registry read comes before every cache lookup.
- `FilteredToolCallbackProvider` stays the only `ToolCallbackProvider` bean. The cache is a collaborator, not a second provider.

### Negative

- The stale-session reconnect in `FilteredToolCallbackProvider` now runs only when a listing happens, meaning on a cache miss. If a server restarts inside the expiry, the model can call a cached tool on the old session. The MCP SDK (0.17.0) discards its session when the server reports it unknown and starts a fresh initialisation, so later calls succeed, but that first tool call returns an error to the model.
- A server redeployed with changed tools and no notification shows the old tool set for up to the expiry.

### Risks

- Concurrent cache misses each list tools, as every prompt did before this change. No regression, but no stampede protection either.

## Related

- `McpToolCallbackCache`, `FilteredToolCallbackProvider`, `McpClientStatusRegistry`
- `McpToolCacheProperties` (`app.mcp.tool-cache.ttl`, default `60s`)
- ADR-008 MCP startup tolerance
