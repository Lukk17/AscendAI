## Purpose

Lets the agent connect any number of MCP servers, ours and outside ones, each described by one entry that decides how it is reached, which of its tools the model may use, under which names, in which tool mode, and how its calls are bounded, measured and logged.

## ADDED Requirements

### Requirement: Each MCP server is one entry, and the connection list is derived from it

The agent SHALL read every configured MCP server from one entry under `app.mcp.servers.<id>`, where `<id>` is lower case letters, digits and `-`, at most 32 characters. An entry SHALL hold: `module` (optional, a module name of the deployment module catalog), `transport`, `url`, `endpoint`, `headers`, `trust` (`internal` or `external`), `tool-prefix`, `tools.include`, `tools.exclude`, `discovery` (`always` or `search`), `default-mode` (`allowed` or `requires_approval`), per tool entries under `tools.overrides.<original tool name>` with `mode`, `category`, `rememberable`, `scope-arguments` and `module`, `init-timeout`, `request-timeout`, `max-result-chars` and `metered`. When not set, `default-mode` SHALL be `requires_approval`, `discovery` SHALL be `search` and `metered` SHALL be `true` for `trust: external`, and `allowed`, `always` and `false` for `trust: internal`. The Spring AI connection entries SHALL be derived from the configured entries whose module is active and from every entry with no module, and the application SHALL refuse to start when `spring.ai.mcp.client.streamable-http.connections` holds an entry that no server entry produced. Adding a server SHALL need no code change. An entry with no `module` SHALL be accepted in every profile and SHALL always be connected.

#### Scenario: A new server is added by configuration only

- **WHEN** the owner adds an entry `app.mcp.servers.notes` with `module: notes`, `transport: streamable-http`, `url: http://notes-mcp:8000` and `tool-prefix: notes`, `notes` is in `ASCEND_MODULES`, and the agent restarts
- **THEN** the agent connects to it, lists its tools with the prefix `notes_` and offers them to the model
- **AND** no Java source file changed

#### Scenario: A hand-written connection is refused

- **WHEN** `application.yaml` holds `spring.ai.mcp.client.streamable-http.connections.extra.url` and no server entry `extra`
- **THEN** the application refuses to start with a message naming `extra` and the property `app.mcp.servers`

#### Scenario: Entry without a module is always on

- **WHEN** an entry has no `module`, under any Spring profile and whatever `ASCEND_MODULES` holds
- **THEN** the application starts and the entry is connected

### Requirement: A server is on exactly when its deployment module is active

A configured server SHALL be connected only when its `module` is in `app.modules.active`, which is bound from `ASCEND_MODULES`. A server whose entry names no module SHALL always be connected. A server of an inactive module SHALL have no derived connection and SHALL offer no tool. No other flag SHALL switch a configured server on or off. A tool whose override sets `module` SHALL be offered, indexed and callable only while both the entry's `module` and the tool's `module` are active, SHALL count as a tool of its own `module` for the tenant's module grants, and SHALL otherwise be treated like an excluded tool. The application SHALL refuse to start when an override names a module that the catalog does not know.

#### Scenario: Module off

- **WHEN** the entry `notes` has `module: notes` and `ASCEND_MODULES` does not list `notes`
- **THEN** no connection to the `notes` server is made and no `notes_` tool is offered

#### Scenario: Tool of an inactive per tool module

- **WHEN** the `ascend-web-hunter` entry has `module: web-search` and the override `web_download_file: { module: web-download }`, and `ASCEND_MODULES` lists `web-search` but not `web-download`
- **THEN** `web_search` is offered and `web_download_file` is neither offered nor callable

### Requirement: Entries can be added and removed at run time by an entry source

Besides the configured entries, an entry source of another change SHALL be able to add and remove entries while the agent runs, without a restart. A run-time entry SHALL be connected over Streamable HTTP with the same header, timeout and result rules as a configured entry, SHALL belong to the module of its source, SHALL be refused when its `trust` is `internal`, and SHALL be retried in the background like a configured entry. A run-time entry MAY name a tenant: its tools SHALL then be offered only to requests and runs of that tenant, its prefix SHALL be unique among the configured entries and the entries of that tenant, and its tool entries in the capability index SHALL be keyed by that tenant. A run-time entry MAY name a metric tag that replaces its id in the `server` tag of the MCP metrics. Per tool modes and approval metadata of a run-time entry SHALL come from its source. Removing a run-time entry SHALL close its client, withdraw its tools from the next request and remove its tool entries from the capability index. When several agent instances run, an entry added or removed on one instance SHALL be connected or closed on every instance, through a notification in the shared database and a fresh read of the entry source on each instance.

#### Scenario: Run-time entry added

- **WHEN** an entry source adds an entry `int-quotes` for tenant `a` with prefix `quotes`
- **THEN** the next request of tenant `a` can find `quotes_get_quote` through tool search without a restart
- **AND** no request of tenant `b` can find or call it

#### Scenario: Run-time entry reaches every instance

- **WHEN** two agent instances run and an entry source adds an entry on the first
- **THEN** the second instance connects the entry and offers its tools without a restart
- **AND** after the source removes it on the first, the second instance closes its client

#### Scenario: Run-time entry with internal trust refused

- **WHEN** an entry source adds an entry with `trust: internal`
- **THEN** the entry is refused and no connection is made

#### Scenario: Run-time entry removed

- **WHEN** the source removes the entry `int-quotes`
- **THEN** the next request of tenant `a` has no `quotes_` tool and a search finds none

### Requirement: The agent connects to MCP servers over Streamable HTTP only

The agent SHALL connect to every MCP server over Streamable HTTP. The application SHALL refuse to start when a server entry has a `transport` other than `streamable-http`, or when any `spring.ai.mcp.client.stdio` or `spring.ai.mcp.client.sse` connection is configured, with a message saying that a stdio server runs in its own container behind a bridge. No MCP server process SHALL ever be started by the agent.

#### Scenario: Stdio entry refused

- **WHEN** a server entry sets `transport: stdio`
- **THEN** the application refuses to start and the message names the entry and the rule

#### Scenario: No child process

- **WHEN** the agent has started with every configured server connected
- **THEN** the agent process has started no child process

### Requirement: Every MCP tool name carries its server prefix

The name the model sees for an MCP tool SHALL be `<tool-prefix>_<original name>`, after the existing replacement of characters outside `[a-zA-Z0-9_-]`. When the original name already starts with `<tool-prefix>_`, it SHALL not be prefixed again. Every server SHALL have a non-empty `tool-prefix` made of letters, digits and `_`, and two configured servers SHALL NOT share a prefix, or the application refuses to start. A name longer than 64 characters SHALL be shortened to its first 55 characters, `_` and the first 8 hex characters of the SHA-256 of the full name, with one WARN line naming both. A call to a prefixed name SHALL reach the original tool on its own server. The tools `session_establish`, `session_status` and `session_clear` of ascend-web-hunter SHALL be offered as `web_session_establish`, `web_session_status` and `web_session_clear`, and the `health` tool of ascend-audio-scribe SHALL be excluded.

#### Scenario: Two servers with the same tool name

- **WHEN** the servers `notes` (prefix `notes`) and `tasks` (prefix `tasks`) both offer a tool `search`
- **THEN** the model sees `notes_search` and `tasks_search`, and a call to `tasks_search` reaches the `tasks` server

#### Scenario: Prefix not doubled

- **WHEN** the server `ascend-weather-mcp` with prefix `weather` offers `weather_current`
- **THEN** the model sees `weather_current`

#### Scenario: Shared prefix refused

- **WHEN** two configured entries both set `tool-prefix: web`
- **THEN** the application refuses to start and the message names both entries

### Requirement: Only the exposed tools of a server reach the model

A tool of a server SHALL be offered only when `tools.include` is empty or names it, and `tools.exclude` does not name it, by original name. Excluded tools SHALL never be offered, never be indexed and never be callable, also not through a stored approval.

#### Scenario: Excluded tool cannot be called

- **WHEN** the `notes` server excludes `delete_all` and the model asks for `notes_delete_all` by name
- **THEN** the tool is not in the tool list and the call is answered as an unknown tool

### Requirement: Headers, timeouts and the result cap apply per server

Each connection SHALL send the headers of its entry. A header value SHALL come from the environment through a placeholder, SHALL never be logged, and SHALL never appear in the banner, a metric or an error body. An entry of an active module whose header resolves to an empty value SHALL not be connected, SHALL be recorded `FAILED`, and SHALL produce one WARN line naming the entry and the header name. The `init-timeout` of an entry SHALL bound its initialisation instead of `app.mcp.startup.init-timeout` when set, and its `request-timeout` SHALL bound each of its tool calls instead of `spring.ai.mcp.client.request-timeout` when set. The `ascend-web-hunter` entry SHALL set a `request-timeout` of at least the web-hunter's download timeout plus 30 seconds (330 seconds at the defaults). A tool result longer than `max-result-chars` SHALL be cut to that length and end with one line saying it was cut and how long it was.

#### Scenario: Token header sent and hidden

- **WHEN** the entry `notes` sets the header `Authorization: Bearer ${NOTES_MCP_TOKEN}` and the model calls `notes_search`
- **THEN** the request to the `notes` server carries that header
- **AND** no log line, banner line or metric contains the token value

#### Scenario: Empty token

- **WHEN** the module of `notes` is active and `NOTES_MCP_TOKEN` is empty
- **THEN** the agent starts without trying to connect to `notes`, records it `FAILED`, and writes one WARN line that names the header

#### Scenario: Long result cut

- **WHEN** `max-result-chars` is 20000 and a tool returns 90000 characters
- **THEN** the model receives the first 20000 characters and a final line saying the result was cut from 90000 characters

### Requirement: Our own servers receive the tenant and the request in `_meta`

For every tool call to a server whose entry has `trust: internal`, the agent SHALL put the tool context values `tenant_id` and `request_id` into the MCP `_meta` object of the call as `ascend.ai/tenant_id` and `ascend.ai/request_id`. For a server whose entry has `trust: external`, the agent SHALL send neither key. The model SHALL have no way to set or change `_meta`.

#### Scenario: Internal server gets the tenant

- **WHEN** a request of tenant `a` calls `web_search`
- **THEN** the call to ascend-web-hunter carries `_meta` with `ascend.ai/tenant_id` `a` and the request's id

#### Scenario: Outside server gets nothing

- **WHEN** the same request calls `notes_search` of a `trust: external` entry
- **THEN** the call carries no `ascend.ai/tenant_id` and no `ascend.ai/request_id`

### Requirement: The service token goes only to our own servers

The bearer service token of `add-keycloak-login` SHALL be sent only to servers whose `trust` is `internal`. A server whose `trust` is `external` SHALL never receive it, and the application SHALL refuse to start when an external entry names the service token in its headers.

#### Scenario: Outside server never sees the service token

- **WHEN** the service token is configured and the model calls a tool of a `trust: external` server
- **THEN** the request to that server carries no service token

### Requirement: Each tool has a default mode, and outside tools ask first until reviewed

The deployment default tool mode of an MCP tool SHALL be the `mode` of its override when one exists, else the mode its entry source gives for it, else its entry's `default-mode`. A tool whose default mode is `requires_approval` SHALL be in the deployment default approval list of `add-action-approvals`, with the `category`, `rememberable` and `scope-arguments` of its override or source. The same tool SHALL NOT also be described under `app.approvals.tools`, or the application refuses to start. Every tool of a `trust: external` entry without an override or a source review SHALL be `requires_approval`. The shipped entries `ascend-weather-mcp`, `ascend-web-hunter` and `ascend-audio-scribe` SHALL be `trust: internal` with default mode `allowed`.

#### Scenario: Unreviewed outside tool waits for the owner

- **WHEN** the model calls a tool of a `trust: external` entry that no override names
- **THEN** the call does not run and an approval request is created

#### Scenario: A new tool after an upgrade asks first

- **WHEN** an outside server adds a tool that no override names
- **THEN** its default mode is `requires_approval`

#### Scenario: Reviewed tool runs

- **WHEN** the owner sets the override `search_notes: { mode: allowed }` on the `notes` entry and the model calls `notes_search_notes`
- **THEN** the call runs at once

### Requirement: MCP tool calls are measured and logged per server

Every MCP tool call SHALL be recorded in the `mcp.tool.duration` timer with the tags `server`, `tool` and `outcome`, and every cut result SHALL increase the counter `mcp.tool.result.truncated` tagged `server`. An entry with a metric tag SHALL use it for `server` and for `tool`. Every call SHALL write one INFO line with the server, the prefixed tool name, the outcome, the duration and the result length, and never the arguments or the result, which SHALL appear only at DEBUG. A connection state change SHALL write one line naming the server and the new state. The gauge `mcp.server.connected` tagged `server` SHALL read 1 for a connected server and 0 otherwise.

#### Scenario: Call measured

- **WHEN** the model calls `notes_search` and it succeeds
- **THEN** `mcp.tool.duration` has a sample tagged `server=notes`, `tool=notes_search`, `outcome=ok`
- **AND** the INFO line holds no search text

#### Scenario: Server that comes back is visible as connected

- **WHEN** a configured server is down at startup and starts later
- **THEN** `mcp.server.connected` tagged with that server reads 0 before it starts and 1 within two reconnect intervals after it starts
- **AND** its tools are offered from the next request on

### Requirement: The MCP server behaviour is proven end to end against a live stack

The repository SHALL hold one deterministic end-to-end spec for this capability in `apps/ascend-agent/e2e/testing/`, with its tasks template and its Bruno requests in `docs/api/request/AscendAI/ascend-agent/testing/mcp-tool-servers/`. The deterministic spec SHALL call no chat model: the scripted model of the shared e2e harness, reached through the agent's own provider `scripted`, returns fixed tool calls, and the one fake MCP server of the harness, registered twice in the test catalog under the endpoint paths `/external` (`trust: external`) and `/internal` (`trust: internal`), stands in for an outside server and for one of our own servers, with one readable call log that records the endpoint path of every call. It SHALL prove the background retry, the prefixed name, the header and `_meta` rules, the approval wait with approve and deny, the excluded tool, the result cap, the per server metrics, and that a deferred tool found through tool search is offered to the next model call of the same request. It SHALL pass only on HTTP status, response body, the fake's call log, the scripted model's request log, Prometheus samples and persisted rows, never on a log line, and it SHALL be listed in the run scenarios of `docs/E2E_RUN_SCENARIOS.md` that the owner chose. No AI-run spec SHALL use the fake MCP server.

#### Scenario: Deterministic run calls no chat model

- **WHEN** the deterministic spec runs with the e2e overlay copied into the running agent
- **THEN** every step passes without a call to any hosted or local chat model, and the only model calls are the embedding calls every prompt already makes

#### Scenario: Unreviewed tool proven gated end to end

- **WHEN** the scripted model calls `e2efake_write_note`, the spec reads the pending approval and approves it with its `argumentsDigest`
- **THEN** the fake's call log shows no write before the approval and exactly one write after it

#### Scenario: Only the internal entry gets the _meta keys end to end

- **WHEN** the scripted model calls `e2efake_read_canary` and `e2efakeint_read_canary`
- **THEN** the fake's call log shows the call on `/internal` with `ascend.ai/tenant_id` and `ascend.ai/request_id` in `_meta`
- **AND** the call on `/external` with neither key

#### Scenario: Deferred tool found by search end to end

- **WHEN** the scripted model calls `toolSearchTool` for "read the canary" and then the tool it found
- **THEN** the first model call held `toolSearchTool` and no `e2efake_` tool, the next held `e2efake_read_canary`, and the answer holds the canary
