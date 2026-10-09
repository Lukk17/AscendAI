## Context

See proposal.md for why. This section holds only the facts the design rests on, each checked on 2026-10-02.

The MCP client today (`apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/config/mcp/`):

- Spring AI builds one `McpSyncClient` per entry of `spring.ai.mcp.client.streamable-http.connections` (`application.yaml` lines 391 to 398, and `application-docker.yaml` for container addresses). `initialized=false` and `toolcallback.enabled=false` keep the auto configuration from connecting and from registering an unfiltered provider.
- `McpClientStartupInitializer` initialises each client on `ApplicationReadyEvent` with `app.mcp.startup.init-timeout` (5 seconds) and records `CONNECTED` or `FAILED` in `McpClientStatusRegistry`.
- `FilteredToolCallbackProvider` lists the tools of `CONNECTED` clients with `McpToolNamePrefixGenerator.noPrefix()`, replaces characters outside `[a-zA-Z0-9_-]`, renames a collision to `<name>_2`, and reconnects a stale session once. `McpToolCallbackCache` holds the listing for `app.mcp.tool-cache.ttl` (60 seconds) and drops it on `McpToolsChangedEvent`.
- `ChatExecutor` records `mcp.tool.duration` tagged `tool` and `outcome`, and `ToolCallTracker` gives the tools used.
- The three connected servers are our own. Their tool names: `weather_current`, `weather_forecast`, `weather_historical`, `weather_air_quality`, `weather_geocode`, `web_search`, `web_read`, `session_establish`, `session_status`, `session_clear`, `transcribe_local`, `transcribe_openai`, `transcribe_hf`, `transcribe_audacity` and `health`.

Spring AI 2.0.1, which `upgrade-spring-boot-4` brings, read from the tag `v2.0.1` of `spring-projects/spring-ai` and from Maven Central:

- `McpStreamableHttpClientProperties.ConnectionParameters` is `record (url, endpoint)`. There is no header field. `StreamableHttpWebFluxTransportAutoConfiguration` calls every `McpClientCustomizer<WebClientStreamableHttpTransport.Builder>` bean with `customize(connectionName, transportBuilder)`, and the transport builder has `webClientBuilder(WebClient.Builder)`. Headers and timeouts per connection therefore go through one customizer bean.
- The Tool Search Tool moved from the archived `spring-ai-community/spring-ai-tool-search-tool` into Spring AI 2.0.0 GA. `org.springframework.ai:spring-ai-tool-search-tool` 2.0.1 holds the `ToolIndex` interface (`indexTool`, `indexTools`, `search(ToolSearchRequest)`, `clearIndex(sessionId)`), `ToolSearchTool`, `ToolReference` and three index implementations (Lucene, regex, vector store). `org.springframework.ai:spring-ai-tool-search-advisor` 2.0.1 holds `ToolSearchToolCallingAdvisor extends ToolCallingAdvisor`. The advisor sends only its search tool (named `toolSearchTool`) plus the tools named in earlier search results, and it hides every other tool, including tools that should stay listed. The method that selects the tools of each iteration is private.
- MCP Java SDK 2.0.0 (`mcp-core`) ships `HttpServletStreamableServerTransportProvider` and `McpServer`, so a test can run a real Streamable HTTP MCP server in the same JVM. Its tool call request carries a `_meta` map, and Spring AI's MCP tool callback fills it from the tool context through a `ToolContextToMcpMetaConverter`.

The owner's decision of 2026-10-02: no specific outside server (Gmail, Google Calendar, GitHub, Home Assistant, a browser or a filesystem) is built now. Apps the owner needs come through OpenClaw plugins, which `add-openclaw-plugin-host` hosts and exposes to the agent as one MCP server entry of this change. Self-built servers of `add-self-built-integrations` are added as run-time entries. This change is therefore the generic mechanism only.

Module switch: `add-deployment-modules` decides which modules are on through `COMPOSE_PROFILES`, passed to the agent as `ASCEND_MODULES` and bound to `app.modules.active`. Under its delta of `mcp-startup-resilience` a connection of an inactive module gets no connection, no registry entry and no banner line. Its D19 adds `McpReconnectScheduler` (task 4.8 there), which retries a failed connection in the background every `app.mcp.reconnect.interval`.

## Goals / Non-Goals

Goals:

- One configuration entry per server and no code per server.
- One switch: an entry is on when its deployment module is active.
- No outside server code inside the agent process, and no outside server that can read another server's secrets or reach the internal services.
- A request carries only the tools it needs, without a second index and without a second tool search mechanism.
- Every tool of an outside server asks the owner first until he reviews it, through the existing approval gate.
- A server that is down never stops the agent and comes back on its own.

Non-Goals:

- Any specific outside server. Apps come through `add-openclaw-plugin-host` and `add-self-built-integrations`, and the owner adds any other server as one entry.
- Our own MCP server code. ascend-weather-mcp, ascend-web-hunter and ascend-audio-scribe do not change. Only the names the model sees for three web-hunter tools change, and the `health` tool is excluded.
- An MCP server inside the agent (the agent exposing tools to others).
- A user interface for server configuration. The owner edits `application.yaml` and `.env`.
- MCP resources and prompts. Only tools are used.
- Deciding risk from tool arguments at run time. Modes stay per tool, and remembered approvals use the argument scope `add-action-approvals` already defines.

## Decisions

### D1: One entry per server, the Spring AI connection list is derived

`McpServerProperties` binds `app.mcp.servers.<id>` with the fields of the `mcp-tool-servers` spec and validates them at startup (id shape, a module name of the catalog when `module` is set, unique non-empty prefix, `transport` equal to `streamable-http`, a URL, `discovery` and `default-mode` values, overrides that name no excluded tool, an override `module` that the catalog knows, positive timeouts and cap). The `module` field is optional (owner answer 90 of 2026-10-08, `add-deployment-modules` D7): an entry with no `module` belongs to no switchable module and is always on, in every profile. No profile changes this rule.

`McpConnectionEnvironmentPostProcessor`, registered in `META-INF/spring.factories`, runs after the module selection check of `add-deployment-modules` and adds `spring.ai.mcp.client.streamable-http.connections.<id>.url` and `.endpoint` for every entry whose `module` is in `app.modules.active`, and for every entry with no `module`, as a property source of lower precedence than the files. A hand-written connection entry is refused at startup, so a server is configured in one place only. The `module` field replaces `app.modules.connections`, which `add-deployment-modules` adds until this change lands.

Example, the shipped entries plus one outside example:

```yaml
app:
  mcp:
    reconnect:
      interval: 60s
    discovery:
      max-results: 5
      score-threshold: 0.4
    servers:
      ascend-weather-mcp:
        module: weather
        url: http://localhost:9998
        trust: internal
        tool-prefix: weather
      ascend-web-hunter:
        module: web-search
        url: http://localhost:7021
        trust: internal
        tool-prefix: web
        request-timeout: 330s
      ascend-audio-scribe:
        module: audio
        url: http://localhost:7017
        trust: internal
        tool-prefix: transcribe
        tools:
          exclude: health
```

The exclude list of `ascend-audio-scribe` is the literal `health`, because one value needs no setting (answer 93 of 2026-10-08). `add-customer-stack-installer` (company, build group 5) turns it into the placeholder `${AUDIO_TOOLS_EXCLUDE:health}` in its own task 5.1, so its installer can also exclude `transcribe_local` on a server without a GPU. That plug-in point stays (R2), and today's behaviour is the same.

The `ascend-web-hunter` timeout is `DOWNLOAD_TIMEOUT_SECONDS` of `add-file-download` (300 seconds by default) plus 30 seconds, so a download call ends inside the call bound. Every value of the example with a default is a setting (owner rule 98 of 2026-10-08, tasks 1.1 and 1.3): each `url` (`APP_MCP_SERVERS_ASCENDWEATHERMCP_URL`, `APP_MCP_SERVERS_ASCENDWEBHUNTER_URL` and `APP_MCP_SERVERS_ASCENDAUDIOSCRIBE_URL`, the `localhost` addresses in `application.yaml`, the container addresses in `application-docker.yaml` and in compose), this timeout (`APP_MCP_SERVERS_ASCENDWEBHUNTER_REQUESTTIMEOUT`, `330s`, which an operator who raises `DOWNLOAD_TIMEOUT_SECONDS` raises with it), and the discovery bounds (`APP_MCP_DISCOVERY_MAXRESULTS`, `5`, and `APP_MCP_DISCOVERY_SCORETHRESHOLD`, `0.4`). `app.mcp.reconnect.interval` is the setting `APP_MCP_RECONNECT_INTERVAL` of `add-deployment-modules`.

Per tool module: an override may carry `module`, a second module name of the catalog for that one tool. The tool is exposed only while both the entry's `module` and the tool's `module` are active, and for the module grants of a tenant (D6) the tool belongs to its own `module`. A tool whose module is off is treated like an excluded tool (D5): never offered, never indexed and never callable. `add-download-ingestion` (the agent part of `add-file-download` since the split of 2026-10-04) sets `module: web-download` on each of the eight `web_download_*` tools in the `ascend-web-hunter` entry, for example:

```yaml
      ascend-web-hunter:
        tools:
          overrides:
            web_download_file: { module: web-download }
            web_download_get: { module: web-download }
```

An outside server is an entry like this one, written by the change or the owner that adds it:

```yaml
      notes:
        module: notes
        url: http://mcp-notes:8000
        trust: external
        tool-prefix: notes
        discovery: search
        max-result-chars: 20000
        headers:
          Authorization: "Bearer ${NOTES_MCP_TOKEN:}"
        tools:
          overrides:
            search_notes: { mode: allowed }
            send_note: { mode: requires_approval, category: outside_message, rememberable: true, scope-arguments: [to] }
```

Defaults that depend on `trust`: `default-mode` is `requires_approval` for `external` and `allowed` for `internal`, `metered` is `true` for `external` and `false` for `internal`, and `discovery` is `search` for `external` and `always` for `internal`. Our own servers are already metered by the wrappers `add-usage-metering-and-quotas` defines for them.

`add-openclaw-plugin-host` adds the entry `openclaw-apps` for the OpenClaw app plugins that the containers of its service `ascend-openclaw-host` run, with its own module. That entry is written in that change, not here.

Alternatives considered: keep the Spring AI connection list and add a second map keyed by the same name (rejected: two places for one server, which drift), build the `McpSyncClient` beans of configured entries ourselves (rejected: `mcp-startup-resilience` forbids replacing `McpClientAutoConfiguration`), and a per entry `enabled` flag next to `module` (rejected: two switches for one thing, and `add-deployment-modules` makes the module the only switch).

### D2: Where an MCP server runs

The agent connects only over Streamable HTTP and never starts a process. An outside server runs in its own container. A server that speaks only stdio runs in its own container behind a pinned stdio to Streamable HTTP bridge (for example `supercorp-ai/supergateway`, MIT, `--outputTransport streamableHttp`).

Why not inside the agent process: a stdio server is a child process of the agent and inherits its environment, so the server's code (and every dependency it pulls) could read the provider keys, the database password, the service token and the secrets of every other server. A crash or a memory leak in it would also hit the agent. The agent is the process most exposed to prompt injection, so it should hold the fewest moving parts.

Why not in the sandbox of `add-agent-sandbox`: a sandbox workspace is created for one subagent run and destroyed when the run ends, has no network by default, and by design carries no secrets (its D4). An MCP server is the opposite: it lives as long as the agent, the main chat needs it outside any run, it may need its own secret, and it keeps state between calls. Putting secrets into throwaway workspaces would break the sandbox's main promise.

Why not Docker's MCP Gateway (`docker/mcp-gateway`, MIT): it starts each server as a container through the Docker socket. `harden-cloud-deployment` keeps the socket away from the agent, and `add-agent-sandbox` makes its runner the only service that holds it. A second socket holder for tools would double that risk, for servers that are fixed at deployment time.

So each outside server that runs in the stack is a compose service with its own secrets only, its own internal network shared with the agent and, when it needs the internet, the egress proxy (D11), and the hardening of the `mcp-tool-server-deployment` spec. The self-built servers of `add-self-built-integrations` follow the same rule through the sandbox runner instead of compose. The application refuses `transport: stdio`, any `spring.ai.mcp.client.stdio` connection and any `spring.ai.mcp.client.sse` connection at startup.

### D3: Headers, base URL, timeouts and `_meta` through customizers

`McpServerConnectionCustomizer implements McpClientCustomizer<WebClientStreamableHttpTransport.Builder>` gets the connection name, looks up the server entry and sets a `WebClient.Builder` cloned from the shared one with the base URL, the default headers of the entry and the response timeout from `request-timeout`. A second customizer of type `McpClientCustomizer<McpClient.SyncSpec>` sets the request timeout of the client. The type parameters were checked in the 2.0.1 jars on 2026-10-03 and are recorded in `upgrade-spring-boot-4` D11: `StreamableHttpWebFluxTransportAutoConfiguration` calls the transport builder customizer after it has set the base URL, the endpoint and the JSON mapper, so the cloned `WebClient.Builder` must carry the base URL again, and `McpClient.SyncSpec` has no header method, so headers never go through the second customizer. `add-keycloak-login` D6, which lands before this change (split of 2026-10-04 from `add-auth-and-identity`, owner rule of 2026-10-04), attaches the service token to our own MCP connections through a `McpClientCustomizer` of its own. This change moves that attachment into this customizer and sends the token only to `trust: internal` entries (task 5.3, the required edit `add-keycloak-login` asks of this change), so there is one header mechanism. Run-time entries (D10) use the same customizers.

Header values are resolved from placeholders when the properties bind. An entry of an active module with a header whose value is empty after resolution is not connected: `McpClientStartupInitializer` records it `FAILED` without calling `initialize()` and logs one WARN line naming the entry and the header name. Header values are never logged, and the banner shows the URL only.

`McpClientStartupInitializer` uses the entry's `init-timeout` when set, otherwise `app.mcp.startup.init-timeout`.

`_meta` forwarding (asked by `add-file-download`, used by its agent part `add-download-ingestion`): one `ToolContextToMcpMetaConverter` copies the tool context keys `tenant_id` and `request_id` of `add-agent-skills` into the MCP `_meta` object of each call as `ascend.ai/tenant_id` and `ascend.ai/request_id`, for callbacks of `trust: internal` entries only. For `trust: external` the converter returns an empty map, so an outside server never learns the tenant or the request. The model cannot set `_meta`, because the tool schemas never carry it. ascend-web-hunter uses the tenant to scope its downloads.

### D4: Prefixed names and the server of each tool

`FilteredToolCallbackProvider` stops using `McpToolNamePrefixGenerator.noPrefix()` and uses one `McpToolNamePrefixGenerator` that returns `<prefix>_<name>`, or the name itself when it already starts with `<prefix>_`, then applies the existing character replacement and the 64 character rule of the spec. The prefix is unique among the entries one tenant sees (D1, D10), so cross server collisions cannot happen. The existing `_2` renaming stays as the last guard for a server that lists one name twice.

Every callback keeps its server id and original name, so the approval gate stores `tool_server` and `tool_original_name` (`add-action-approvals` D3), and `add-tenant-policy` (company, build group 5) can match `server:<id>` when it registers its policy later (required edit to `add-tenant-policy`).

Name changes the model sees: `session_establish`, `session_status` and `session_clear` become `web_session_establish`, `web_session_status` and `web_session_clear`. `health` of ascend-audio-scribe is excluded. The `web_download_*` tools of `add-file-download` keep their names, because they already carry the `web_` prefix. Every other existing name is unchanged. Task 3.5 searches the repository for the old names and updates every Bruno request, e2e spec and doc that names them as agent tool names, not as the web-hunter's own MCP names.

### D5: Exposure and the result cap

Exposure is applied right after listing, before the listing is cached, because it does not depend on the request. It covers `tools.include`, `tools.exclude` and the per tool `module` of D1, because the active modules are fixed while the agent runs. A tool that is excluded never reaches the cache, the index, the tool search or the approval execution path (`add-action-approvals` D7 finds the tool through `ChatToolset`, which no longer holds it, and answers `tool_unavailable`).

The result cap wraps each callback of an entry with `max-result-chars`: the text result is cut and the note line added. The counter `mcp.tool.result.truncated{server}` counts cuts. The cap is applied on the result text the model receives, never on a result the approval service stores, which has its own limit.

### D6: Deferred tools with the Spring AI Tool Search Tool

The tool list of one request is split by `ChatToolset` into an always part (agent native tools, tools of `discovery: always` servers) and a deferred part (tools of `discovery: search` servers). Both parts are already filtered by exposure, connection state and the module grants of the tenant, and gated tools are already wrapped by the approval gate. The tenant tool policy of `add-tenant-policy` (company, build group 5) adds its filter at the same point later.

What is reused from Spring AI 2.0.1:

- `ToolCallingAdvisor`, the advisor that runs the tool loop with a `ToolCallingManager`.
- `ToolSearchTool`, the search tool the model calls (named `toolSearchTool`), and its `ToolIndex` interface.

What is written here, because the library advisor cannot keep an always part (it sends only the search tool and found tools, and its selection method is private):

- `DeferredToolSelection`, a pure function: from the always part, the deferred part and the messages of the request so far, it returns the tools of the next model call: the always part in its given order, then the search tool when the deferred part is not empty, then the deferred tools named in earlier search results, in the order found. It reads search results the way the library does (the JSON list of names in each `toolSearchTool` response).
- `DeferredToolCallingAdvisor extends ToolCallingAdvisor`, which calls `DeferredToolSelection` before each model call of the main chat.
- `CapabilityToolIndex implements ToolIndex`. `indexTools(sessionId, references)` stores the names of the request's deferred tools in memory for that session and embeds nothing, because the entries are already in the capability index (D7). `search` calls the capability index search of `add-agent-skills` with type `tool`, the request's tenant, the request's embedding provider, the stored names as allowed entry keys, `max-results` and `score-threshold`, and falls back to its text match. `clearIndex(sessionId)` drops the stored names. The session id is the request's `request_id`, and the advisor clears it when the request ends.

`StreamingChatExecutor`, the one chat executor of `add-chat-streaming-and-conversations` (its D3, owner answer 89.1 of 2026-10-08), moves the main chat from the model's internal tool execution to `DeferredToolCallingAdvisor` with the existing `TrackingToolCallingManager`, so `toolsUsed`, `mcp.tool.duration` and the prompt cache retry keep working. When the deferred part is empty, `DeferredToolSelection` returns the always part unchanged, so a request with only our own servers sends exactly what it sends today. Subagent runs use `DeferredToolSelection` in their own loop (required edit to `add-agent-subagents`).

Alternatives considered:

- `ToolSearchToolCallingAdvisor` as it is (rejected: it hides `Skill`, `Task` and our own tools behind the search, so every request would need a search before the model can load a skill).
- A dispatcher tool `mcp_call {name, arguments}` that runs any deferred tool by name (rejected: the model never sees the tool's input schema, so it guesses arguments, the approval gate and the tenant policy would see one tool name instead of the real one, and the tools used list would only say `mcp_call`).
- Extending `skill_search` with a `type` of `tool` (rejected for the search step only: the expansion step needs to find the found tool names in the results, and the library already does that for `toolSearchTool`. The index is still the one capability index, D7).
- The Lucene or vector store index of the library (rejected: a second index next to the capability index, which already has tenant and policy filtering, provider separation, sync and the text fallback).

Prompt cache: the tool list of a request grows by the tools found, so the first model call after a search starts a new cache entry for the tool part. The always part and the search tool come first in a fixed order, so every request whose model does not search keeps identical tool bytes. This is the trade the Tool Search Tool makes by design, and the saving it reports is 34 to 64 percent of tokens (https://spring.io/blog/2025/12/11/spring-ai-tool-search-tools-tzolov). Task 4.6 measures the tool definition size of a request with fake outside servers of 20, 60 and 120 tools, with and without search.

### D7: Tool entries in the capability index

This change registers one `CapabilitySource` of type `tool` (required edit to `add-agent-skills`: the type set gains `tool`, and a tool entry may be tenant-keyed). For an entry without a tenant, its entries are global, one per exposed tool of a search server, with entry key `global//<prefixed name>`. For a tenant-scoped run-time entry (D10), the key is `<tenantId>//<prefixed name>` and only that tenant's searches see it. `source` is the server id, and the embedded text is `<prefixed name> (<server title>): <description>`, the description cut to 1024 characters. The server title is the `serverInfo.title` the server reports, or its id.

The source publishes the full list of its entries after every listing that changed it: at startup after the first listing, after a reconnect, after `McpToolsChangedEvent`, and after a run-time entry is added or removed. `CapabilityIndexSync` does the rest, with its retries, pending entries and metrics (`capability.index.sync{type="tool"}`). A server that goes `FAILED` keeps its entries, because the allowed keys of a request come from the request's own tool list, which holds no tool of a failed server. An entry of an inactive module and a removed run-time entry lose their entries at the next sync.

Global tool entries hold no tenant id, so tenant erasure in `add-agent-skills` D17 has nothing to delete for them. Tenant-keyed tool entries are deleted with the tenant like every other tenant-keyed entry.

### D8: Default modes, reviews and approval metadata

`McpToolModeDefaults` gives, for a prefixed tool name, the default mode and the approval metadata. The mode is the entry's override for the original tool name when one exists, else the mode an entry source gives for that tool (the owner's tool reviews of `add-self-built-integrations`, which are remembered rules of kind `integration_tool_review` of `add-action-approvals`, owner answer 89.4 of 2026-10-08), else the entry's `default-mode`. `McpToolModeDefaults` implements the source interface that `add-action-approvals` reads (required edit there), so the deployment default approval list is `app.policy.default.approval-required-tools` plus every MCP tool whose default mode is `requires_approval`, and the metadata of an MCP tool comes from its server entry or its source. The metadata of an MCP tool comes only from its server entry or its source, because `add-action-approvals` has no per tool metadata block of its own any more (answer 93 of 2026-10-08).

A review of a configured outside server is the owner writing an override with `mode: allowed` for a tool he has read. A tool without an override keeps asking, so a tool that appears after an upgrade asks first. The contract test of D12 fails when an override names a tool the pinned image no longer lists.

Our own servers are `trust: internal` and default to `allowed`, as today.

### D9: Background retry of failed servers

The requirement (a `FAILED` connection is retried in the background, returns when it answers, and the banner shows the current state) is part of the `mcp-startup-resilience` delta of `add-deployment-modules`, and the component is its `McpReconnectScheduler` (its D19 and task 4.8) with `app.mcp.reconnect.interval` (default 60 seconds). This change creates no scheduler and no second retry. It reuses that component:

- A configured entry of an active module is a Spring AI connection like any other, so `McpReconnectScheduler` retries it unchanged.
- A run-time entry (D10) is recorded in `McpClientStatusRegistry` with its client like a configured connection. This change extends `McpReconnectScheduler` so it also retries a `FAILED` run-time entry of `RuntimeMcpClientRegistry`, under the same per server gate, and bounds each attempt by the entry's `init-timeout` when one is set (required edit 4 of `add-deployment-modules` to this change asks for exactly this).
- On success the tool source of D7 publishes the server's tools, because `CONNECTED` changes the connected set.
- A server of an inactive module has no connection and no registry entry, so it is never retried.

`mcp.server.connected` shows the current state.

### D10: Run-time entries and tenant scope

Server entries come from `McpServerEntrySource` beans. `ConfigurationMcpEntrySource` returns the entries of `app.mcp.servers` and is the only source of the derived Spring AI connection list (D1). A run-time source, such as `IntegrationMcpEntrySource` of `add-self-built-integrations`, adds and removes entries while the agent runs through `McpServerRegistry.add(entry)` and `remove(id)`.

Several agent instances run at once (owner answer 87 of 2026-10-08, CANON 26.1), and each keeps its own MCP clients, so a run-time entry must reach every instance. A run-time source keeps its entries in its own shared store and lists them through `McpServerEntrySource.entries()`. `McpServerRegistry.add` and `remove` apply the change on the calling instance and send `pg_notify('mcp_runtime_entries', <source name>)` in the caller's transaction, through the one `PostgresNotificationListener` of `add-keycloak-login` (its D20). The registry registers a `PostgresNotificationHandler` for the channel `mcp_runtime_entries`, and on every instance that handler reads `entries()` of the named source again and connects, replaces or closes its own clients until they match. Its `onReconnect()` does the same for every run-time source, because a notification sent while the listener was disconnected is lost, and every instance does it once at startup before it reports ready. So an entry added on one instance is connected on every instance within one notification, and no instance keeps a client of a removed entry.

For a run-time entry the agent builds the `McpSyncClient` itself with a `WebClientStreamableHttpTransport` and the same customizers (D3), keeps it in `RuntimeMcpClientRegistry`, records its state in `McpClientStatusRegistry`, and publishes `McpToolsChangedEvent` so `FilteredToolCallbackProvider` lists its tools. `McpClientAutoConfiguration` is not replaced, so `mcp-startup-resilience` holds. A run-time entry is refused when its `trust` is `internal`, so the service token and `_meta` never reach a server that a run-time source added.

A run-time entry may carry a `tenant`. Its tools are offered only to requests and runs of that tenant, its prefix must be unique among the configured entries and the entries of that tenant, and its tool entries in the capability index are tenant-keyed (D7). An entry may also carry `metric-server-tag`, which replaces its id in the `server` tag of the MCP metrics, so the tag stays bounded when many run-time entries exist (`add-self-built-integrations` sets `integration`). A run-time entry belongs to the module of its source (`self-built-integrations`), so the module switch removes all of them.

Per tool modes of a run-time entry come from its source (D8), so an owner review stored by the source reaches the approval defaults the same way as a configured override.

### D11: Compose layout and the shared egress proxy

This change ships one compose service:

| Service | Image | Profiles | Networks | Ports | Secrets in its environment |
|---|---|---|---|---|---|
| `mcp-egress-proxy` | Smokescreen image of `add-agent-sandbox` (`infra/sandbox/egress-proxy/`) | none, always on from this change onward (owner answer 76.5 of 2026-10-08) | the internal network of each outside server that needs the internet, and `default` | none | none |

Rules every outside server container follows, written once in the `mcp-tool-server-deployment` spec and in `docs/MCP_SERVERS.md`:

- Its compose services carry the profile of its module, so `COMPOSE_PROFILES` starts the container and `ASCEND_MODULES` turns on its entry.
- It sits on its own network `mcp-<id>-net` with `internal: true`. The agent joins it. The egress proxy joins it only when the server needs the internet. A server that needs no internet has no route out.
- A server that needs the internet sets `HTTPS_PROXY` and `HTTP_PROXY` to the proxy. The proxy runs Smokescreen in ACL mode `open`, which allows any public host and keeps its default refusal of private, loopback, link-local and other internal ranges (required edit to `add-agent-sandbox`: its entrypoint accepts an `open` mode next to its host list).
- `read_only: true`, `tmpfs` for scratch, `security_opt: ["no-new-privileges:true"]`, `cap_drop: [ALL]`, a non-root `user` where the image allows it, memory and CPU limits, a healthcheck, the logging anchor of `harden-cloud-deployment`, and an image pinned by version and digest.
- Its secrets come from the root `.env` and are passed only to that container, or to the agent when the agent sends them as headers.

`mcp-egress-proxy` follows the rules of `harden-cloud-deployment` (build group 3, position 4): it publishes no port, runs with `no-new-privileges:true` and the logging anchor of `compose.yaml`, takes its secrets from `.env`, and mounts no Docker socket.

`mcp-egress-proxy` carries no `profiles` key, so it starts in every deployment from this change onward, like the always-on core of `add-deployment-modules` D0 (owner answer 76.5 of 2026-10-08: our own tool servers are always on, so their proxy is too). `ComposeModuleConsistencyTest` of `add-deployment-modules` treats it as a core service, which has no profile. `add-openclaw-plugin-host` adds its own use of it later: its `apps` containers reach it through their internal network and the proxy variables (its task 8.4), and it adds no profile to it.

### D12: Tests

- Unit tests for the properties validation, the derived connection list, the prefix and length rules, exposure, the result cap, the `_meta` converter, the default modes, `DeferredToolSelection` and `CapabilityToolIndex`.
- A fake MCP server for tests: the one fake MCP server class of the agent's test sources that `close-agent-test-gaps` task 4.2 writes on the MCP Java SDK server transport (owner answer 91.2 of 2026-10-08), started in-process on a random port with tools defined per test. This change writes no fake MCP server of its own: it adds to that class, in its own task, the switches it needs (down, slow initialise, a tools change notification, an error result, a long result, and capture of request headers and `_meta`), and the test image `ascend-e2e-fake-mcp:local` packages the same class. Integration tests start the agent against two or three fakes: prefixing and collision, header sent and hidden, empty header recorded `FAILED`, `_meta` sent only to the internal fake, a down server that comes back through the background retry, deferred tools found by search and called, a gated tool that waits for approval, an excluded tool never callable, and a run-time entry added, tenant-scoped and removed without a restart.
- A generic contract test helper, `McpServerContractCheck`, for any change that pins an outside image: start the image with Testcontainers, list its tools, assert every override and include name exists, and assert every tool not marked read only has a default mode other than `allowed`. `add-openclaw-plugin-host` uses the same rule for its app plugins.
- End-to-end coverage (owner request of 2026-10-04: every planned change carries end-to-end tests, deterministic Bruno tests wherever no AI model is needed). One new spec in `apps/ascend-agent/e2e/`, with the next free number at implementation time:
  - A deterministic spec, `<N>-mcp-tool-server-registration`, that needs no AI model. It uses the shared e2e harness of `close-agent-test-gaps` (owner answer 67.1 of 2026-10-04), which starts only for deterministic tests, never for AI-run e2e specs (owner answer 70.4 of 2026-10-04): the fake MCP server image `ascend-e2e-fake-mcp:local`, run as the container `e2e-fake-mcp`, with its call log, and the scripted model (Mockoon, the container `e2e-scripted-model` at `http://e2e-scripted-model:3000`, answering the OpenAI chat completion format with a fixed tool call per `E2E-SCRIPT <name>` marker), reached through the agent's own provider `scripted`, never through `lmstudio`. The agent reads the e2e overlay only in the deterministic phase, which copies it into the running agent as `/app/config/application.yaml` and restarts the agent, with no test line in `compose.yaml` (owner answer 98.1 of 2026-10-08, `close-agent-test-gaps` D7). This change replaces the overlay's hand-written connection to the fake, which it would refuse at startup, with two catalog entries of its own format that both point at the one shared fake `e2e-fake-mcp` (owner answers 82.1 and 82.2 of 2026-10-08): `e2e-fake` (no module, so always on, `trust: external`, `url` `http://e2e-fake-mcp:7032`, `endpoint` `/external`) and `e2e-fake-internal` (no module, `trust: internal`, the same `url`, `endpoint` `/internal`). The fake serves the same tools on both endpoint paths and records the endpoint path of every call (`close-agent-test-gaps` D5), so the spec reads one call log through `127.0.0.1:7032` and proves that only the calls on `/internal` carry the `_meta` keys. No second fake container runs, and no catalog entry of the shipped configuration is added for a test. It proves the background retry through `mcp_server_connected`, the prefixed name, the header and the `_meta` rule through the fake's call log, the approval wait, approve and deny of an unreviewed tool, the excluded tool, the result cap counter and the per server timer. It also proves tool search: the scripted model calls `toolSearchTool`, and its request log (Mockoon `GET /mockoon-admin/logs`) shows that the first model call held the search tool and no `e2efake_` tool, and the next call held the found `e2efake_read_canary`.
  - No AI-run spec. Ruling 13.5 of 2026-10-05 (answer 70.4): an AI-run spec never uses the fake MCP server, so the tool search check would have to run against our own real MCP servers. Every own server stays `discovery: always` (owner answer 65.19 of 2026-10-04), and an AI-run spec runs with the shipped profile, so no own server is ever found through search, and an AI-run spec cannot express the check. The search check is therefore deterministic, through the scripted model of the shared harness.
  - The harness (fake image, scripted model, overlay and the copy step of the deterministic phase) is owned and built by `close-agent-test-gaps` (build group 3, position 1). This change reuses it, adds its script rules in the shared Mockoon environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json` and reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/mcp-tool-servers/`, and, because its prefix rule renames every MCP tool, updates in place the scripts, Bruno requests and specs of the earlier changes that name a fake tool without its prefix (owner answer 67.2 of 2026-10-04: a changed feature updates its existing specs). Before running either spec, the runner asks the owner which scenario of `docs/E2E_RUN_SCENARIOS.md` to use.
  - Not provable end to end, and proven by the integration tests above instead: the startup refusals (a hand-written connection, a stdio entry, a shared prefix), because each needs the agent restarted with a broken configuration, the 64 character name rule, the empty header recorded `FAILED`, the run-time entries, which `add-self-built-integrations` proves end to end, and the container rules of `mcp-tool-server-deployment`, because this change ships no outside server container. `add-openclaw-plugin-host` proves them end to end for the `openclaw-apps` container.

### D13: Metering, metrics and logs

- Metering: every successful call of a tool of a server with `metered: true` records one usage event through `UsageEventPort` of `add-deployment-modules` (its company extension ports), naming the request type `mcp-tool`, the server id (or its `metric-server-tag`) and the prefixed tool name. A failed call records none. The default `NoOpUsageEventPort` does nothing. `add-usage-metering-and-quotas` (company, build group 5) registers its implementation later, which writes one ledger row of the new request type `mcp-tool` with the prefixed tool name in a new nullable `tool` column (required edit there, task 7.1 moved there in the dependency fix of 2026-10-05). This change does not wait for it.
- Metrics, following `add-observability` D2 and D5: `mcp.tool.duration{server,tool,outcome}` (existing timer, new `server` tag), `mcp.tool.result.truncated{server}`, `mcp.server.connected{server}`, `mcp.tool.search{outcome}` and `mcp.tool.deferred`. The `tool` tag is bounded by the exposed tools of the configured servers. A run-time entry with `metric-server-tag` uses that tag, and its tools are tagged `tool=<metric-server-tag>` too, so self-built tools add no tag values. No tenant tag.
- Logs: the lines of the specs. Arguments and results only at DEBUG. Header values never.
- Banner: the `MCP servers:` block of `mcp-startup-resilience` as `add-deployment-modules` defines it (one line per connection of an active module, `[Connected]` or `[FAILED]`, and no line for a server of an inactive module). This change adds, per connected entry, its discovery mode and exposed tool count on the same line, and one line with the number of run-time entries.

## Risks / Trade-offs

- [A tool result carries injected instructions, for example a mail that tells the model to forward the inbox] → The system prompt already treats tool results as data, every tool of an outside server asks the owner first until reviewed, and the approval preview shows the exact arguments.
- [An outside server changes its tool list in an upgrade] → Images are pinned by digest, the contract test fails on renamed tools, and a tool without an override asks first.
- [An outside server reaches an internal service] → Its network is internal, it shares it only with the agent and the proxy, and the proxy refuses private addresses.
- [The model does not search and misses a tool] → The library's system message suffix tells the model to search, the always part keeps our own tools visible, and `discovery: always` is one line per entry.
- [Moving the main chat into an advisor loop changes how tools run] → The same `TrackingToolCallingManager` runs every call, and the existing chat executor tests run unchanged against the new loop.
- [A run-time source adds a server that impersonates an internal one] → A run-time entry can never be `trust: internal`, so it never receives the service token or `_meta`.

## Migration Plan

1. Land at build group 4, position 6 of the owner build order of 2026-10-04, after `close-agent-test-gaps`, `upgrade-spring-boot-4`, `add-keycloak-login`, `add-deployment-modules`, `add-shared-scheduler`, `add-agent-skills`, `add-agent-subagents`, `add-agent-sandbox`, `add-agent-soul` and `add-action-approvals`, and use the required edits to `add-agent-skills`, `add-agent-subagents` and `add-action-approvals`, which are made in those changes. `add-tenant-policy` and `add-usage-metering-and-quotas` (company, build group 5) register their parts later, and no task here waits for them.
2. Deploy with the current `COMPOSE_PROFILES`: our own servers behave as before except the three renamed web-hunter tool names and the excluded `health` tool.
3. Outside servers arrive with the changes that add them (`add-openclaw-plugin-host`, `add-self-built-integrations`) or as an entry the owner writes.
4. Rollback: deploy the previous image. There is no data to move.

## Required edits to other changes

This change does not edit any other change. Each edit must be made in the named change. On 2026-10-03 every edit below was checked against the named change and is made there, so each section says so. The changes that land earlier carry their edit already, and no task here waits for a company change.

### `add-deployment-modules`

Edits 1 and 2 are made in that change (checked 2026-10-03: its D3 catalog names none of the five reserved modules and neither secret, and its edit 3 to this change, which since owner answer 76.5 of 2026-10-08 says that `mcp-egress-proxy` is always on with no profile).

1. Design D3: the five reserved module names `mcp-google`, `mcp-github`, `mcp-home-assistant`, `mcp-browser` and `mcp-files` are removed from the catalog, because this change ships no specific outside server (owner decision of 2026-10-02). Their agent secrets `GITHUB_MCP_TOKEN` and `HOME_ASSISTANT_TOKEN` go with them.
2. Design D3 and its edit 3 to this change: `mcp-egress-proxy` is not a catalog companion and carries no module profile. It is always on from this change onward (owner answer 76.5 of 2026-10-08).
3. Its required edits 1 to 5 to this change are applied here: `app.mcp.modules`, `APP_MCP_MODULES` and `app.modules.connections` are gone, `module` is optional on every entry and an entry with no module is always on (owner answer 90 of 2026-10-08, which replaced the mandatory field with its `e2e` profile exception), and the agent reads `ASCEND_MODULES` (edits 1, 2 and 5). `mcp-egress-proxy` carries no profile and is always on (owner answer 76.5 of 2026-10-08), `add-openclaw-plugin-host` adds its own use of it later, and no specific outside server module exists (edit 3, D11). `McpReconnectScheduler` is reused and only extended for run-time entries, and a server of an inactive module has no connection, no registry entry and no banner line (edit 4, D9 and D13).

### `add-agent-skills`

Edits 1 to 4 are made in that change (checked 2026-10-03, its D3, D14, D18, D19 and its row for this change). Since the dependency fix of 2026-10-05 the code that adds the type `tool`, the two-part result of `ChatToolset` and the `skill_search` sentence is this change's task 4.8 (moved from `add-agent-skills` task 10.9).

1. Design D18 and `specs/agent-capability-index/spec.md`: the entry type set is `skill`, `subagent` and `tool`. A tool entry is global or tenant-keyed. A search of one type never returns another type.
2. Design D14: the `type` tag of `capability.index.sync` and `capability.index.pending` has three values.
3. Design D3: `ChatToolset` returns the request's tools as two parts, always and deferred, from the server entry of each MCP tool. Agent native tools are always in the always part. Tools of a tenant-scoped entry are offered only to that tenant.
4. Design D19: the `skill_search` description gains one sentence that tools are found with `toolSearchTool`, so the model does not search tools with `skill_search`.

### `add-agent-subagents`

Edits 1 and 2 are made in that change (checked 2026-10-03, its D8, D9 and its row for this change). Since the dependency fix of 2026-10-05 the code that makes `RunLoop` call `DeferredToolSelection` and accept prefixed and deferred tool names is this change's task 4.9 (moved from `add-agent-subagents` task 6.9).

1. Design D8: the run tool loop calls `DeferredToolSelection` of this change before each model call, so a run gets the always part, the search tool and the tools it found.
2. Design D9: a definition's `tools` list names prefixed MCP tool names, and may name a deferred tool, which the run offers from its first model call.

The deferred tool rules of the requirement "A subagent never has more tools than its parent" and its scenario "A definition names a tool found only by search" are this change's MODIFIED delta `specs/subagent-execution/spec.md`, which copies the full requirement of `add-agent-subagents` and adds them (review item 6, owner answer 75.1 of 2026-10-07). `add-agent-subagents` lands earlier and is archived first.

### `add-action-approvals`

Edits 1 and 2 are made in that change (checked 2026-10-03, its D1 and D2).

1. Design D1: the deployment default approval list is `app.policy.default.approval-required-tools` plus the tools a registered `ApprovalDefaultsSource` marks. This change's `McpToolModeDefaults` is one such source, fed by configured entries and by run-time sources.
2. Design D2: the sentence that the default list holds no MCP tool changes. Every tool of a `trust: external` entry is `requires_approval` until an override or a source review says otherwise (`mcp-tool-servers` spec), and the per tool metadata of an MCP tool comes from its server entry, never from both places.

### `add-tenant-policy`

Company, build group 5, registers its part later. Edits 1 and 2 are made in that change (checked 2026-10-03, its D2 and its `tool-policy` requirement "Server entries, own integrations and a deny list" with the scenario "The deny list wins over a server entry"). The task that supports them in the policy filter is that change's own (moved from this change's task 5.2 in the dependency fix of 2026-10-05).

1. Design D2: tool names are the prefixed names. An allow-list entry may be `server:<id>`, which allows every exposed tool of that server, and a new deny list of tool names removes tools from an allowed server. A tool on the deny list is `denied` whatever the allow-list says.
2. `specs/tool-policy/spec.md`: a requirement for `server:<id>` entries and the deny list with scenarios.

### `add-keycloak-login`

Edit 1 moved from `add-auth-and-identity` to `add-keycloak-login` with the split of 2026-10-04 (its D6, its task 6.3 and its `service-authentication` requirement "ascend-ai-agent attaches the service token on all outbound calls", checked 2026-10-04). Because `add-keycloak-login` lands first, it attaches the token to every MCP connection configured then (all of them our own servers), and this change makes the rule below true in its own task 5.3.

1. The token is sent to every MCP connection whose entry has `trust: internal` and never to an entry with `trust: external`, through the customizer of this change's D3.

### `add-usage-metering-and-quotas`

Company, build group 5, registers its `UsageEventPort` implementation later. Edit 1 is made in that change (checked 2026-10-03, its D12 row `mcp-tool`, its D14 `tool` column in `V<n>__usage_ledger_tool.sql` and its `usage-metering` scenario for one `mcp-tool` row). The task that writes the row is that change's own (moved from this change's task 7.1 in the dependency fix of 2026-10-05).

1. Design D12 and `specs/usage-metering/spec.md`: a request type `mcp-tool`, one row per successful call of a tool of a server with `metered: true`, `provider` set to the server id or its metric tag, and a new nullable `tool` column holding the prefixed tool name, added in its own Flyway migration.

### `add-agent-sandbox`

Made in that change (checked 2026-10-03, its D6 and its task 10.7).

1. Design D6: the egress proxy image is also used by `mcp-egress-proxy` of this change. Its entrypoint accepts `ALLOWED_HOSTS=*`, which writes an ACL with mode `open` and keeps the private address refusal.

### `add-coding-agent-delegation`

Made in that change (checked 2026-10-03, its section "Applied here from other changes").

1. Design Context line 9, the D3 paragraph that compares with "the fine-grained personal access token of `add-mcp-tool-servers`", and its required edit to this change: this change no longer ships a GitHub MCP server or `GITHUB_MCP_TOKEN`, so those sentences are removed. Its own GitHub App token stays as it is. Its required edit 1 to this change has nothing left to change here.

### Applied here from other changes

- `add-file-download` edit 1 (now used by `add-download-ingestion`): the `_meta` forwarding of `tenant_id` and `request_id` to `trust: internal` entries (D3, spec requirement "Our own servers receive the tenant and the request in `_meta`").
- `add-file-download` edit 2: `request-timeout: 330s` on the `ascend-web-hunter` entry (D1).
- `add-file-download` edit 3: the `web_download_*` tools keep their names (D4).
- `add-self-built-integrations` edits 1 to 4: entry sources and run-time entries (D10), tenant-scoped entries and the `server` metric tag (D10, D13), tenant-keyed tool entries (D7), and per tool modes from a source (D8).
- `add-deployment-modules` edits 1 to 5 (see that section above).
- `add-download-ingestion` (the agent part of `add-file-download`, split of 2026-10-04): the per tool override `tools.overrides.<tool>.module` (D1, D5), which it sets to `web-download` on each `web_download_*` tool of the `ascend-web-hunter` entry in its own change (its task 1.1).

### Checked, no edit needed

- `upgrade-spring-boot-4`: this change uses the Spring AI 2.0.1 modules its BOM manages and the two customizer types its D11 names, `McpClientCustomizer<WebClientStreamableHttpTransport.Builder>` for headers, base URL and response timeout and `McpClientCustomizer<McpClient.SyncSpec>` for the request timeout (checked 2026-10-03).
- `add-chat-streaming-and-conversations`: `DeferredToolCallingAdvisor` overrides the stream hooks of `ToolCallingAdvisor` too, so a streamed turn finds tools the same way.
- `harden-cloud-deployment`: the egress proxy follows its rules as written (no published port, `no-new-privileges`, secrets in `.env`).
- `add-customer-stack-installer`: outside server secrets are customer inputs, never generated, the rule it already has for connector credentials.
- `add-openclaw-plugin-host`: its `openclaw-apps` entry uses the generic mechanism of this change as written.

## Decision record numbering

The monorepo record for D2 takes the next free number in `docs/architecture/decisions/`, and the agent record for D6 takes the next free number in `apps/ascend-agent/docs/architecture/decisions/`, both at implementation time.

## Owner decisions of 2026-10-06

Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores. This change adds no stored data and needs none of today's data.

## Owner decisions of 2026-10-07

Answer 75.1: the owner approved the fix of every item of the review of the group 3, 4 and 5 changes of 2026-10-07. Fixed here: item 5 (`mcp-egress-proxy` names no module profile in this change, `add-openclaw-plugin-host` adds `openclaw-apps`), item 6 (this change carries the deferred tool rules of `add-agent-subagents` as the MODIFIED delta `specs/subagent-execution/spec.md`) and item 24 (the overlay entry `e2e-fake` has no module and is accepted only under the profile `e2e`, owner answer 72.5 of 2026-10-06, superseded by owner answer 90 of 2026-10-08: an entry with no module is always on in every profile).

## Owner decisions of 2026-10-08

Answer 76.1: the overlay test user of task 8.2 is `frostyMcpToolServersScriptedTest`, created by task 8.2, the task that uses it. The tool search check of task 8.3 runs in the same spec as the same user.

Answer 76.5: `mcp-egress-proxy` is always on from this change onward, because our own tool servers are always on. It carries no compose profile (D11, task 6.1 and `specs/mcp-tool-server-deployment/spec.md`), and `add-deployment-modules` states it as a service with no profile. `add-openclaw-plugin-host` still adds its own use of it (its task 8.4) and adds no profile to it. This replaces the follow-up of item 5 of 2026-10-07, which left the profile list for `add-openclaw-plugin-host` to fill.

Answer 76.2: the scripted model of the shared harness of `close-agent-test-gaps` is Mockoon (the `mockoon/cli` image, pinned by version and digest). This change adds its script rules to the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json`, which holds every rule of every change, and keeps its reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/mcp-tool-servers/` (D12, tasks 8.1 and 8.3, spec `mcp-tool-servers`). Every check that read the request journal now reads the scripted model's request log, `GET /mockoon-admin/logs` of the Mockoon admin API, and clears it with `POST /mockoon-admin/state/purge`.

Approved fix of 2026-10-08: every deterministic spec of this change that runs a scripted chat turn wipes in AscendMemory the memories of its users in its Reset state and Post-run cleanup (`POST /api/v1/memory/wipe` with the provider `openai` and the service token), because the memory extraction of a scripted turn embeds through the scripted model into `ascend_memory_1536` (task 8.2). (Superseded by answer 91.1 below.)

Answer 79.2: the shared harness containers of `close-agent-test-gaps` are `e2e-fake-mcp` (the fake MCP server, at `http://e2e-fake-mcp:7032` on the stack's network, the port set by answer 81.1 below) and `e2e-scripted-model` (the scripted model, at `http://e2e-scripted-model:3000`). The catalog entry `e2e-fake` of task 8.1 points at `e2e-fake-mcp`, and the spec of task 8.2 removes and starts that container by this name.

Answer 81.1: the fake MCP server `e2e-fake-mcp` listens on port 7032 in the container and is published as `127.0.0.1:7032`, so the catalog entry `e2e-fake` of task 8.1 points at `http://e2e-fake-mcp:7032`, and Bruno reads its call log at `http://127.0.0.1:7032/e2e/calls` (tasks 8.1 and 8.2). When the spec of task 8.2 starts `e2e-fake-mcp` again, it uses the `docker run` shape of `close-agent-test-gaps` (network `ascend-ai_default`, `-p 127.0.0.1:7032:7032`).

Answer 81.3: the scripted model is published as `127.0.0.1:7033`, so the request log checks of tasks 8.2 and 8.3 read `GET http://127.0.0.1:7033/mockoon-admin/logs` from the host, and containers keep using `http://e2e-scripted-model:3000`.

Answer 81.4: the second fake container, earlier `ascend-e2e-fake-mcp-internal`, is renamed `e2e-fake-mcp-internal`. It listens on port 7036 in the container, stays on its internal network and publishes no port, so the catalog entry `e2e-fake-internal` points at `http://e2e-fake-mcp-internal:7036` (D12, tasks 8.1, 8.2 and 8.4). Superseded by answers 82.1 and 82.2 below.

Answer 81.3, addition (mandatory): every host and port of this change follows the rules of `close-agent-test-gaps` D8, so the plan works on Linux Docker Engine, where `host.docker.internal` does not resolve by itself. Checked on 2026-10-08: the agent reaches the fake and every outside server by container or service name on a shared network (rule 1), Bruno reads the call log of `e2e-fake-mcp` on `127.0.0.1:7032` (rule 2), no outside server container gets `extra_hosts`, because none may reach the host, and the egress proxy check of `specs/mcp-tool-server-deployment/spec.md` now also names the host's address on the default bridge, because on Linux the name `host.docker.internal` does not resolve inside a container that has no `extra_hosts` line, so a refused request by that name alone proves nothing there (task 6.1). The `localhost` addresses in the example of D1 are the host run of `application.yaml`, where the agent runs on the host. The container addresses come from `application-docker.yaml` (task 1.3).

Answers 82.1 and 82.2 (the owner called the earlier design overengineered and not best practice): there is only one fake MCP server, `e2e-fake-mcp`, on port 7032, published as `127.0.0.1:7032`. The second fake `e2e-fake-mcp-internal`, its closed network and its catalog entry pointing at it are removed everywhere. The `trust: internal` against `trust: external` test registers the one fake twice in the test catalog of the e2e overlay, `e2e-fake` under the endpoint path `/external` and `e2e-fake-internal` under `/internal`, and the spec reads the call log through `127.0.0.1:7032` to prove that only the internal entry got the `_meta` keys (D12, tasks 8.1, 8.2 and 8.4). The production rule for outside tool servers (own internal network, egress proxy when needed, D11 and `specs/mcp-tool-server-deployment/spec.md`) stays. Only the test changes.

Answer 82.3: there is no `FAKE_MCP_PORT` setting. Port 7032 is written into the fake MCP server's own test image (`close-agent-test-gaps` D5), and no real service or its configuration gets anything for tests.

Answer 85.1: every key and secret lives in the repository `.env`, never in the shell. Header secrets of an outside server come from `.env` through placeholders (D3), and the deterministic phase sets only `SPRING_PROFILES_ACTIVE` in the shell (task 8.2). (Replaced by answer 98.1 below: the phase copies the overlay into the running agent and sets nothing in a shell.)

Answer 87 (rule R1, CANON 26.1): several agent instances run at once. Checked: every instance keeps its own MCP clients and its own `McpReconnectScheduler` retries, which is correct per instance (a local `@Scheduled` task of `add-deployment-modules`, answer 89.3), the tool listing cache is per instance and per MCP session with its TTL, and the deferred tool index lives for one request on one instance. Changed: run-time entries reach every instance through the channel `mcp_runtime_entries` of the one `PostgresNotificationListener` of `add-keycloak-login`, and each instance re-reads the run-time sources on a notification, on a reconnect of the listener and at startup (D10, task 1.4). New name: the channel `mcp_runtime_entries` and the method `McpServerEntrySource.entries()`, sent to `add-self-built-integrations` through `inbox93/add-self-built-integrations__from__add-mcp-tool-servers.md`.

Answer 88 (rule R2): every company plug-in point stays: the `tenant` field of a run-time entry, `metric-server-tag`, `server:<id>` for `add-tenant-policy`, `UsageEventPort` metering, and the exclude placeholder that `add-customer-stack-installer` adds.

Answer 89.1: `StreamingChatExecutor` of `add-chat-streaming-and-conversations` is the one chat executor, and this change adds `DeferredToolCallingAdvisor` to it once, for the blocking and the streaming endpoint alike (D6, task 4.5).

Answer 89.4: the owner's tool reviews of a self-built integration are remembered rules of kind `integration_tool_review` of `add-action-approvals`, read through that change's entry source, so `McpToolModeDefaults` reads them as before through the source (D8).

Answer 90: the `module` field of a server entry is optional, an entry with no module is always on, and no profile changes the rule. The `e2e` profile branch is removed, which replaces answer 72.5 for the module rule (D1, D12, tasks 1.1, 1.2 and 8.1, `specs/mcp-tool-servers/spec.md`). The two overlay entries `e2e-fake` and `e2e-fake-internal` name no module and exist only in the overlay file.

Answer 91.1: the deterministic spec of task 8.2 runs in the deterministic phase of `close-agent-test-gaps` D7, where the agent's semantic memory points at the AscendMemory fake under `/ascend-memory/` of `e2e-scripted-model`. AscendMemory is never restarted, there is no dummy key, and the spec wipes no memories (task 8.2). Answer 91.2: the fake MCP server of the integration tests and of the test image is the one class of `close-agent-test-gaps` task 4.2, which this change extends with its switches instead of writing `FakeMcpServer` of its own (D12, task 2.1).

Answer 91.3: checked, this change has one deterministic spec and no AI-run spec, and the spec proves the live MCP connection, the prefix, the header and `_meta` rules, the default gating of an outside tool, the exclusion, the cap, the metrics and the tool search, which no lower test proves against the live stack. Nothing is removed.

Answer 93: the setting `AUDIO_TOOLS_EXCLUDE` with its one value is replaced by the literal `health` (D1), and the refusal of a tool described both under `app.approvals.tools` and in a server override is gone with that block (D8, task 5.1). Not applied, because each would cut a company plug-in point or a feature: the `tenant` field of a run-time entry and `metric-server-tag` (R2, company), and `mcp-egress-proxy` (answer 76.5).

Answer 98 (the configuration rule, CANON 31.11 to 31.13): every value of this change with a default is a setting read from the environment, written `${ENV:default}` in `application.yaml` (and in `application-docker.yaml` where the container value differs), with the same default in the bound record and a `- ENV=${ENV:-default}` line on the `ascend-agent` service. Made external: the three server addresses `APP_MCP_SERVERS_ASCENDWEATHERMCP_URL`, `APP_MCP_SERVERS_ASCENDWEBHUNTER_URL` and `APP_MCP_SERVERS_ASCENDAUDIOSCRIBE_URL` (the compose default is the container address of `application-docker.yaml`, the `application.yaml` default the `localhost` address of a host run, the same pattern as `harden-cloud-deployment` task 3.2), `APP_MCP_SERVERS_ASCENDWEBHUNTER_REQUESTTIMEOUT` (`330s`), `APP_MCP_DISCOVERY_MAXRESULTS` (`5`) and `APP_MCP_DISCOVERY_SCORETHRESHOLD` (`0.4`) (D1, tasks 1.1 and 1.3). Not bound here a second time: `app.mcp.reconnect.interval` (`APP_MCP_RECONNECT_INTERVAL`, `60s`) of `add-deployment-modules`, and the existing `app.mcp.startup.init-timeout` (`5s`) and `app.mcp.tool-cache.ttl` (`60s`). The exclude list `health` of `ascend-audio-scribe` stays a literal by answer 93, and `add-customer-stack-installer` turns it into its setting `AUDIO_TOOLS_EXCLUDE` (its Answer 98). The per entry values of an outside server (`init-timeout`, `request-timeout`, `max-result-chars`, its URL and headers) are written by whoever adds that entry, as placeholders in the same form. Kept as constants, because they are not operational: the 64 character tool name limit (the limit model providers set for a tool name), the 1024 character cut of a tool description in the capability index (the format of the stored index entry), the tool name prefixes, the `_meta` keys `ascend.ai/tenant_id` and `ascend.ai/request_id`, the trust values and their default modes, the channel `mcp_runtime_entries`, the metric names, the Smokescreen ACL mode `open`, and the test values (the fake's port 7032, the 1 second test interval, the 20, 60 and 120 tool fakes of task 4.6, the canary). `mcp-egress-proxy` has no setting of its own. Rows go to `apps/ascend-agent/docs/CONFIGURATION.md` in the same commit as each setting (task 6.4). No test or measurement of this change uses LM Studio: every scripted turn goes through the provider `scripted`, never `lmstudio` (task 8.1, checked in round 98). This change plans no deployment of several agent copies, so no text names `plan-scaled-deployment`.

Answer 98.1: there is no test line in `compose.yaml` and no `e2e` profile. The overlay entries `e2e-fake` and `e2e-fake-internal` reach the agent only through the copy of the deterministic phase, which restarts only the agent and recreates it from its image at the end (`close-agent-test-gaps` D7). D12 and tasks 1.1, 1.2, 8.1, 8.2 and 8.5 no longer name the `e2e` profile, `SPRING_PROFILES_ACTIVE=docker,e2e` or an overlay mount.

Answer 98.2: the fake MCP server is the one new test class of `close-agent-test-gaps` task 4.2, packaged as `ascend-e2e-fake-mcp:local`, confirmed. This change extends it with its switches (task 2.1) and runs the image as `e2e-fake-mcp` (task 8.2).

## Open Questions

These do not change the specs or the tasks.

1. Closed (owner answer 65.19 of 2026-10-04): our own stack's tool servers (ascend-web-hunter, ascend-memory, ascend-ocr, ascend-audio-scribe and ascend-weather-mcp) stay always listed in every request with `discovery: always`, and are never found by search. The agent may use the whole own stack normally. `discovery: search` stays the default only for outside servers (`trust: external`).
2. Closed (ruling 13.5 of 2026-10-05): the tool search check is part of the deterministic spec of D12 through the scripted model, and this change has no AI-run spec (D12).
3. Closed (owner answers 82.1 and 82.2 of 2026-10-08): there is no second fake container and no internal test network. Both catalog entries point at `e2e-fake-mcp` under the endpoint paths `/external` and `/internal`.
4. Closed (owner answers 82.1 and 82.2 of 2026-10-08): the spec reads the one call log at `http://127.0.0.1:7032/e2e/calls` and tells the internal calls from the external ones by their endpoint path.
