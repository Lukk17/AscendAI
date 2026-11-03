## Purpose

Sets the rules for running an outside MCP server next to the agent: its own container switched on by its deployment module, isolated from the agent's secrets and from the internal services, reaching the internet only through the shared egress proxy, with every secret in the environment file and a contract test for every pinned image.

## ADDED Requirements

### Requirement: An outside server runs in its own container under its module

Every outside MCP server that runs in the compose stack SHALL run in its own container whose compose services carry the profile of the server entry's module, so one name in `COMPOSE_PROFILES` starts the container and, through `ASCEND_MODULES`, turns on the entry. With the module not in `COMPOSE_PROFILES`, `docker compose up` SHALL start none of its containers and the agent SHALL offer none of its tools. No outside server SHALL run inside the agent process or in a sandbox workspace of `add-agent-sandbox`.

#### Scenario: Module off

- **WHEN** the stack starts and the module of an outside server is not in `COMPOSE_PROFILES`
- **THEN** its container does not run and none of its tools is offered

#### Scenario: Module on

- **WHEN** the module is added to `COMPOSE_PROFILES` and `docker compose up -d` runs
- **THEN** its container runs, the agent connects to it, and its tools are offered through tool search

### Requirement: Outside server containers are hardened and hold only their own secrets

Every outside server container SHALL run from an image pinned by version and digest, as a non-root user where the image allows it, with `no-new-privileges`, every capability dropped, a read-only root file system with tmpfs for scratch, CPU and memory limits, a healthcheck, and only its own secrets in its environment. No outside server container SHALL receive a provider key, a database password, the service token or any secret of another server. A server that speaks only stdio SHALL run behind a pinned stdio to Streamable HTTP bridge inside its own container.

#### Scenario: Secrets are separated

- **WHEN** two outside server containers run
- **THEN** the environment of each holds no secret of the other and no provider key
- **AND** the environment of the agent holds no secret that only an outside container needs

### Requirement: Outside servers cannot reach internal services

Each outside server container SHALL sit on its own internal network shared only with the agent and, when it needs the internet, the shared egress proxy `mcp-egress-proxy`. It SHALL publish no port, and SHALL reach the internet only through the egress proxy, which refuses private, loopback, link-local and Docker internal addresses. A server that needs no internet SHALL have no route out at all. The egress proxy SHALL carry no compose profile and SHALL start in every deployment, whichever modules are active.

#### Scenario: The egress proxy is always on

- **WHEN** `docker compose config` runs with an empty `COMPOSE_PROFILES`
- **THEN** the service `mcp-egress-proxy` is in the configuration and carries no `profiles` key

#### Scenario: Internal address refused

- **WHEN** a process in an outside server container requests `http://ascend-agent:9917/api/v1/approvals`, `http://host.docker.internal:6333` or port 6333 on the host's address on the default bridge network through the proxy
- **THEN** the request is refused and nothing reaches the address

#### Scenario: Outside server cannot reach another outside server

- **WHEN** a process in one outside server container connects to another outside server container
- **THEN** the connection fails, because the two containers share no network

### Requirement: Secrets live in the environment file only

Every secret an outside server needs SHALL be set only in the root `.env` file and passed by compose to the one container that uses it, or to the agent when the agent sends it as a header. `.env.example` SHALL list every such variable with an empty value and one line on where to get it. No secret SHALL be written into `application.yaml`, a compose file, an image or a log line.

#### Scenario: Example file complete

- **WHEN** a change adds an outside server with a secret
- **THEN** `.env.example` lists the variable with an empty value and one line on where to get it

### Requirement: Each pinned outside server keeps the tool list the configuration expects

For each outside server image pinned in the stack, a contract test SHALL start the image, list its tools, and fail when a tool named in that server's overrides or include list no longer exists, or when a tool that the server marks as not read only would get the default mode `allowed`.

#### Scenario: Upgrade renames a tool

- **WHEN** a new pinned version of an outside server renames a tool that an override names
- **THEN** the contract test fails and names that tool
