## REMOVED Requirements

### Requirement: Configuration uses Spring AI's built-in deferral flag

**Reason**: Its upgrade scenario is pinned to the Spring AI 1.1.x line ("Spring AI version upgrade within the 1.1.x line"), which the project leaves for Spring AI 2.0.x. A MODIFIED block cannot drop or rename that scenario, so the requirement is replaced whole by "Configuration uses Spring AI's built-in MCP deferral flag" below, with the same flags, the same no-fork rule and the same auto-configuration scenario.

**Migration**: Nothing changes in the code or the configuration. `spring.ai.mcp.client.initialized=false` and `spring.ai.mcp.client.toolcallback.enabled=false` stay in `application.yaml`, and `McpClientAutoConfiguration` and `McpToolCallbackAutoConfiguration` keep their names in Spring AI 2.0.1.

## ADDED Requirements

### Requirement: Configuration uses Spring AI's built-in MCP deferral flag

The application SHALL set `spring.ai.mcp.client.initialized=false` and
`spring.ai.mcp.client.toolcallback.enabled=false` in
[application.yaml](../../../../../apps/ascend-agent/src/main/resources/application.yaml). The project MUST NOT replace,
override, or fork Spring AI's `McpClientAutoConfiguration` or the `SyncMcpToolCallbackProvider` class. Switching off
`McpToolCallbackAutoConfiguration` through its own documented property is the supported way to keep the unfiltered
provider bean out of the context.

#### Scenario: Spring AI version upgrade within the 2.0.x line

- **GIVEN** the project upgrades from Spring AI 2.0.1 to a later 2.0.x patch
- **WHEN** the new patch ships
- **THEN** the change requires no code edits to ascend-ai-agent's MCP integration
- **AND** the `initialized=false` flag continues to defer auto-config-driven init

#### Scenario: Auto-built MCP clients still construct normally

- **WHEN** the Spring context refreshes with `initialized=false`
- **THEN** `McpClientAutoConfiguration` constructs every configured `McpSyncClient`
- **AND** the transport, sampling, roots, and request-timeout on each client match the project's YAML config
- **AND** no `McpSyncClient.initialize()` call is made by the auto-config factory
- **AND** no auto-configured `SyncMcpToolCallbackProvider` bean is created
