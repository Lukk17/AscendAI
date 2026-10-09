## Purpose

Lets the assistant hand a coding task (build an app or change code in a repository) to OpenCode as a background run on a coding project, with a visible status, time and cost limits and a cancel, and report the outcome back to the conversation instead of writing the code itself.

## ADDED Requirements

### Requirement: The delegate_coding tool starts a background coding run

The agent SHALL offer a tool named `delegate_coding` to the main chat when the module `coding` is active and the tenant's module grants and tool policy allow it. Its input SHALL be exactly one of: `repository` (a GitHub repository written `owner/name`), `new_project` (a project name), or `project_id` (an existing coding project of the caller's tenant), plus an optional `base_branch` (only with `repository`), `task` (the task text, 1 to 20000 characters), an optional `provider`, an optional `model`, an optional `max_cost_usd`, an optional `max_minutes`, and an optional `test_command` (at most 1000 characters). A call with `repository` or `new_project` SHALL create a new coding project. A valid call SHALL create a run of kind `coding` in state `waiting`, SHALL return at once with the run id, the project id, the provider, model, limits and a note that the run works in the background, and SHALL NOT wait for the run. The tool SHALL NOT be offered to subagent runs.

#### Scenario: A valid call returns the run id at once

- **WHEN** the model calls `delegate_coding` with `repository` `owner/app` and `task` "add a health endpoint"
- **THEN** the tool result holds a run id, a new project id, the resolved provider and model, the cost and time limits, and the text that the run works in the background
- **AND** `GET /api/v1/runs/{id}` answers the run with kind `coding`

#### Scenario: Follow-up on an existing project

- **WHEN** the model calls `delegate_coding` with the `project_id` of a project in state `pushed` and a new task
- **THEN** a new run of that project is created and no new project is created

#### Scenario: Two targets at once

- **WHEN** the model calls `delegate_coding` with both `repository` and `new_project`
- **THEN** the tool result is an error naming the fields and no run is created

#### Scenario: Not offered to subagents

- **WHEN** the tool list of a subagent run is built
- **THEN** it holds no `delegate_coding` tool

### Requirement: The usable repositories are read from the GitHub App installation

The agent SHALL read the repositories of every installation of the GitHub App through the GitHub API (`GET /app/installations`, then `GET /installation/repositories` with a `metadata: read` token) at startup, every `app.coding.repositories.refresh` (default `10m`) and when GitHub answers that the App has no installation on a repository. It SHALL log the repository names it found and each repository added or removed since the last read, and SHALL list them through `GET /api/v1/coding-repositories` and the read-only tool `coding_repositories`, each with `fullName`, `private`, `defaultBranch` and `allowed` for the caller's tenant. No repository list SHALL be fixed in the specification. A failed read SHALL keep the last good list and log a WARN. Owner decision 65.10 of 2026-10-04.

#### Scenario: Installed repositories are listed and logged

- **WHEN** the App is installed on `owner/app-a` and `owner/app-b` and the agent starts
- **THEN** the startup log names both repositories
- **AND** `GET /api/v1/coding-repositories` returns both with `allowed` true

#### Scenario: A repository added to the installation appears after a refresh

- **WHEN** the owner adds `owner/app-c` to the installation and the refresh interval passes
- **THEN** the log names `owner/app-c` as added and the tool `coding_repositories` returns it

#### Scenario: A failed read keeps the last list

- **WHEN** GitHub answers 503 during a refresh
- **THEN** the endpoint still returns the last good list and the log holds one WARN

### Requirement: A coding run is refused before it starts when it cannot be allowed

A call to `delegate_coding` SHALL be refused with a tool error, and no run SHALL be created, when: the tenant's module grants or tool policy do not allow the tool, the repository is not in the configured repository allow-list of the tenant, the GitHub App has no installation on the repository, the project id is unknown or belongs to another tenant, the project is `in_progress`, `deleting` or `deleted`, the provider is unknown or refused by the shared model access policy port, the model is not in the provider's model allow-list or is refused by that port, no key is available for the provider from the provider key port, a requested limit is above its configured maximum, the shared quota gate port refuses the run, the free space of the coding project area is below the configured stop level, or the number of waiting coding runs is at its maximum. The error SHALL name the reason and SHALL NOT include a secret or a key.

#### Scenario: Repository not allowed

- **WHEN** the model calls `delegate_coding` for `stranger/repo`, which is not on the tenant's repository allow-list
- **THEN** the tool result is an error that names the repository as not allowed
- **AND** no run, project, workspace or token is created

#### Scenario: Limit above the maximum

- **WHEN** the model asks for `max_cost_usd` 50 while the configured maximum is 20
- **THEN** the tool result is an error that names the maximum

#### Scenario: Provider refused by the policy port

- **WHEN** a registered model access policy refuses provider `opencode-go` and the model calls `delegate_coding` with it
- **THEN** the tool result is an error that names the provider as denied by policy

#### Scenario: Project busy

- **WHEN** the model calls `delegate_coding` with the `project_id` of a project whose run is still `running`
- **THEN** the tool result is an error with reason `coding_project_busy`

#### Scenario: Area almost full

- **WHEN** the coding project area has less free space than the configured stop level
- **THEN** the tool result is an error with reason `disk_low` that lists the largest projects and says whether a cleanup approval is waiting

### Requirement: A coding run moves through the run states and is limited in time and cost

A coding run SHALL use the run states of the run status capability (`waiting`, `running`, `awaiting_approval`, `done`, `failed`, `cancelled`), and SHALL never enter `awaiting_approval`, because its push and its cleanup are approvals of their own. It SHALL move to `running` when it gets a coding slot and its workspace is created. At most the configured number of coding runs SHALL be `running` at once, and further runs SHALL wait in arrival order up to the configured number of waiting runs. Its cost limit SHALL be the smaller of the requested and the configured value, and the same for its time limit. A run that reaches its time limit SHALL end `failed` with reason `TIME_LIMIT`. A run whose counted cost reaches its cost limit SHALL end `failed` with reason `COST_LIMIT`. A run whose OpenCode process exits with an error SHALL end `failed` with reason `CODING_AGENT_ERROR`, and with `PROVIDER_LIMIT` when the error is the provider's usage limit. A run that cannot get or use its workspace SHALL end `failed` with reason `SANDBOX_ERROR`. A run whose clone fails, or whose project folder is not clean on its work branch at start, SHALL end `failed` with reason `REPOSITORY_ERROR`. A run stopped because the coding project area fell below the stop level SHALL end `failed` with reason `DISK_LOW`. In every final state the run's workspace SHALL be destroyed and its project folder SHALL be kept.

#### Scenario: Time limit

- **WHEN** a coding run with a time limit of 2 minutes is still working after 2 minutes
- **THEN** the OpenCode process is ended, the run is `failed` with reason `TIME_LIMIT`, its workspace no longer exists, and its project folder still exists

#### Scenario: Cost limit

- **WHEN** the counted cost of a coding run reaches its limit of 1.00 US dollar
- **THEN** OpenCode is stopped and the run is `failed` with reason `COST_LIMIT`
- **AND** the counted cost and tokens stay on the run record

#### Scenario: One run at a time by default

- **WHEN** two coding runs of different projects are started while the configured maximum of running coding runs is 1
- **THEN** the first is `running` and the second is `waiting` until the first is final

### Requirement: Trusted agent code can start a coding run from a seed

The agent SHALL offer an internal entry point, used only by trusted agent code and never offered as a tool or a REST endpoint, that starts a coding run on a new project of source `seed` from a tar archive of a seed folder. The agent SHALL write the seed into the project's work tree and commit it as the base commit before OpenCode starts, so the run's diff and bundle are relative to the seed. The run SHALL carry the `purpose` its caller gives (`integration` for `add-self-built-integrations`). Its gateway SHALL have only the model route and no git route. Its egress allow-list SHALL be the one its caller gives, checked by the same rules as a configured allow-list. Provider, model, key, limits, quota and free space SHALL be resolved and checked as for any coding run. A project of source `seed` SHALL never be published, and a publish request for it SHALL be refused with `coding_not_publishable`.

#### Scenario: Seed run starts from the seed

- **WHEN** trusted agent code starts a seed run from a folder that holds `server.py` and `integration.yaml`
- **THEN** the project's base commit holds exactly those two files
- **AND** the run's diff shows only the changes OpenCode made on top of them

#### Scenario: No tool starts a seed run

- **WHEN** the tool list of the main chat is built
- **THEN** no tool and no input of `delegate_coding` can start a run of source `seed`

#### Scenario: Seed project is not publishable

- **WHEN** a publish is requested for a project of source `seed`
- **THEN** it is refused with code `coding_not_publishable`

### Requirement: A coding run can be cancelled and is closed after a restart

`POST /api/v1/runs/{id}/cancel` on a coding run SHALL stop its OpenCode process, collect what was committed, destroy its workspace and end the run `cancelled`. When the agent restarts, every coding run that was `waiting` or `running` SHALL be closed as `failed` with reason `AGENT_RESTARTED` and its workspace SHALL be destroyed. A coding run SHALL never be resumed or started again on its own. The project folder SHALL be kept in both cases, and the project's state SHALL be set from its commits.

#### Scenario: Cancel a running coding run

- **WHEN** the owner cancels a running coding run
- **THEN** the run is `cancelled` within the configured poll interval plus 10 seconds
- **AND** its workspace, gateway and egress proxy no longer exist
- **AND** its project folder still exists

#### Scenario: Restart closes the run

- **WHEN** the agent stops while a coding run is running and starts again
- **THEN** the run is `failed` with reason `AGENT_RESTARTED`, its workspace is removed, and its project is no longer `in_progress`

### Requirement: Progress of a coding run is visible in the run status

While a coding run works, its run record SHALL show its last step, at most 500 characters, updated at least every configured poll interval while OpenCode produces output: OpenCode's last tool use or the start of its last message, the counted tokens and the counted cost so far. Every change SHALL be published as a run change, so `GET /api/v1/runs/{id}/events` streams it as `subagent_status`. Progress text SHALL NOT contain a provider key or a git token.

#### Scenario: Following a coding run

- **WHEN** a client follows `GET /api/v1/runs/{id}/events` of a running coding run whose OpenCode process edits a file
- **THEN** the client receives a `subagent_status` event whose last step names the file edit
- **AND** the cost so far in later events never goes down

### Requirement: The result is stored and the conversation is told

When OpenCode ends, the agent SHALL collect the result before the workspace is destroyed: it SHALL commit any uncommitted change on the work branch, and SHALL collect OpenCode's final summary, the list of the run's commits, the diff against the run's start commit, the diff statistics, the test command's exit code and output when a test command was given, the tokens and cost, and a git bundle holding the run's commits. The run SHALL end `done` with a result text of at most 4000 characters that holds the summary, the diff statistics, the test outcome and the cost. The full result SHALL be stored in the object store under `tenant/<tenantId>/coding/<runId>/`. `GET /api/v1/coding-runs/{id}/result` SHALL return the stored result as JSON, `GET /api/v1/coding-runs/{id}/diff` the full diff as text, and `GET /api/v1/coding-runs/{id}/bundle` the bundle, each after the same tenant and user check as the run endpoints, and each answers 404 for a run of another tenant. A run that made no change SHALL still end `done` and say that nothing changed. The conversation SHALL be told through the finished runs block of the run status capability.

#### Scenario: Result of a finished run

- **WHEN** a coding run ends after OpenCode added two commits and the test command passed
- **THEN** the run is `done`, its result text names two commits, the diff statistics, "tests passed" and the cost
- **AND** `GET /api/v1/coding-runs/{id}/diff` returns a diff that applies cleanly to the run's start commit
- **AND** the object store holds the result under `tenant/<tenantId>/coding/<runId>/`

#### Scenario: Nothing changed

- **WHEN** OpenCode ends without changing any file
- **THEN** the run is `done` and its result says that no change was made, and no bundle is stored

### Requirement: Coding projects can be listed and read

The agent SHALL offer a tool named `coding_projects` to the main chat and the endpoints `GET /api/v1/coding-projects` and `GET /api/v1/coding-projects/{id}`. Each project SHALL show its id, repository or new project name, work branch, state (`in_progress`, `done`, `pushed`, `deleting`, `deleted`), the number of commits not pushed, the last measured size, the last activity, its last run, and its pull request when one is open. Every read SHALL be keyed by the caller's tenant and SHALL answer 404 for a project of another tenant.

#### Scenario: List projects

- **WHEN** the model calls `coding_projects` for a tenant with one pushed and one done project
- **THEN** the result lists both with their states and sizes, and says that the done project has commits that are not pushed

### Requirement: Coding endpoints are gated by login role

The agent SHALL add rows to the authorization matrix of `add-keycloak-login` in the filter chain of `SecurityConfig` for its endpoints. `GET /api/v1/coding-repositories`, `GET /api/v1/coding-projects`, `GET /api/v1/coding-projects/{id}`, `GET /api/v1/coding-runs/{id}/result`, `GET /api/v1/coding-runs/{id}/diff` and `GET /api/v1/coding-runs/{id}/bundle` SHALL need a signed-in user of the tenant and SHALL be scoped by the controller to the caller's tenant. `POST /api/v1/coding-projects/{id}/publish` and `POST /api/v1/coding-projects/cleanup` SHALL need `ADMIN`, and the controller SHALL check `ADMIN` of the project's own tenant again.

#### Scenario: A user cannot publish

- **WHEN** a token carrying only the `USER` role calls `POST /api/v1/coding-projects/{id}/publish`
- **THEN** the response is 403
- **AND** no approval is submitted

#### Scenario: A user can read the projects of the tenant

- **WHEN** a token carrying only the `USER` role calls `GET /api/v1/coding-projects`
- **THEN** the response is 200 and lists the projects of the caller's tenant

#### Scenario: A request with no token

- **WHEN** a request with no token calls `POST /api/v1/coding-projects/cleanup` or `GET /api/v1/coding-runs/{id}/result`
- **THEN** the response is 401

### Requirement: Coding stores are tenant scoped and fail closed

The tables `coding_project` and `coding_run` SHALL carry `tenant_id`, written from the tenant of the current request or bound from the row for background work, and every query SHALL filter on it. Project folders SHALL live only under `tenants/<tenantId>/projects/` of the coding project area, and run results only under the object prefix `tenant/<tenantId>/coding/<runId>/` of the `coding-output` bucket, with the tenant taken from the project or run row and never from tool input. A project, run or result of another tenant SHALL be answered as not found. A tool call, an endpoint call or a seed run start with no tenant bound SHALL be refused and SHALL write no row, folder or object.

#### Scenario: Folder and objects under the tenant

- **WHEN** a coding run of tenant `default` ends `done` on a new project
- **THEN** its project folder is under `tenants/default/projects/` and its results are under `tenant/default/coding/<runId>/`

#### Scenario: No tenant resolved

- **WHEN** `delegate_coding` is called while no tenant is bound
- **THEN** the call is refused with a tool error
- **AND** no `coding_project` or `coding_run` row, project folder or object is written

### Requirement: Agent side metrics and logs of coding runs

The agent SHALL record, with no run id, project id, repository, user or tenant as a metric tag: runs started by provider, runs finished by state and reason, run duration, tokens by provider and token type, cost by provider, limit hits by limit, refused calls by reason, published results by outcome, projects by state, and project cleanups by outcome. It SHALL log one INFO line per state change and per collected result with the run id, project id, tenant, provider, model, duration, cost and diff statistics, one WARN line per refused call, limit hit and workspace error, and the task text, the summary and the diff only at DEBUG. No log line at any level SHALL contain a provider key, a git token, the GitHub App private key or a signed GitHub App token request.

#### Scenario: Metrics after a run

- **WHEN** one coding run ends `failed` with reason `COST_LIMIT`
- **THEN** the counter of finished coding runs grows by one with the tags state `failed` and reason `COST_LIMIT`, and the limit hit counter grows by one with limit `cost`

#### Scenario: No secret in logs

- **WHEN** a coding run is made at log level DEBUG and its logs are searched for the provider key and the git token values
- **THEN** neither value is found

### Requirement: Coding delegation is proven end to end with a fake coding agent and with a real one

The repository SHALL hold a deterministic end-to-end spec in `apps/ascend-agent/e2e/testing/`, with Bruno requests in `docs/api/request/AscendAI/ascend-agent/testing/coding/`, in which the scripted model of the shared harness of `close-agent-test-gaps` calls the coding tools and the fake OpenCode of the test image does the work on new projects, so that no AI model and no GitHub account are needed. It SHALL prove the run states and events, the project and result endpoints, cancel, the cost limit, the refusals, the login role rules and an approved cleanup. The scripted model SHALL start only for the deterministic specs, never for the AI-run spec, which runs against the agent with the shipped profile. An AI-run spec SHALL prove on the dedicated private test repository with the owner's GitHub App that a real model delegates a task that real OpenCode completes there, and that an approved publish pushes its work branch. The publish path SHALL be proven end to end by that one spec only, and its refusal and race cases by integration tests. The repository and the App installation SHALL be named in those specs as owner facts. Every spec SHALL pass only on HTTP answers, run events, object listings, persisted rows, container lists and GitHub reads, never on a log line.

#### Scenario: Fake coding run needs no model

- **WHEN** the deterministic spec delegates a task on a new project through the scripted model
- **THEN** the run reaches `done`, its result endpoint answers 200, and no hosted or local chat model and no GitHub endpoint was called

#### Scenario: Cancelled fake run keeps its project

- **WHEN** the spec cancels a `#hang` run through `POST /api/v1/runs/{id}/cancel`
- **THEN** the run reads `cancelled` within the poll interval plus 10 seconds, no container of its workspace runs, and its project is still readable
