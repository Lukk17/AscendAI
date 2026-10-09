## Purpose

Lets the assistant turn a need for a new outside connection into a tested MCP server image, by describing the integration, having a coding agent write it from a fixed template, and checking it in the sandbox before anything runs.

## ADDED Requirements

### Requirement: The model can start an integration build with one tool

The agent SHALL offer the tool `integration_build` to the main chat only, and only when the deployment module `self-built-integrations` is active, the tenant has it, and the `TenantToolPolicy` port of `add-agent-subagents` allows it (its default allows every tool). Its input SHALL be: `slug` (3 to 24 characters of lower case letters and digits, starting with a letter), `title` (at most 80 characters), `purpose` (at most 2000 characters), `api_notes` (at most 20000 characters, the outside API as the model understood it), `destinations` (at least one entry, each a host name and a purpose), `credentials` (any number of entries, each a name, a kind `bearer`, `header` or `basic`, a header name for kind `header`, the destination host it is sent to, and a purpose), and `tools` (at least one entry, each a name of lower case letters, digits and `_`, a description and an effect `read`, `write`, `message`, `money` or `delete`). The tool SHALL start a background run of kind `integration` and return the run id and the integration id at once. A refusal SHALL be a tool result naming the reason, never an HTTP error of the chat request.

#### Scenario: Build started

- **WHEN** the model calls `integration_build` with slug `quotes`, one destination `api.quotes.example`, no credential and one read tool `get_quote`
- **THEN** the tool result holds a run id and an integration id
- **AND** `GET /api/v1/runs/{run id}` shows a run of kind `integration` in state `waiting` or `running`

#### Scenario: Not offered to subagents

- **WHEN** a subagent run lists its tools
- **THEN** none of the five integration tools is in the list

#### Scenario: Invalid destination refused

- **WHEN** the model passes the destination `10.0.0.5`
- **THEN** the tool result refuses it with `invalid_destination`, because a destination is a public host name and never an IP literal, `localhost`, a single label name or a wildcard

#### Scenario: Credential for an undeclared host refused

- **WHEN** a credential names the host `api.other.example`, which is not one of the declared destinations
- **THEN** the tool result refuses the build with `credential_host_not_declared`

### Requirement: Builds are not limited in number, only serialized for safety

The agent SHALL NOT limit the number of integrations of a tenant, the number of builds per day, or the cost or time of a build. It SHALL refuse a new build with a tool result only when the slug is already used by another integration of the tenant or equals the tool prefix of a configured MCP server, or when a build of the same integration is still running. Running builds of the deployment SHALL be bounded by the safety bound `app.integrations.safety.max-running-builds` (default 1, maximum 2), and further builds SHALL wait in arrival order with no limit on how many wait. Both rules SHALL hold when several agent instances run at once.

#### Scenario: Many builds in one day

- **WHEN** a tenant has started 20 builds today and the model calls `integration_build` again with a new slug
- **THEN** the tool result holds a run id, and the build waits in arrival order until the running build ends

#### Scenario: Slug taken by a configured server

- **WHEN** the model asks for slug `weather` and a configured MCP server uses the prefix `weather`
- **THEN** the tool result refuses with `slug_taken`

### Requirement: The code is written by a coding run from a fixed template, never by the assistant

An integration build SHALL hand all code writing to a coding run of `add-coding-agent-delegation`. The coding run SHALL start from a seed folder that holds the fixed template and, for an update, the integration's current source, and SHALL get the build request as its task text. Its network SHALL reach only the model provider through its gateway and the Python package index hosts in `app.integrations.build.network.allow`, never a declared destination of the integration. It SHALL get no integration-specific cost or time limit and SHALL run under the run settings of `add-coding-agent-delegation` unchanged. Its result SHALL never be published to any git host.

#### Scenario: Coding run cannot reach the outside system

- **WHEN** the generated tests or the coding agent try to open `https://api.quotes.example`
- **THEN** the request fails inside the coding workspace and nothing reaches that host

#### Scenario: Coding run fails

- **WHEN** the coding run ends `failed`
- **THEN** the integration run ends `failed` with reason `CODING_AGENT_ERROR`, and no image is built

### Requirement: The result is checked against the request before it is kept

After the coding run ends, the agent SHALL accept its new commits into the tenant's integration repository only when every changed path is inside the integration's own folder and matches the template's allowed paths, no file is a symbolic link, a hard link or a device, no file is larger than the safety bound `app.integrations.safety.build.max-file-bytes` (default 1 MiB), the folder is at most the safety bound `max-source-bytes` (default 5 MiB), and the manifest `integration.yaml` names exactly the slug, the destinations, the credentials and the tools of the build request with the same effects. A destination, credential or tool that the request did not declare SHALL make the build fail with `manifest_mismatch`, and nothing of that coding run SHALL be kept.

#### Scenario: Coding agent adds a destination

- **WHEN** the generated manifest lists `collector.evil.example` besides the declared destination
- **THEN** the integration run ends `failed` with reason `INTEGRATION_VERIFY_FAILED` and detail `manifest_mismatch`
- **AND** the tenant's integration repository has no new commit

### Requirement: Generated source is versioned in a git repository per tenant

Each tenant SHALL have one git repository at `<app.agent-home>/tenants/<tenantId>/integrations/`, with one folder per integration named by its slug. Every accepted version SHALL be one commit with the trailers `Integration-Id`, `Integration-Version`, `Integration-Run` and `Coding-Run`, and the version number SHALL increase by one for each accepted version of that integration. A version rejected by a later check SHALL stay in the history and be marked rejected in the version record, and SHALL never be used for an image.

#### Scenario: Two versions

- **WHEN** an integration is built and later updated, and both pass every check
- **THEN** the repository holds two commits for its folder with `Integration-Version` 1 and 2

### Requirement: Dependencies are installed without running package code

Extra Python packages SHALL be listed in `requirements.lock` with an exact version and at least one SHA-256 hash per package, and SHALL be installed in a fresh sandbox workspace whose network reaches only the hosts in `app.integrations.build.network.allow`, as binary wheels only, with hash checking on. A lock with a package without a hash, a URL, a path, a version range, a package the runtime image already provides, or an installed size above the safety bound `max-dependency-bytes` (default 50 MiB) SHALL fail the build with `dependency_refused`. The number of packages SHALL NOT be limited.

#### Scenario: Source distribution refused

- **WHEN** a locked package has no binary wheel for the runtime platform
- **THEN** the build fails with `dependency_refused` and no `setup.py` of any package was run

### Requirement: Tests and a fixed contract check run in the sandbox with no network

The agent SHALL run the generated tests and the contract check in a fresh sandbox workspace of profile `integration-verify` with no network, holding exactly the source and dependency archives that will go into the image. The tests SHALL pass with no failure and no error, and at least one test SHALL exist per declared tool. The contract check SHALL be a program of the verify image, not of the generated source, and SHALL start the server, require `/health` to answer 200, connect over Streamable HTTP, and require that the listed tools equal the declared tools by name, that each has a description of 1 to 1024 characters and an input schema of type `object`, that `readOnlyHint` is true exactly for tools of effect `read`, that `destructiveHint` is true for tools of effect `delete`, and that the server lists no resources and no prompts. A failure SHALL end the run `failed` with reason `INTEGRATION_VERIFY_FAILED` and a detail naming the first failed check.

#### Scenario: Undeclared tool found

- **WHEN** the server lists a tool `run_shell` that the manifest does not declare
- **THEN** the run ends `failed` with detail `contract_tool_list_mismatch`, and the version is marked rejected

#### Scenario: Tests cannot reach the network

- **WHEN** a generated test opens a connection to any host
- **THEN** the connection fails inside the workspace

### Requirement: The image holds exactly the tested files and is built without running code

The image SHALL be assembled by the sandbox runner from the same source and dependency archives that passed the checks, compared by SHA-256, on top of the pinned runtime image, without starting any container and without running any build step. The runner SHALL refuse an archive that holds a symbolic link, a hard link, a device, a path outside its root, a set-user-id or set-group-id bit, more than `max-entries` entries or more than `max-bytes` bytes. The image SHALL stay on the engine of the deployment and SHALL never be pushed to a registry. The agent SHALL never hold the Docker socket.

#### Scenario: Archive changed after the checks

- **WHEN** the source archive sent to the runner has a different SHA-256 than the one that passed the checks
- **THEN** the agent does not send it, and the run ends `failed` with detail `archive_changed`

#### Scenario: Symbolic link refused

- **WHEN** an archive sent to `POST /v1/images` holds a symbolic link
- **THEN** the runner answers 400 with code `archive_refused` and no image is created

### Requirement: Build runs are measured and logged

The agent SHALL count builds started in `integration.builds.started` tagged `trigger` (`build` or `update`), finished builds in `integration.builds.finished` tagged `outcome` and `stage`, and their time in the timer `integration.build.duration` tagged `outcome`. Each stage change SHALL write one INFO line with the tenant, the integration id, the version and the stage, and never the API notes, the task text or any source file, which SHALL appear only at DEBUG.

#### Scenario: Failed build counted

- **WHEN** a build fails in the contract check
- **THEN** `integration.builds.finished` has a sample with `outcome=failed` and `stage=verify`
