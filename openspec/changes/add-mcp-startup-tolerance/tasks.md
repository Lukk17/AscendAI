## 1. Configuration

- [ ] 1.1 Add `spring.ai.mcp.client.initialized: false` to `AscendAgent/src/main/resources/application.yaml`,
      with an inline-rationale comment (or ADR pointer) explaining the deferred-init contract.
- [ ] 1.2 Add a new `app.mcp.startup.init-timeout` property (default `5s`) to `application.yaml`, with sibling
      property bound through a `@ConfigurationProperties("app.mcp.startup") McpStartupProperties` record.

## 2. Status registry

- [ ] 2.1 Create `com.lukk.ascend.ai.agent.config.mcp.McpClientStatus` enum: `CONNECTED`, `FAILED`, `DISABLED`.
- [ ] 2.2 Create `com.lukk.ascend.ai.agent.config.mcp.McpClientEntry` record:
      `(String name, String url, McpClientStatus status)`. Used by the registry and the banner section.
- [ ] 2.3 Create `com.lukk.ascend.ai.agent.config.mcp.McpClientStatusRegistry` (`@Component`, thread-safe map
      backed by `ConcurrentHashMap<String, McpClientEntry>`). Public surface: `record(String name, String url,
      McpClientStatus, Throwable cause)`, `Collection<McpClientEntry> entries()`, `Set<String> connectedNames()`.

## 3. Startup initialiser

- [ ] 3.1 Create `com.lukk.ascend.ai.agent.config.mcp.McpClientStartupInitializer` (`@Component`).
- [ ] 3.2 Constructor-inject `List<McpSyncClient>`, `McpClientStatusRegistry`, `McpStartupProperties`, the
      streamable-http connection map from Spring AI's `McpClientCommonProperties` (or directly from
      `Environment` if the properties class isn't autowire-friendly).
- [ ] 3.3 `@EventListener(ApplicationReadyEvent.class) public void initialize()`. For each client: resolve its
      configured URL (by name lookup against the connection map), call `client.initialize()` wrapped in
      `Mono.fromRunnable(() -> client.initialize()).timeout(initTimeout).subscribe(...)` or equivalent
      synchronous helper. On success, `registry.record(name, url, CONNECTED, null)`. On any `Exception` or
      `TimeoutException`, `registry.record(name, url, FAILED, cause)` and `log.warn(...)` with the cause attached
      as DEBUG-only detail (`log.debug("MCP {} init failed", name, cause)`).
- [ ] 3.4 Ensure the initialiser fires **before** `StartupLogConfig.onReadinessChange(...)`. Use `@Order` or rely
      on the fact that `ApplicationReadyEvent` precedes `AvailabilityChangeEvent<ACCEPTING_TRAFFIC>` in Spring's
      lifecycle. Verify with a `@SpyBean` test that registry is populated before banner emits.

## 4. Tool callback filtering

- [ ] 4.1 Create `com.lukk.ascend.ai.agent.config.mcp.FilteredToolCallbackProvider` implementing
      `ToolCallbackProvider`. Constructor takes `SyncMcpToolCallbackProvider delegate` and `McpClientStatusRegistry registry`.
- [ ] 4.2 Implement `ToolCallback[] getToolCallbacks()`. Delegate to the wrapped provider, then filter the array
      to keep only callbacks whose owning client name (extracted from the callback's metadata) is in
      `registry.connectedNames()`. Document the metadata-lookup approach (Spring AI exposes the client name on
      `SyncMcpToolCallback` via `getToolDefinition()` or a transport-level accessor; verify the exact API in
      Spring AI 1.1.5 and pin the lookup).
- [ ] 4.3 Expose the filtered provider as `@Bean @Primary` so `ChatExecutor`'s
      `@Autowired ToolCallbackProvider` autowires the filtered instance.

## 5. Readiness banner update

- [ ] 5.1 Inject `McpClientStatusRegistry` into `StartupLogConfig`.
- [ ] 5.2 Replace the existing `MCP tools:` single-line summary with a new `MCP servers:` multi-section. For each
      entry in `registry.entries()`: `      <padded-name>: <url> [Connected]` or `[FAILED]`. Names padded to a
      common width (e.g. 16 chars) so the URLs align vertically. Indentation: 6 spaces (per
      [coding-standards](../../../.agents/skills/coding-standards/SKILL.md) "keys 3-indented", which means 6
      spaces from column 0 inside the 4-space-indented `MCP servers:` section).
- [ ] 5.3 Add a single aggregate counter line `      Aggregate: N/M connected` at the bottom of the section, as
      a small UX nicety. (Re-evaluate at code review; drop if it duplicates information.)

## 6. Tests

- [ ] 6.1 Write `McpStartupToleranceIT` under
      `AscendAgent/src/test/java/com/lukk/ascend/ai/agent/integration/`. Use Testcontainers OR an in-process
      `McpSyncServer` via Spring AI's own builder bound to an ephemeral port for the "reachable" connection.
      For the "unreachable" connection, point at `http://localhost:1` (always refused).
- [ ] 6.2 Assert: context refreshes with 0 failures, registry has one `CONNECTED` and one `FAILED`,
      `ToolCallbackProvider.getToolCallbacks()` returns only the reachable server's tools, `POST /api/v1/ai/prompt`
      with `provider=lmstudio` returns 200 (mock LM Studio via `@MockitoBean`).
- [ ] 6.3 Add a scenario to `StartupBannerIT` asserting the `MCP servers:` section appears with the expected
      4-space / 6-space indentation, both `[Connected]` and `[FAILED]` markers, and the `Aggregate: N/M` line if
      kept.
- [ ] 6.4 Add a scenario asserting per-client init timeout: configure `app.mcp.startup.init-timeout=200ms`,
      point an MCP at a port that accepts the TCP connection but never replies. Assert the client is recorded
      `FAILED` and startup wall-clock added by this client is `≤ 1s`.

## 7. Documentation

- [ ] 7.1 Update `AscendAgent/docs/architecture/arc42/08-crosscutting-concepts.md` "Model Context Protocol (MCP)"
      section: add a "Startup tolerance" subsection describing the `initialized=false` + initialiser-loop pattern,
      and how to read the readiness-banner `MCP servers:` section.
- [ ] 7.2 Create `AscendAgent/docs/architecture/decisions/ADR-008-mcp-startup-tolerance.md` recording the
      decision (built-in flag + small runner vs. custom client builder), the trade-offs, and pointers to the
      OpenSpec change `add-mcp-startup-tolerance` and the upstream Spring AI MCP Security "known limitation" note.
- [ ] 7.3 Update `AscendAgent/README.md` "Operational Workflow" or "Configuration" section to mention the
      tolerance behaviour and the `app.mcp.startup.init-timeout` knob.
- [ ] 7.4 Add the new ADR to
      [docs/architecture/decisions/README.md](../../../docs/architecture/decisions/README.md) AscendAgent ADR list
      and to `AscendAgent/docs/architecture/arc42/09-architecture-decisions.md`.

## 8. Verification

- [ ] 8.1 Manual smoke test: start AscendAgent with `audioscribe` MCP shut down, observe banner shows
      `[FAILED]` for it and `[Connected]` for the others, prompt endpoint serves a request that doesn't need
      audio transcription successfully.
- [ ] 8.2 Manual smoke test: start AscendAgent with all MCPs up, observe banner shows `[Connected]` for all
      three, prompt endpoint behaviour is unchanged from current happy path.
- [ ] 8.3 Run `./gradlew test integrationTest`. All green.
- [ ] 8.4 Run `/code-reviewer` skill on the diff before opening a PR.
