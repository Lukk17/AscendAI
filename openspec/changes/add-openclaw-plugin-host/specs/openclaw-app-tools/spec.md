## Purpose

Lets the owner give the assistant apps through OpenClaw tool plugins: the `apps` containers of `ascend-openclaw-host` run the plugins the owner installed, with no OpenClaw agent, and offer their tools to Ascend's agent as an outside MCP server whose tools ask first until the owner reviews them.

## ADDED Requirements

### Requirement: App plugins run in their own containers with no OpenClaw agent

The `ascend-openclaw-host` image SHALL run app plugins only in containers of the role `apps`, as the compose service `ascend-openclaw-host-apps` and any further `apps` service the owner adds, under the profile of the deployment module `openclaw-apps`. In an `apps` container the generated OpenClaw configuration SHALL enable no channel, no model provider, no provider key, no skill, no memory plugin, no heartbeat, no cron job and no hook, SHALL allow only the plugins named in `OPENCLAW_HOST_APP_PLUGINS`, and SHALL allow only the tools those plugins declare. The host SHALL refuse to start, with one ERROR line naming the setting, when any of these is broken or when a known model provider key variable is set. No OpenClaw agent run SHALL start. No `apps` container SHALL hold a channel token, the host's agent client secret or the pairing pepper, and no `channels` container SHALL hold an app plugin secret.

#### Scenario: Skill enabled

- **WHEN** the generated `apps` configuration would load a skill
- **THEN** the host exits before the gateway starts and the log names the setting

#### Scenario: Secrets are separated

- **WHEN** containers of both roles run
- **THEN** the environment of every `apps` container holds no channel token and no host client secret
- **AND** the environment of every `channels` container holds no app plugin secret

### Requirement: Only owner-installed, pinned app plugins load

Every app plugin SHALL be a dependency of the host module with an exact version in `package.json` and its integrity in the committed lock file, installed into the image at build time. A plugin available only on ClawHub SHALL be checked in as a tarball and referenced as a file dependency. No plugin SHALL be installed while the host runs. The host SHALL refuse to start when `OPENCLAW_HOST_APP_PLUGINS` names a plugin that is not pinned. The repository SHALL keep a contract file with the name and an input schema digest of every tool of every pinned app plugin, and the host's tests SHALL fail when the plugins list a tool that the file does not hold, or a tool whose schema digest differs.

#### Scenario: Unpinned plugin named

- **WHEN** `OPENCLAW_HOST_APP_PLUGINS` names a plugin id that `package.json` does not pin
- **THEN** the host exits before the gateway starts and the log names the plugin id

#### Scenario: Update changes a tool

- **WHEN** an updated plugin version changes the input schema of one of its tools
- **THEN** the app plugin test fails and names that tool

### Requirement: App plugin tools are offered as one MCP server

Every `apps` container SHALL serve a Streamable HTTP MCP endpoint that lists the tools of the allowed app plugins with their names, descriptions and input schemas, and runs each call as one direct tool invocation of the OpenClaw gateway, with no agent turn. The endpoint SHALL keep no session, so any replica of one `apps` service can answer any request, and every replica of one service SHALL list the same tools. The endpoint SHALL refuse every request without the bridge token with 401. A gateway refusal or tool failure SHALL be returned as a tool result with `isError` true and the gateway's sanitized message. The OpenClaw gateway SHALL listen only inside the container, and its token SHALL be its own value, never the one of a `channels` container.

#### Scenario: Tool listed and called

- **WHEN** a pinned plugin declares the tool `quote_get` and the agent calls `openclaw_quote_get` after the owner reviewed it
- **THEN** the bridge runs `quote_get` through the gateway and returns its result, and no OpenClaw agent run starts

#### Scenario: No token

- **WHEN** a client on the agent's network calls the bridge without the bridge token
- **THEN** the answer is 401 and no tool runs

#### Scenario: Any replica answers

- **WHEN** `ascend-openclaw-host-apps` runs two replicas and the agent calls `openclaw_quote_get` several times
- **THEN** every call succeeds whichever replica answers it, and no call fails for an unknown session

### Requirement: The agent connects the bridge as an outside server whose tools ask first

The agent SHALL connect the bridges of one `apps` compose service through one server entry of `add-mcp-tool-servers` whose URL is that service's name, so all of its replicas are behind the one entry: `openclaw-apps` with tool prefix `openclaw` for `ascend-openclaw-host-apps`, and one further entry with its own prefix for each further `apps` service. Every such entry SHALL have module `openclaw-apps`, `trust: external`, discovery `search` and default mode `requires_approval`, and SHALL send the bridge token of its service as a header. Every tool of the entry SHALL ask the owner through the approval gate until the owner reviews it by naming it with mode `allowed` in the entry's overrides. The entry SHALL never receive the service token or the tenant and request ids in `_meta`. With the module off, the entry SHALL not be connected and no `openclaw_` tool SHALL be offered.

#### Scenario: Unreviewed tool waits

- **WHEN** the model calls an `openclaw_` tool that no override names
- **THEN** the call does not run and an approval request is created

#### Scenario: Module off

- **WHEN** `openclaw-apps` is not in `COMPOSE_PROFILES`
- **THEN** no `apps` container of `ascend-openclaw-host` runs and no `openclaw_` tool is offered

### Requirement: App plugins reach only the internet through the egress proxy

Every `apps` service SHALL sit on its own internal network shared only with its own replicas, the agent and the shared egress proxy of `add-mcp-tool-servers`, SHALL publish no port, and SHALL send outside requests only through the proxy, which refuses private, loopback, link-local and Docker internal addresses.

#### Scenario: Plugin cannot reach the agent

- **WHEN** a plugin requests `http://ascend-agent:9917/api/v1/approvals`
- **THEN** the request fails and the agent receives nothing

### Requirement: App tool calls are measured and logged

The host SHALL count app tool calls in `openclaw.host.app.tool.calls` and time them in `openclaw.host.app.tool.duration`, both tagged `tool` and `outcome`, and SHALL gauge the listed tools in `openclaw.host.app.tools.listed`. Every call SHALL write one INFO line with the tool, the outcome, the duration and the MCP request id, and never the arguments or the result, which SHALL appear only at DEBUG. The startup banner of an `apps` container SHALL list the OpenClaw version, every allowed plugin with its version and tool count, and no secret.

#### Scenario: Call counted without arguments

- **WHEN** an app tool call succeeds
- **THEN** `openclaw.host.app.tool.calls` grows by one with `outcome` `ok`
- **AND** the INFO line holds no argument value
