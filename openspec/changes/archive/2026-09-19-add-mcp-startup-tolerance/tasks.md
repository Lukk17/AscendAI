## 1. Configuration

- [x] 1.1 Add `spring.ai.mcp.client.initialized: false` to `apps/ascend-agent/src/main/resources/application.yaml`.
      The deferred-init contract is recorded in ADR-008 rather than as an inline comment, since rationale does not
      live in configuration files.
- [x] 1.2 Add a new `app.mcp.startup.init-timeout` property (default `5s`) to `application.yaml`, bound through
      `@ConfigurationProperties("app.mcp.startup") McpStartupProperties`. A Lombok `@Getter`/`@Setter` class rather
      than a record, matching every sibling properties class and Spring's setter binding for a mutable default.

## 2. Status registry

- [x] 2.1 Create `com.lukk.ascend.ai.agent.config.mcp.McpClientStatus` enum: `CONNECTED`, `FAILED`. (`DISABLED`
      was dropped at code review: nothing can ever record it, since a disabled MCP client has no client bean and no
      initialiser.)
- [x] 2.2 Create `com.lukk.ascend.ai.agent.config.mcp.McpClientEntry` record:
      `(String name, String url, McpClientStatus status)`. Used by the registry and the banner section.
- [x] 2.3 Create `com.lukk.ascend.ai.agent.config.mcp.McpClientStatusRegistry` (`@Component`, thread-safe map
      backed by `ConcurrentHashMap<String, McpClientEntry>`). Public surface: `record(String name, String url,
      McpClientStatus)`, `markFailed(String name)`, `Collection<McpClientEntry> entries()` returning an immutable
      snapshot, `Set<String> connectedNames()`. The registry does no logging: the initialiser owns the failure log
      line, so the message can name what actually happened.

## 3. Startup initialiser

- [x] 3.1 Create `com.lukk.ascend.ai.agent.config.mcp.McpClientStartupInitializer` (`@Component`).
- [x] 3.2 Constructor-inject `List<McpSyncClient>`, `McpClientStatusRegistry`, `McpStartupProperties`, and
      Spring AI's `McpStreamableHttpClientProperties` for the connection map.
- [x] 3.3 `@EventListener(ApplicationReadyEvent.class) public void initialize()`. For each client: resolve its
      configured URL (by name lookup against the connection map), call `client.initialize()` wrapped in
      `Mono.fromRunnable(() -> client.initialize()).timeout(initTimeout).subscribe(...)` or equivalent
      synchronous helper. On success, `registry.record(name, url, CONNECTED)`. On any `Exception` or
      `TimeoutException`, `registry.record(name, url, FAILED)` and `log.warn(...)` with the cause attached
      as DEBUG-only detail (`log.debug("MCP {} init failed", name, cause)`). The whole per-client body, including
      name and URL resolution, sits inside the try, so nothing escapes the `ApplicationReadyEvent` listener and
      fails the application start.
- [x] 3.4 Ensure the initialiser fires **before** `StartupLogConfig.onReadinessChange(...)`. No `@Order` is
      needed: `EventPublishingRunListener.ready(...)` publishes `ApplicationReadyEvent` and only then publishes
      `AvailabilityChangeEvent<ACCEPTING_TRAFFIC>`, both synchronously, so the registry is always populated before
      the banner renders. Confirmed against `spring-boot` 3.5.14 sources and observed in the 8.1 and 8.2 smoke
      tests, where the banner reported the real per-server states.

## 4. Tool callback filtering

- [x] 4.1 Create `com.lukk.ascend.ai.agent.config.mcp.FilteredToolCallbackProvider` implementing
      `ToolCallbackProvider`. Constructor takes `List<McpSyncClient>`, `McpClientStatusRegistry`, and
      `McpStartupProperties`.
- [x] 4.2 Implement `ToolCallback[] getToolCallbacks()` by filtering the *client* list against
      `registry.connectedNames()` and building a fresh `SyncMcpToolCallbackProvider` per surviving client, rather
      than post-filtering a combined callback array. Spring AI 1.1.5's `SyncMcpToolCallback` does not expose its
      owning client, so a callback-to-client reverse lookup would need reflection or tool-name parsing. Resolution
      of a client's connection key lives in `McpConnectionNames.resolve(...)`, which reads
      `getClientInfo().title()` as set by `McpClientAutoConfiguration`; see ADR-008.
- [x] 4.3 Expose the filtered provider as `@Component @Primary` so the `ToolCallbackProvider` that `ChatExecutor`
      takes through its constructor resolves to the filtered instance.
- [x] 4.4 Set `spring.ai.mcp.client.toolcallback.enabled: false` so Spring AI's own unfiltered
      `SyncMcpToolCallbackProvider` bean never enters the context. `@Primary` alone only governs single-value
      injection, so a `List<ToolCallbackProvider>` injection point would otherwise bypass the filter.
- [x] 4.5 Mirror the condition on `FallbackToolCallbackProvider` (`@ConditionalOnProperty` on
      `spring.ai.mcp.client.enabled` having value `false`) instead of `@ConditionalOnMissingBean`, which Spring
      Boot only order-guarantees inside auto-configuration.
- [x] 4.6 Recover a stale session with one reconnect-and-retry per client, serialised per client, and record the
      client `FAILED` when the reconnect or the retry still fails.

## 5. Readiness banner update

- [x] 5.1 Inject `McpClientStatusRegistry` into `StartupLogConfig`.
- [x] 5.2 Replace the existing `MCP tools:` single-line summary with a new `MCP servers:` multi-section. For each
      entry in `registry.entries()`: `      <padded-name>: <url> [Connected]` or `[FAILED]`. Names padded to a
      common width (e.g. 16 chars) so the URLs align vertically. Indentation: 6 spaces (per
      [coding-standards](../../../.agents/skills/coding-standards/SKILL.md) "keys 3-indented", which means 6
      spaces from column 0 inside the 4-space-indented `MCP servers:` section).
- [x] 5.3 Add a single aggregate counter line `      Aggregate: N/M connected` at the bottom of the section.
      (Re-evaluated at code review: kept, and the spec scenario amended to describe the per-connection lines plus
      the counter. It was verified working during the 8.1 and 8.2 smoke tests.)

## 6. Tests

- [x] 6.1 Write `McpStartupToleranceIT` under
      `apps/ascend-agent/src/test/java/com/lukk/ascend/ai/agent/integration/`, with every configured connection
      redirected at `http://localhost:1` (always refused). A map-valued property binds by merge across property
      sources, so a fictional extra key would sit alongside the three real connections instead of replacing them,
      which is why all three are redirected rather than one.
- [x] 6.2 Assert: context refreshes, every entry is `FAILED` and is keyed by its bare connection name with its
      configured URL (which pins the `getClientInfo().title()` claim against real Spring AI wiring),
      `ToolCallbackProvider.getToolCallbacks()` is empty, the context holds no unfiltered MCP provider bean, and
      `POST /api/v1/ai/prompt` with `provider=lmstudio` returns 200 through `MockMvc` with `ChatModelResolver`
      replaced by a `@MockitoBean` handing back a stub `ChatModel`.
- [x] 6.3 Assert in `StartupBannerIT` the exact `MCP servers:` section content: the 6-space indent, one line per
      connection with an aligned URL column and its `[Connected]` / `[FAILED]` marker, the `Aggregate: N/M
      connected` line, and the absence of any `MCP tools` summary. `StartupLogConfigTest` asserts the same line
      format at the unit level, including the URL-column alignment and the empty-registry rendering.
- [x] 6.4 Assert the per-client init timeout at two levels. `McpStartupTimeoutIT` configures
      `app.mcp.startup.init-timeout=200ms` and points one connection at a loopback server that accepts the TCP
      connection and never replies, then asserts the connection really was accepted and the client is recorded
      `FAILED` with no tools advertised (without the timeout the boot would hang for the 300s request-timeout, so
      reaching the assertion is itself the proof). `McpClientStartupInitializerTest` pins the wall-clock bound
      deterministically: a client whose handshake sleeps 5s against a 100ms timeout is recorded `FAILED` and the
      loop returns in under 1s.
- [x] 6.5 Write `McpClientStartupInitializerTest` covering the init loop, per-client failure isolation, the
      timeout branch, URL resolution (configured, unconfigured, missing url, empty map, absent map), and the case
      where a client cannot report its own identity.
- [x] 6.6 Write `McpConnectionNamesTest` for connection-name resolution, extend `McpClientStatusRegistryTest` for
      `markFailed` and the immutable `entries()` snapshot, and extend `FilteredToolCallbackProviderTest` for the
      `FAILED` demotion and the per-client reconnect serialisation.

## 7. Documentation

- [x] 7.1 Update `apps/ascend-agent/docs/architecture/arc42/08-crosscutting-concepts.md` "Model Context Protocol (MCP)"
      section: add a "Startup tolerance" subsection describing the `initialized=false` + initialiser-loop pattern,
      and how to read the readiness-banner `MCP servers:` section.
- [x] 7.2 Create `apps/ascend-agent/docs/architecture/decisions/ADR-008-mcp-startup-tolerance.md` recording the
      decision (built-in flag + small runner vs. custom client builder), the trade-offs, and pointers to the
      OpenSpec change `add-mcp-startup-tolerance` and the upstream Spring AI MCP Security "known limitation" note.
- [x] 7.3 Update `apps/ascend-agent/README.md` "Operational Workflow" or "Configuration" section to mention the
      tolerance behaviour and the `app.mcp.startup.init-timeout` knob.
- [x] 7.4 Add the new ADR to
      [docs/architecture/decisions/README.md](../../../docs/architecture/decisions/README.md) ascend-ai-agent ADR list
      and to `apps/ascend-agent/docs/architecture/arc42/09-architecture-decisions.md`.

## 8. Verification

- [x] 8.1 Manual smoke test: with `ascend-audio-scribe` stopped and the agent restarted, the banner read
      `ascend-audio-scribe [FAILED]`, the other two `[Connected]`, `Aggregate: 2/3 connected`, and the service came
      up with health UP. The stack was then restored to 3/3.
- [x] 8.2 Manual smoke test: with all three MCP servers up, the banner read `ascend-audio-scribe [Connected]`,
      `ascend-weather-mcp [Connected]`, `ascend-web-hunter [Connected]`, `Aggregate: 3/3 connected`.
- [x] 8.3 Run `./gradlew test integrationTest`. All green: 732 unit tests across 99 classes and 24 integration
      tests across 8 classes, zero failures, zero errors, zero skipped.
- [x] 8.4 Code review closed. Fixed in this pass: the unfiltered Spring AI provider bean removed from the context,
      `reconnect()` given registry demotion and per-client serialisation, real Spring AI name and URL wiring
      asserted, `McpClientStartupInitializerTest` written, the two falsely-ticked test tasks implemented, the
      banner section genuinely asserted, `@ConditionalOnMissingBean` replaced with a mirrored
      `@ConditionalOnProperty`, the startup loop made exception-proof, `entries()` made immutable, `DISABLED`
      dropped, `McpStartupProperties` moved to Lombok, name resolution extracted to `McpConnectionNames`, registry
      logging moved to the initialiser, the `FilteredToolCallbackProvider` Javadoc cut to the cap, and the two
      inline fully-qualified names in `McpStartupToleranceIT` imported. The `Aggregate:` banner line was kept and
      the spec scenario amended to match.
