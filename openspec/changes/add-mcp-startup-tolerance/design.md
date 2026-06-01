## Context

AscendAgent's `application.yaml` currently configures three MCP servers (`audioscribe`, `weather`,
`ascend-web-search`) under `spring.ai.mcp.client.streamable-http.connections`. Spring AI's
`McpClientAutoConfiguration` reads this map and produces a `List<McpSyncClient>` bean. As part of that factory
method, it iterates the list and calls `.initialize()` on each client, which performs the MCP `initialize` JSON-RPC
handshake. The handshake is implemented as a reactive WebClient call with a `request-timeout` of 300s (current
config). If a configured connection is refused at the TCP layer (typical case: the MCP service hasn't started yet,
or is permanently disabled in the user's local setup), the handshake fails fast with
`WebClientRequestException: Connection refused`, the factory method throws, and the whole
`AnnotationConfigServletWebServerApplicationContext` refresh aborts.

The downstream blast radius is large: `chatExecutor` depends on `mcpToolCallbacks`, `mcpToolCallbacks` depends on
`mcpSyncClients`, `ascendChatService` depends on `chatExecutor`, `promptController` depends on `ascendChatService`.
One unreachable MCP server (which is a peripheral capability, not a required dependency of the agent's core
function) takes the whole API gateway offline.

Spring AI 1.1.5 (the project's current version) and 2.0.0-m6 (latest milestone) both target Spring Boot 3.4 / 3.5.
Spring Boot 4 has no compatible Spring AI yet, so a version-upgrade-driven solution is not available. The
`spring.ai.mcp.client.initialized` property (default `true`) is the closest built-in lever Spring AI ships: when
set to `false`, the auto-config builds the `McpSyncClient` beans without calling `.initialize()` on them. Tool
discovery on uninitialized clients then has to be done explicitly by the application.

Spring AI's MCP Security docs explicitly call out this initialise-at-startup behaviour as a "known limitation
requiring workarounds for user-based authentication". No `failure-tolerance` flag is shipped by either 1.1.x or
2.0.x. The decision is therefore: use the built-in `initialized=false` flag (avoiding a full custom client
builder), then add the smallest amount of project code that handles the per-client initialise loop, status
tracking, and tool-callback filtering.

## Goals / Non-Goals

**Goals:**

- The Spring context refreshes successfully when zero, some, or all configured MCP servers are unreachable.
- The agent advertises tools from MCP clients that **did** initialise; uninitialised clients are invisible to the
  LLM (their tools are never proposed, so the LLM cannot select them and fail).
- The readiness-log banner shows one line per configured MCP server with its current state
  (`[Connected]` / `[FAILED]`), so the operator can see at a glance which MCP integrations are live and which are
  not.
- The per-client failure detail (the `WebClientRequestException` chain) lands at `DEBUG`, not in the banner, per
  the [coding-standards](../../../.agents/skills/coding-standards/SKILL.md) startup-readiness convention.
- Startup latency on the unhappy path is bounded. An unreachable MCP server must not stall startup for the full
  `request-timeout` (currently 300s).

**Non-Goals:**

- Automatic retry of failed clients during the lifetime of the JVM.
- Runtime re-initialisation when a previously-failed MCP server becomes reachable. (Operator restarts the agent.)
- Surfacing per-client status over a management endpoint (e.g. `/actuator/mcp`). Banner-only for this change.
- Upgrading Spring AI beyond 1.1.5 or migrating to Spring Boot 4.
- Filing an upstream PR or issue with Spring AI. Tracked separately if we want it.

## Decisions

### Decision 1: use `spring.ai.mcp.client.initialized=false` instead of replacing `mcpSyncClients`

**Chosen approach.** Flip the Spring AI property so the auto-configured factory still constructs `McpSyncClient`
instances (transport, sampling, roots, request-timeout) but does NOT call `.initialize()` on them. Our code then
performs the initialise loop, with try/catch per client.

**Alternative considered: replace the `mcpSyncClients` bean entirely.** Would have required reproducing Spring
AI's internal `McpClient.sync(transport).build()` logic, including transport construction
(`WebClientStreamableHttpTransport`), per-connection request timeout, name/version metadata, sampling and roots
config, and `WebClient.Builder` propagation. Rejected because: (a) the user explicitly rejected the "custom
handler" approach; (b) reproducing the auto-config's internals binds us to Spring AI's exact 1.1.5 class layout,
making future minor-version upgrades risky; (c) the `initialized=false` flag is the upstream-supported escape
hatch and exists for exactly this use case.

### Decision 2: trigger the initialise loop on `ApplicationReadyEvent`, not in a `@PostConstruct`

The initialise loop runs in `McpClientStartupInitializer.onApplicationReady(...)` (an
`@EventListener` for `ApplicationReadyEvent`). This places it after Spring's full context refresh, so a failure in
the loop cannot poison bean instantiation. It also fires **before**
`AvailabilityChangeEvent<ReadinessState.ACCEPTING_TRAFFIC>`, which is the event `StartupLogConfig` listens for to
emit the readiness banner. So by the time the banner renders, the registry is populated.

**Alternative: `@PostConstruct` on a `@Configuration` class.** Rejected because `@PostConstruct` runs during bean
construction; a network probe inside `@PostConstruct` blocks the entire context-refresh thread, defeating the
point of moving init out of the auto-config factory.

**Alternative: `CommandLineRunner`.** Functionally equivalent to the `ApplicationReadyEvent` listener for this
use case. We pick `ApplicationReadyEvent` because the readiness-banner emitter is already an event listener; the
two then live in the same idiomatic Spring lifecycle.

### Decision 3: per-client init timeout of 5 seconds

The MCP handshake is a single JSON-RPC `initialize` round-trip. A reasonable healthy server replies in under 100 ms.
We pick **5 seconds** as the per-client init timeout: long enough to ride out a slow handshake from a healthy
server under load, short enough that a refused connection adds at most 5 s per failed MCP to startup wall-clock.

With three configured MCPs all down, worst-case added startup time is 15 s. The current behaviour (whole context
fails after `request-timeout = 300s` worth of retries) is strictly worse.

The `spring.ai.mcp.client.request-timeout: 300s` stays as configured for **tool calls** (some MCP tools do
long-running work like transcription; a 5 s tool timeout is too aggressive). Only the per-client init handshake
gets the shorter ceiling, implemented via `Mono.timeout(Duration.ofSeconds(5))` around the `client.initialize()`
call.

**Alternative: 2 seconds (matches the `coding-standards` skill's general dependency-probe timeout).** Rejected
because the MCP handshake is heavier than a TCP-connect probe (full JSON-RPC negotiation), and 2 s is on the edge
for a cold-started container.

**Alternative: reuse `request-timeout`.** Rejected. 300 s on a refused localhost connection is unbearable.

### Decision 4: filter tool callbacks via a wrapper bean, not via per-callback null-checks

The advertised tool set must be a function of the initialised-client set. Spring AI's `SyncMcpToolCallbackProvider`
takes `List<McpSyncClient>` and returns tool callbacks from all of them, including uninitialised clients (which
would throw `IllegalStateException` on first tool call).

The fix: wrap `SyncMcpToolCallbackProvider` with a `FilteredToolCallbackProvider` (`@Primary` bean) that asks the
`McpClientStatusRegistry` for the set of `CONNECTED` clients and only delegates to those. The auto-built provider
stays in the context; the wrapper masks the broken slice.

**Alternative: filter inside `ChatExecutor`.** Pushes the responsibility downstream and into the request hot
path. The auto-build-then-filter pattern keeps the static tool-discovery surface honest at startup time, which is
where it belongs.

### Decision 5: registry holds connection state as an immutable enum, no timestamps

`McpClientStatus { CONNECTED, FAILED, DISABLED }`. No `lastAttemptAt`, no retry counter. Banner shows
`[Connected]` or `[FAILED]` only, matching the `coding-standards` skill format
(`<url> [Connected | Warning (status=N) | FAILED]`). When operators need detail, they look at the DEBUG log entry
the initialiser emits on failure.

### Decision 6: configuration shape stays the same

No new `spring.ai.mcp.client.*` properties beyond toggling `initialized`. Connection names, URLs, and request
timeouts continue to live where they already do. Operators don't have to re-learn a new layout.

## Risks / Trade-offs

- **Risk: an MCP server is reachable but its `initialize` handshake stalls past 5 s.** A genuinely slow but
  healthy server gets marked `FAILED`. Mitigation: the 5 s timeout is configurable via a new property
  `app.mcp.startup.init-timeout` (defaulting to 5 s). If operators see false negatives, they raise it.
- **Risk: tools call paths assume the tool exists.** If `ChatExecutor` passes a tool name from a now-uninitialised
  client to the LLM, the LLM would request a tool the provider doesn't advertise. Mitigation: `ChatExecutor` only
  pulls the advertised set from `ToolCallbackProvider.getToolCallbacks()` at request time, which is already
  filtered. No code path assumes a static tool catalogue.
- **Risk: the readiness banner contract changes (`MCP tools:` single line → `MCP servers:` multi-section).** Any
  log-parsing tooling needs to be updated. Mitigation: documented in the ADR. Today's value of the old line is
  already low (just a comma-separated tool name list); the new section carries strictly more information.
- **Risk: integration test brittleness.** Spinning up a fake MCP server in Testcontainers requires either a Java
  in-memory `McpSyncServer` or a real MCP server image. Mitigation: the integration test can use Spring AI's own
  `McpSyncServer.sync(...)` builder in a `@TestConfiguration` and bind it to a free port; no external Docker image
  needed.
- **Trade-off: `initialized=false` is project-wide.** A non-MCP-tolerant deployment can't opt back into the
  upstream "fail-fast on init" behaviour without changing the YAML. Acceptable; the new behaviour is strictly
  more useful.

## Migration Plan

1. Land the new code + config change on the existing branch
   `feat/agent-deploy-chat-history-caching-rag-attachments`. No DB migration, no data model change.
2. Build + start AscendAgent locally with one MCP server intentionally shut down. Confirm: context refreshes,
   readiness banner shows the missing server with `[FAILED]`, prompt endpoint responds, the LLM can call tools
   from the surviving MCPs.
3. Restart with all MCP servers up. Confirm: banner shows all `[Connected]`, full tool set advertised, behaviour
   unchanged from today's happy path.
4. Rollback path: revert the single `initialized: false` line in `application.yaml` and disable the new
   `McpClientStartupInitializer` via Spring profile, or revert the whole branch. No state to migrate back.

## Open Questions

- (Resolved during this design) Should the per-init timeout be 2 s, 5 s, or `request-timeout`? **Chose 5 s with a
  property override.**
- (Resolved during this design) Wrapper bean vs. patching the auto-config provider? **Chose `@Primary` wrapper.**
- (Still open) Should `McpClientStatusRegistry` be exposed via `/actuator/mcp` so a downstream health probe can
  read it? **Punted to a follow-up change** — the readiness banner covers the operator-visibility ask for now.
- (Still open) Should there be a single `Connection` aggregate state on the banner ("MCP: 2/3 connected") in
  addition to per-server lines? **Punted** — the per-server lines are the authoritative view; aggregate is a UX
  nicety, easy to add later.
