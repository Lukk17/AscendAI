## Purpose

Runs OpenCode headless inside a gVisor sandbox workspace that mounts one coding project folder, with a configurable model provider (an OpenCode subscription, an API key, or a local model), with network only to the model provider, the one repository and package registries, with the model key and git token kept out of the workspace, and collects, meters and bounds what it does.

## ADDED Requirements

### Requirement: OpenCode runs from one pinned image built in this repository

Coding workspaces SHALL start only from the configured `coding` image profile, whose image is built in this repository, pinned by digest in the runner configuration, and holds OpenCode at an exact pinned version together with the build tools the image lists. OpenCode SHALL be the only coding agent. The image SHALL NOT download or update OpenCode or its model list at run time. A tool call SHALL never choose an image. The image SHALL be scanned and SHALL hold no set-user-id binary, the same as the runner's base image.

#### Scenario: The pinned version runs

- **WHEN** a coding run starts
- **THEN** the version OpenCode reports is the version pinned in the image build file
- **AND** the workspace made no request to a package registry or release host to install or update OpenCode

#### Scenario: No update check

- **WHEN** a coding run ends
- **THEN** the egress proxy and gateway logs of that workspace show no request to an update, share or model list address of OpenCode

### Requirement: OpenCode runs headless and never waits for a person

OpenCode SHALL be started with no terminal, with its task text given by the agent and never by the repository, with a machine readable event stream as its output, in a mode where every action it is allowed to take runs without asking and every other action is refused at once, so it never waits for an answer. Its own web fetch and web search tools, its share feature, its sub tasks and its questions SHALL be off. Project files of the repository that configure OpenCode SHALL NOT widen what it may do, use, or reach. OpenCode SHALL be told, in text added by the agent, the run's limits, that it must not push, that it works on a branch the agent created, and that it must end with a summary of what it changed and how it tested it.

#### Scenario: OpenCode runs unattended

- **WHEN** a coding run starts
- **THEN** OpenCode edits files and runs commands without any prompt
- **AND** the run's last step shows its tool use within the poll interval

#### Scenario: A repository config cannot widen the rules

- **WHEN** the repository holds an OpenCode config file that allows `webfetch` and adds a provider pointing at an outside host
- **THEN** `webfetch` stays denied, the outside host is not reachable from the workspace, and the run uses only the provider the agent chose

#### Scenario: OpenCode does not block on a question

- **WHEN** OpenCode asks for a permission that is not allowed in a coding run
- **THEN** the request is refused at once and the run goes on

### Requirement: The model provider is configurable and a subscription is used only by its owner

The provider of a coding run SHALL be one of `opencode-go`, `opencode-zen`, `anthropic`, `openai`, `gemini`, `minimax` and `lmstudio`, chosen from the tool input, else the tenant's default, else the deployment's default. Each provider SHALL be reached only through the run's credential gateway at that provider's fixed upstream and paths, and `lmstudio` at the address the operator listed. The model SHALL be checked against the provider's configured model list and then through the shared model access policy port of the deployment modules capability, whose default allows every provider the deployment has enabled, the coding providers included while the module `coding` is active. The key SHALL come from the provider key port of this capability, whose default returns the deployment's key when the deployment allows that provider to use it, and no key otherwise. A registered implementation of either port SHALL replace its default with no change to this capability. The deployment's key of the subscription provider `opencode-go` SHALL be allowed only in a deployment with one tenant, and the agent SHALL refuse to start when that rule is broken. When the provider answers that its usage limit is reached, the run SHALL end `failed` with reason `PROVIDER_LIMIT` and its result SHALL say so.

#### Scenario: Personal deployment uses the subscription

- **WHEN** the owner's personal deployment has the OpenCode subscription key configured and a coding run starts with no provider in the tool input
- **THEN** the run uses provider `opencode-go` through the gateway with the owner's key

#### Scenario: Local model

- **WHEN** a coding run starts with provider `lmstudio` and the operator listed the LM Studio address
- **THEN** OpenCode's model requests reach LM Studio through the gateway, and no key is used

#### Scenario: Subscription key in a multi-tenant deployment

- **WHEN** the agent starts with more than one tenant configured and `opencode-go` allowed to use the deployment key
- **THEN** the agent does not start and the log names the setting

#### Scenario: Subscription limit reached

- **WHEN** the provider answers a model request of a running coding run with its usage limit error
- **THEN** the run ends `failed` with reason `PROVIDER_LIMIT`

### Requirement: A coding workspace reaches only the gateway and the allowed package registries

A coding workspace SHALL have no network except: its own credential gateway, and the egress proxy of its workspace with the configured host allow-list for package registries. The model provider and the git host SHALL be reached only through the gateway, never through the egress proxy. The gateway SHALL forward only the configured paths of each route, SHALL forward git requests only for the project's one repository, and SHALL refuse every other path with 403. The workspace SHALL NOT reach the agent, the runner, the container engine socket, another workspace, a private, loopback or link-local address, or a host that is not on the allow-list.

#### Scenario: Allowed registry

- **WHEN** a command in a coding workspace installs a package from `registry.npmjs.org`, which is on the allow-list
- **THEN** the install succeeds through the egress proxy

#### Scenario: Model provider only through the gateway

- **WHEN** a command in a coding workspace connects to `opencode.ai` through the egress proxy
- **THEN** the proxy refuses it

#### Scenario: Another repository through the gateway

- **WHEN** a command in a coding workspace clones `owner/other-repo` through the gateway
- **THEN** the gateway answers 403 and no request reaches the git host

#### Scenario: Not the agent and not the socket

- **WHEN** a command in a coding workspace connects to the agent's service name, to the runner, or to the engine socket over TCP 2375
- **THEN** each connection fails

### Requirement: Secrets never enter the workspace or the project folder and never reach the result

The model provider key and the git token of a run SHALL be held only by that run's credential gateway, in a memory-backed file inside the gateway container, written there by the runner and readable only by the gateway process. They SHALL NOT be passed to the gateway or the workspace as environment variables, labels or command arguments, SHALL NOT be written to the project folder (no OpenCode credential file), and SHALL NOT be stored by the runner. The workspace SHALL hold only a fixed placeholder key that the gateway replaces. The gateway SHALL NOT log request or response headers or bodies. The agent SHALL check every stored result file and every progress text for the exact secret values of the run, and SHALL replace any found value with a fixed marker and log one WARN line, before anything is stored.

#### Scenario: Workspace has no secret

- **WHEN** a command in a coding workspace prints its environment, reads `/proc/*/environ` of every process it can see, and searches `/workspace` and `/tmp` for the run's model key and git token
- **THEN** neither value is found

#### Scenario: Gateway hides the key

- **WHEN** the runner's container inspect output of the gateway container is searched for the model key
- **THEN** the key is not found in its environment, labels or command

#### Scenario: A leaked value is redacted

- **WHEN** a test OpenCode binary writes the run's git token value into its summary
- **THEN** the stored summary holds the marker in place of the value and one WARN line is logged

### Requirement: The clone uses a read-only token for one repository

On the first run of a repository project, before OpenCode starts, the agent SHALL mint a git host token limited to the project's one repository with read access to its contents and to its metadata, and nothing else, and SHALL clone the base branch, or the repository's default branch when none is given, through the gateway into the project folder. The agent SHALL then create the project's work branch, whose name the server made. A later run of the same project SHALL start on that work branch and SHALL require a clean work tree. For a new project the agent SHALL create an empty repository in the project folder with an initial empty commit and no remote, and SHALL mint no token.

#### Scenario: Clone of the default branch

- **WHEN** the first coding run for `owner/app` with no base branch starts
- **THEN** the project folder holds a clone of the repository's default branch on a new local branch named with the configured prefix and the project id

#### Scenario: New project

- **WHEN** the first coding run for a new project starts
- **THEN** the project folder holds an empty git repository with one empty commit and no remote, and no git token was minted for the run

### Requirement: Cost, tokens and time are counted and bounded inside a run

The agent SHALL read OpenCode's event stream while it runs and SHALL count, per model, input tokens, output tokens, cache read and cache write tokens, and the cost. The counted cost SHALL be the larger of the cost OpenCode reports and the cost the agent computes from the counted tokens with the one price table. The agent SHALL stop OpenCode when the counted cost reaches the run's cost limit or when the run's deadline passes. The agent SHALL also pass a step limit from the run's limits to OpenCode. The gateway SHALL refuse model requests above the configured request rate per minute of a run with 429, so the spend between two polls stays bounded. The OpenCode process SHALL be stopped at the deadline even when it ignores its own limits, and the workspace SHALL be destroyed no later than the deadline plus the configured grace time.

#### Scenario: OpenCode ignores its budget

- **WHEN** a test OpenCode binary keeps sending model requests after the run's cost limit is reached
- **THEN** the agent stops it, the run ends `failed` with reason `COST_LIMIT`, and the workspace is destroyed within the grace time

#### Scenario: Request rate at the gateway

- **WHEN** a test OpenCode binary sends model requests faster than the configured rate of a run
- **THEN** the gateway answers 429 to the requests above the rate

### Requirement: Model spend and sandbox time of a coding run are recorded as usage events

The agent SHALL record, when a coding run ends in any state, one usage event of request type `coding-agent` per model the run used through the usage event port of the deployment modules capability, with the run's tenant, user, conversation and run id, the provider and model, and the counted input, output and cached tokens. The sandbox time of the run's workspace SHALL be the usage event of request type `sandbox` that the sandbox capability already records. The shared quota gate port of the deployment modules capability SHALL be asked before the run starts and at every poll, and a refusal SHALL end the run `failed` with reason `QUOTA_EXCEEDED`. The default of the quota gate SHALL allow every call, because the run's own cost and time limits bound its spend.

#### Scenario: Usage events of a run

- **WHEN** a coding run that used one model ends `done` while a test usage event port replaces the default
- **THEN** the port receives one `coding-agent` event and one `sandbox` event for that run id, with the run's tenant and user

#### Scenario: Quota gate refuses during a run

- **WHEN** a registered quota gate refuses a coding run at a poll
- **THEN** the run ends `failed` with reason `QUOTA_EXCEEDED` at that poll

### Requirement: The runner and the gateway report coding workspaces in logs and metrics

The runner SHALL count gateway containers created and removed, and the gateway SHALL log one line per forwarded request with the route name, the method, the path without its query, the status, the duration and the bytes, and never a header, a query string or a body. The runner's startup banner SHALL name the coding profile, its image digest, the coding project area mode, host path and free space, and the gateway image digest.

#### Scenario: Gateway log line

- **WHEN** OpenCode sends one model request through the gateway
- **THEN** the gateway logs one line with route `model`, method `POST`, the path, the status and the duration, and no header value
