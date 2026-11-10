## Build order

Build order (owner build order of 2026-10-04, which supersedes the earlier orders): build group 4 (personal), position 6, right after `add-action-approvals`, so `ToolModeResolver` and its settings default, the approval gate and the egress proxy image of `add-agent-sandbox` already exist when it starts. It needs the changes in the table below, which all land earlier. `add-download-ingestion`, `add-obsidian-vault`, `add-openclaw-plugin-host` and `add-self-built-integrations` land later and plug into it. It depends on no company change. It edits none of the changes below:

| Change | What this change needs from it |
| :--- | :--- |
| `upgrade-spring-boot-4` | Spring AI 2.0.1 with MCP Java SDK 2.0.0, the per connection `McpClientCustomizer<WebClientStreamableHttpTransport.Builder>` hook, the Tool Search modules that ship with Spring AI 2.0.1, and the RFC 7807 problem detail of its D19 |
| `close-agent-test-gaps` | The shared scripted e2e harness: the fake MCP server image, the scripted model reached through the provider `scripted` and the `e2e` overlay |
| `add-keycloak-login` | The service token attachment of its D6 and task 6.3, which this change moves into its own customizer, and `TenantContext.currentTenantId()` of its D3 |
| `add-deployment-modules` | The module catalog, `ASCEND_MODULES` bound to `app.modules.active`, `@ConditionalOnModule`, `ModuleState`, its delta of `mcp-startup-resilience`, under which a connection of an inactive module gets no connection, no registry entry and no banner line, `McpReconnectScheduler` with `app.mcp.reconnect.interval` (its D19 and task 4.8), which retries a failed server in the background, and `UsageEventPort` of its company extension ports |
| `add-agent-skills` | `ChatToolset` and `AgentNativeTool`, the tool context keys, and the capability index with `CapabilitySource` and `CapabilityIndexSync`, which gains a third type `tool` |
| `add-agent-subagents` | The run tool loop and the definition `tools` lists, which name the prefixed MCP tool names of this change |
| `add-agent-sandbox` | The Smokescreen egress proxy image in `infra/sandbox/egress-proxy/`, reused here for outside servers that need the internet |
| `add-action-approvals` | The `requires_approval` tool mode, the approval gate in `ChatToolset` and the per tool metadata (`category`, `rememberable`, `scope-arguments`) |

Changes touched by this one. The edits are listed in design.md under "Required edits to other changes". The changes that land earlier carry their edit already. A later personal change carries its own part. A company change of build group 5 registers its part later, and no task here waits for it:

| Change | Why it is touched |
| :--- | :--- |
| `add-deployment-modules` | The five module names `mcp-google`, `mcp-github`, `mcp-home-assistant`, `mcp-browser` and `mcp-files` it reserved for this change are no longer used, and the shared egress proxy carries no module profile, because it is always on (owner answer 76.5 of 2026-10-08) |
| `add-agent-skills` | The capability index gains the type `tool`, tool entries may be tenant-keyed, and `ChatToolset` hands the deferred tools to the tool search step |
| `add-agent-subagents` | The run loop uses the same deferred tool selection as the main chat |
| `add-action-approvals` | The deployment default approval list and the per tool metadata also come from the MCP server entries, and its D2 statement that the default list holds no MCP tool changes |
| `add-tenant-policy` | Company, registers later: allow-list entries can name a whole server (`server:<id>`), a deny list wins over them, and tool names are the prefixed names (task 5.2 moved there in the dependency fix of 2026-10-05) |
| `add-keycloak-login` | The service token goes only to our own MCP servers, never to an outside server (moved from `add-auth-and-identity` with the split of 2026-10-04, and this change moves the attachment into its customizer) |
| `add-usage-metering-and-quotas` | Company, registers its `UsageEventPort` implementation later, which writes a ledger row of the new request type `mcp-tool` for calls to outside servers (task 7.1 moved there in the dependency fix of 2026-10-05) |
| `add-agent-sandbox` | Its egress proxy entrypoint accepts an `open` mode, so the same image serves outside MCP servers |
| `add-coding-agent-delegation` | Its statements about the GitHub MCP server and `GITHUB_MCP_TOKEN` no longer apply, because this change ships no GitHub server |

## Why

The owner wants the personal assistant to reach outside apps through tools other people already build and maintain, instead of AscendAI writing and keeping its own integrations (owner decision of 2026-10-02). On 2026-10-02 the owner also decided that no specific outside server (mail, calendar, code hosting, home automation, browser or files) is built now: apps he needs come through OpenClaw plugins hosted by `add-openclaw-plugin-host`, and no list of apps is needed now. What every route needs is one generic way to connect an MCP server safely. Today the agent can only talk to the three MCP servers of this repository, every server is a hand-written block in `application.yaml`, every tool of every server is sent to the model in every request, nothing protects a sending or deleting tool of an outside server, and the agent has no rule for where a server that speaks only stdio may run.

## What Changes

- One configuration entry per MCP server under `app.mcp.servers.<id>`: an optional deployment module (an entry with no module is always on, owner answer 90 of 2026-10-08), transport, URL and endpoint, headers with secrets taken from the environment, trust, which tools are exposed, the tool name prefix, whether tools are always listed or found by search, a default tool mode, per tool modes and approval metadata, timeouts, a result size cap, and whether calls are metered. Adding a further server is one entry plus, when it needs a container, one compose service. The Spring AI connection list is derived from these entries, so a server is configured in one place only. An entry is on exactly when its deployment module is active in `ASCEND_MODULES` (the switch of `add-deployment-modules`). There is no per entry `enabled` flag.
- Entries can also come from a run-time source. `add-self-built-integrations` adds and removes entries while the agent runs, scoped to one tenant, with tenant-keyed tool entries and per tool modes from the owner's reviews. The configuration source stays the only source at startup.
- The agent connects only over Streamable HTTP. A stdio server never runs inside the agent process, with the agent's secrets, and never in the per-run sandbox of `add-agent-sandbox`. It runs in its own container behind a pinned stdio to Streamable HTTP bridge, holding only its own secrets. The startup refuses a stdio connection.
- Every MCP tool name gets its server's prefix, so two servers can never offer the same name. A tool that already starts with its prefix is not prefixed twice, so `weather_current` and `web_search` keep their names. **BREAKING** for tool names the model sees: `session_establish`, `session_status` and `session_clear` of ascend-web-hunter become `web_session_establish`, `web_session_status` and `web_session_clear`, and the `health` tool of ascend-audio-scribe is no longer offered.
- Tools of servers marked `discovery: search` are not listed in every request. Each such tool is an entry of type `tool` in the capability index of `add-agent-skills`, and the model finds it with the Tool Search tool that Spring AI 2.0.1 ships, through an index adapter over that capability index. Found tools are added to the next model call of the same request. Our own servers stay `discovery: always` and are listed as today.
- Safe defaults: an entry with `trust: external` defaults to `requires_approval` for every tool through the approval gate of `add-action-approvals`, so a tool that appears after an upgrade asks first until the owner reviews it by naming it in the entry's overrides.
- Our own servers get the tool context forwarded: for every `trust: internal` entry the agent copies the tenant id and the request id into the MCP `_meta` object of each call (asked by `add-file-download`). Nothing is copied to an outside server.
- A server that is down at startup keeps the agent starting, as `mcp-startup-resilience` already requires. The background retry of a `FAILED` server is `McpReconnectScheduler` of `add-deployment-modules` (its D19 and task 4.8). This change creates no scheduler of its own. It reuses that one and lets it also retry a `FAILED` run-time entry.
- One server entry can switch single tools by a second module: a per tool override `tools.overrides.<tool>.module` offers that tool only while its module is active too. `add-download-ingestion` (the agent part of `add-file-download`) uses it for the `web_download_*` tools of ascend-web-hunter (module `web-download`).
- Each tool call carries the server and tool in the `mcp.tool.duration` timer, in a new `mcp.tool.result.truncated` counter and in its log line. Each successful call of a server with `metered: true` records one usage event through `UsageEventPort` of `add-deployment-modules`, whose default does nothing. `add-usage-metering-and-quotas` (company, build group 5) registers its implementation later. This change does not wait for it.
- Generic deployment rules for outside servers: own container, own secrets, own internal network shared only with the agent and, when it needs the internet, the shared egress proxy, and a contract test that lists the tools of each pinned outside image.
- Tests with the one fake MCP server class of `close-agent-test-gaps` on the MCP Java SDK server transport (owner answer 91.2 of 2026-10-08), extended here with the switches the tests need, and one new deterministic end-to-end spec against a fake outside server, driven by a scripted model (no AI model), for registration, retry, names, headers, `_meta`, approvals, exclusion, the result cap, the metrics and finding a deferred tool by search. There is no AI-run spec, because an AI-run spec never uses the fake MCP server (owner answer 70.4 of 2026-10-04, ruling 13.5 of 2026-10-05) and our own servers are never searched (owner answer 65.19 of 2026-10-04). The e2e harness they need (the fake server image, the scripted model reached through the agent's own provider `scripted`, and the agent's e2e overlay, which the deterministic phase copies into the running agent, owner answer 98.1 of 2026-10-08) is owned by `close-agent-test-gaps` (build group 3, position 1), and this change reuses it (owner answer 67.1 of 2026-10-04). The scripted model and the fake MCP server start only for deterministic tests, never for AI-run e2e specs (owner answer 70.4 of 2026-10-04).

## Capabilities

### New Capabilities

- `mcp-tool-servers`: the per server configuration and its sources, the module switch and the per tool module override, the Streamable HTTP only rule, the tool name prefix, tool exposure, per server headers, timeouts and result cap, the `_meta` forwarding to our own servers, default tool modes and approval metadata, the service token rule, run-time and tenant-scoped entries, and the metrics and logs of MCP tool calls.
- `mcp-tool-discovery`: tools found by search instead of listed in every request, tool entries in the capability index, the always-listed set, the rule that a search returns only tools of the request's own tool list, and the fallback when the index is not ready.
- `mcp-tool-server-deployment`: where an outside server runs, its container hardening and network isolation, the shared egress proxy, where secrets live, and the contract test per pinned outside image.

### Modified Capabilities

(none. `mcp-startup-resilience` keeps every requirement here. The rule that a connection of an inactive module gets no connection and no banner line, and the background retry of a failed client, are the delta of `add-deployment-modules`, and a second delta on the same spec here would conflict with it. `upgrade-spring-boot-4` also replaces one requirement of that spec.)

## Impact

- ascend-agent, new code in `config/mcp/`: `McpServerProperties` (`app.mcp.servers`), `McpServerEntrySource` with the configuration source, an `EnvironmentPostProcessor` that derives the Spring AI connection entries of active modules, `RuntimeMcpClientRegistry` for run-time entries, an `McpClientCustomizer` for headers, base URL and timeouts per connection, `ToolContextToMcpMetaConverter` for internal entries, the prefix and exposure rules in `FilteredToolCallbackProvider`, a result cap wrapper, the `tool` type `CapabilitySource`, a `ToolIndex` adapter over the capability index, and a deferred tool selection used by a `ToolCallingAdvisor` subclass in the main chat and by the run loop of `add-agent-subagents`.
- ascend-agent, changed code: `FilteredToolCallbackProvider`, `McpClientStartupInitializer`, `McpClientStatusRegistry`, `McpReconnectScheduler` of `add-deployment-modules` (it also retries run-time entries), `StreamingChatExecutor`, the one chat executor since owner answer 89.1 of 2026-10-08 (the main chat tool loop moves from the model's internal loop into the advisor, with the same `TrackingToolCallingManager`), `StartupLogConfig`, `application.yaml` and `application-docker.yaml`.
- New dependency: `org.springframework.ai:spring-ai-tool-search-tool` and `org.springframework.ai:spring-ai-tool-search-advisor` 2.0.1 (Apache 2.0, managed by the Spring AI BOM). Only the `ToolIndex` API, `ToolSearchTool` and the `ToolCallingAdvisor` base are used, not the Lucene or vector index implementations. The MCP Java SDK server transport, already on the classpath, serves the fake servers in tests.
- Compose: the generic service `mcp-egress-proxy` (Smokescreen image of `add-agent-sandbox`), with no profile, so it is always on from this change onward (owner answer 76.5 of 2026-10-08). No outside server container ships with this change.
- No database change. The project is under development, so there is no data migration. Owner answer 73.1 of 2026-10-06 confirms that the data in today's development stores is disposable.
- Docs: a monorepo decision record for where MCP servers run, an agent decision record for deferred tools, `docs/MCP_SERVERS.md` (how to add a server as one entry, trust, modes and reviews, the container rules), `apps/ascend-agent/AGENTS.md`, `docs/SECURITY.md` (outside servers, egress, approval defaults), `docs/OBSERVABILITY.md`, Bruno requests under `docs/api/request/AscendAI/mcp/`, and one new deterministic e2e spec in `apps/ascend-agent/e2e/`.

## Relevant Skills

Load these from `.agents/skills/` before implementing this change:

- `springboot-patterns` and `java-coding-standards` for the properties, the entry sources, the customizers, the advisor, the provider changes and their tests
- `hexagonal-architecture` for `McpServerEntrySource` and the run-time client registry
- `docker-patterns` for the egress proxy service, the networks and the container rules
- `security-review` for secrets, the egress proxy, the exposure lists, the approval defaults, the `_meta` forwarding and prompt injection through tool results
- `observability-and-logging` for the metrics, log lines and the startup banner block
- `tdd-workflow` for writing each test before its code
- `build-dependency-management` for the two Spring AI tool search modules in the version catalog
- `architecture-decision-records` for the two decision records
- `e2e-runbooks` for the new e2e spec
- `markdown-writer` for `docs/MCP_SERVERS.md`, the README and AGENTS.md updates
