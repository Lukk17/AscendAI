## Purpose

Runs each self-built integration as an isolated, long-lived MCP server that the agent can call, that reaches only approved outside hosts, and that is switched off on its own when it keeps failing.

## ADDED Requirements

### Requirement: Each integration runs in its own isolated container

Each enabled integration SHALL run as exactly one container created by the sandbox runner from its active image, on the gVisor runtime in production, as a non-root user, with every capability dropped, `no-new-privileges`, a read-only root file system, a `/tmp` tmpfs of at most 32 MiB, no host mount, no published port, no secret in its environment, labels or command, and the safety bounds of `app.integrations.safety.container` (defaults 0.25 CPU, 256 MiB memory with no swap, 128 processes, maxima 1.0 CPU, 1024 MiB and 512 processes). The number of running integration containers SHALL NOT be limited, and the memory they reserve SHALL be visible in the banner and the runner metric `sandbox.services.reserved.memory`.

#### Scenario: Container settings

- **WHEN** an integration is enabled and the runner has started its container
- **THEN** an inspect of the container shows the runtime `runsc` under the production profile, a read-only root, no capabilities, no mount from the host, the configured memory and CPU, and no environment variable holding a secret

#### Scenario: No count limit

- **WHEN** 12 integrations run and the owner enables a thirteenth
- **THEN** it starts, and `sandbox.services.reserved.memory` grows by its reserved memory

### Requirement: An integration reaches only approved destinations

An integration container SHALL sit on its own internal network whose only other members are its own egress proxy and its own credential gateway. The proxy SHALL allow exactly the destination hosts approved for that integration through `integration_egress` and SHALL refuse private, loopback and link-local addresses. A change of the approved set SHALL take effect by the next run of the system task `integration-reconcile`, at most one minute later. The integration SHALL never reach the agent, another integration, the runner, an internal service, or the host.

#### Scenario: Unapproved host refused

- **WHEN** the integration sends a request to a host that has no approval for it
- **THEN** the proxy refuses it and the host receives nothing

#### Scenario: Agent unreachable

- **WHEN** the integration tries to open `http://ascend-agent:9917`
- **THEN** the connection fails

### Requirement: Credentials are added by a gateway, outside the integration

A request of the integration that needs a credential SHALL go to its credential gateway, which SHALL add the credential to the request and forward it over TLS only to the credential's one destination host and allowed path prefixes. The credential value SHALL exist only in the gateway's memory-backed folder, and the integration container SHALL never be able to read it.

#### Scenario: Header added outside the container

- **WHEN** the integration calls its gateway route for credential `api_key` and the owner has set the value
- **THEN** the outside host receives the configured header with the value
- **AND** reading every file and every environment variable inside the integration container finds no copy of the value

#### Scenario: Route limited to its host

- **WHEN** the integration asks its gateway to forward a credential to a host other than the credential's destination
- **THEN** the gateway refuses the request

### Requirement: The agent reaches an integration through its gateway only

The agent SHALL reach an integration's MCP endpoint only through the integration's gateway on the internal network `integrations-ingress`, which the agent and the gateways join and no integration container joins. The integration's MCP connection SHALL use Streamable HTTP.

#### Scenario: Integration not on the ingress network

- **WHEN** the networks of an integration container are inspected
- **THEN** its only network is its own internal network

### Requirement: An integration is registered as an outside MCP server whose tools ask first until reviewed

When an integration's container is healthy, the agent SHALL register it without asking the owner as a run-time MCP server entry of `add-mcp-tool-servers` with trust `external`, the server id `int-<slug>`, the tool prefix equal to the slug, discovery `search`, metering on, the module `self-built-integrations`, the metric tag `integration`, and scope limited to the integration's tenant. Its tools SHALL be offered only to requests of that tenant and SHALL be found only through tool search. Every tool SHALL default to `requires_approval`, with the approval category `other` for effect `read` and `write`, `outside_message` for `message`, `spend_money` for `money` and `outside_delete` for `delete`. A tool SHALL become `allowed` only through an owner review of that tool at its current definition digest, which is a remembered rule of kind `integration_tool_review` of the approval service. A tool whose definition digest changed SHALL ask first again until reviewed again. Registration SHALL need no restart of the agent.

#### Scenario: New tool asks first

- **WHEN** the integration `quotes` is registered and the model calls `quotes_get_quote`
- **THEN** the call waits for an approval of category `other` and does not run before the owner approves it

#### Scenario: Reviewed tool runs

- **WHEN** the owner has reviewed `quotes_get_quote` as `allowed` and the model calls it
- **THEN** the call runs at once

#### Scenario: Other tenant never sees it

- **WHEN** a request of another tenant searches tools for "quote"
- **THEN** no tool of the integration `quotes` is returned

### Requirement: Calls before the owner's approvals do not reach the integration

While any declared destination of the active version has no decided `integration_egress` approval, or any declared credential is not granted or the runner reports no value for its variable, a call to a tool of the integration SHALL return a fixed tool result saying that the integration waits for the owner, naming the pending approval ids, and SHALL not reach the integration.

#### Scenario: Waiting for egress

- **WHEN** the egress approval for `api.quotes.example` is pending and the model calls `quotes_get_quote`
- **THEN** the tool result says the integration waits for the owner and names the approval id
- **AND** the integration container receives no request

### Requirement: An integration that keeps failing is disabled automatically

The agent SHALL count, per integration, consecutive tool calls that end in an error, a timeout or a transport failure, and consecutive health checks that fail. When the call count reaches `app.integrations.failure.max-consecutive-calls` (default 5) or the health has failed for `failure.max-unhealthy` (default 5 minutes), the agent SHALL set the integration to `disabled_failing`, stop its container, withdraw its tools, write one WARN line, increase `integration.auto_disabled`, record an audit event, create in the same transaction one owner notification of source `integration` and kind `auto_disabled` with the integration id as its subject for each `ADMIN` of the integration's tenant through the owner notification service, and tell the owner in the next chat turn's finished runs block. A successful call SHALL reset the call count. Only the owner SHALL enable it again.

#### Scenario: Five failures in a row

- **WHEN** five calls to tools of the integration `quotes` in a row end in an error
- **THEN** the integration state is `disabled_failing`, its container is gone, and its tools are not offered
- **AND** each `ADMIN` of the tenant has one notification of source `integration` and kind `auto_disabled` naming the integration

#### Scenario: The model cannot enable it

- **WHEN** an integration is `disabled_failing`
- **THEN** no tool of the model can enable it, and only `POST /api/v1/integrations/{id}/enable` can

### Requirement: Running integrations survive restarts of the agent and the runner

The agent SHALL register the system task `integration-reconcile` of `add-shared-scheduler`, scheduled by `app.scheduler.system-tasks.integration-reconcile.cron` (default `* * * * *`, every minute), so that each firing runs on exactly one agent instance. Each firing SHALL compare the integrations that should run with the integration services the runner reports, start the missing ones, replace the changed ones and stop the ones that should not run. Each agent instance SHALL register and remove the MCP entries of the running integrations in its own memory, at startup, at once when any instance changes a run-time MCP entry, through the Postgres notification channel `mcp_runtime_entries` of `add-mcp-tool-servers`, reading the entries from the shared integration rows, and every `app.integrations.entry-refresh-interval` (default 60 seconds) as a fallback, as local work that never runs on the shared scheduler. The runner's reaper SHALL remove the proxy, gateway and network of an integration only when its integration container is gone, and SHALL never remove a running integration container on its own.

#### Scenario: Agent restart

- **WHEN** the agent restarts while two integrations run
- **THEN** after startup both are registered again without being recreated, and their tools are offered

#### Scenario: Container removed by hand

- **WHEN** an operator removes an enabled integration's container
- **THEN** at the next firing of `integration-reconcile`, at most one minute later, the agent asks the runner to start it again

#### Scenario: Two agent instances

- **WHEN** two agent instances run and an enabled integration's container is missing
- **THEN** one firing of `integration-reconcile` asks the runner to start it once, and after the refresh both instances offer its tools

#### Scenario: Disable on one instance withdraws the tools on every instance

- **WHEN** two agent instances run and the owner disables an integration through the first one
- **THEN** the second instance stops offering its tools before its next 60 second refresh

### Requirement: Integration runtime is measured and logged

The agent SHALL report the gauge `integration.count` tagged `state`, the gauge `integration.containers.running`, the counter `integration.auto_disabled`, and the counter `integration.tool.failures`. The runner SHALL report `sandbox.services.active`, `sandbox.services.restarts`, `sandbox.services.reserved.memory` and `sandbox.images.built` tagged `outcome`. No tag SHALL hold an integration id, a slug, a tenant, a tool name or a host. Tool calls of integrations SHALL be measured by the existing `mcp.tool.duration` with the server tag `integration`.

#### Scenario: Gauge after disable

- **WHEN** one of three running integrations is disabled
- **THEN** `integration.containers.running` reads 2
