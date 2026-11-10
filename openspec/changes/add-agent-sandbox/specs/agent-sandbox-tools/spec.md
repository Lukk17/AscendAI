## Purpose

Gives the main chat and the subagent runs of the ascend-agent a shell and file tools that act only inside their own throwaway sandbox workspace, created and destroyed through the sandbox runner. Covers when the tools are offered, the workspace of a run and the workspace of a conversation and their lifecycles, copying results out, the agent's record of workspaces, and the agent side logs and metrics.

## ADDED Requirements

### Requirement: Sandbox tools are offered to the main chat and to subagent runs that may use them

The agent SHALL define three tools named `shell`, `file_read` and `file_write`. The sandbox SHALL be core: the tools and the runner SHALL exist in every deployment, whatever `ASCEND_MODULES` holds, and no module switch or tenant module grant SHALL govern them. They SHALL be offered to the main chat and to a subagent run only when the tenant tool policy port of the agent skills capability allows the tool, and for a subagent run also only when the run's computed tools include the tool by the rules of the `subagent-execution` capability. The default of that port SHALL allow all three unless a tool is listed in the configured tool deny list. When the tenant's tool policy does not allow one of them, a definition that names it SHALL be handled as a tool that is not available at that moment: the tool is left out, one WARN line names it, and the run still starts. No tool of the agent SHALL execute a command or read or write a file inside the agent's own process or container.

#### Scenario: The tools exist with no module listed

- **WHEN** `ASCEND_MODULES` is empty and the tenant's tool policy allows `shell`
- **THEN** the main chat's tool list contains `shell`

#### Scenario: Policy does not allow the tool

- **WHEN** a definition lists `shell` and the tenant's tool policy does not allow `shell`
- **THEN** the run starts without `shell`
- **AND** one WARN line names `shell`
- **AND** the main chat's tool list does not contain `shell`

#### Scenario: The default tool policy allows the tools

- **WHEN** no implementation of the tenant tool policy port is registered, the configured tool deny list is empty, and a definition lists `shell`, `file_read` and `file_write`
- **THEN** the run is offered all three
- **AND** the main chat is offered all three

### Requirement: Tool inputs and results are fixed and bounded

`shell` SHALL take `command` (text), an optional `timeout_seconds` and an optional `workdir` relative to `/workspace`. Its result SHALL hold the exit code, standard output, standard error, whether either output was cut, and whether the timeout ended the command. A `timeout_seconds` above the configured maximum SHALL be lowered to the maximum, and the result SHALL say so.

`file_read` SHALL take `path` relative to `/workspace` and return the file content as UTF-8 text. A file that is not valid UTF-8 or that is larger than the configured read limit SHALL produce a tool error that names the reason and the limit, never partial binary content.

`file_write` SHALL take `path` relative to `/workspace`, `content` as text and an optional `append` flag, and create missing parent folders. Content larger than the configured write limit SHALL produce a tool error naming the limit.

Every failure, including an invalid path, a refused limit, a runner that cannot be reached and a workspace that expired, SHALL be returned to the model as a tool error with a short reason and SHALL NOT end the run or the chat turn by itself.

#### Scenario: Shell result

- **WHEN** a run calls `shell` with `command: "python3 -c 'print(6*7)'"`
- **THEN** the tool result has exit code 0 and standard output `42`

#### Scenario: Binary file

- **WHEN** a run calls `file_read` on a file holding bytes that are not valid UTF-8
- **THEN** the result is a tool error stating that the file is not text

#### Scenario: Runner down

- **WHEN** the runner does not answer and a run calls `shell`
- **THEN** the result is a tool error stating that the sandbox is not available
- **AND** the run goes on and can answer without the tool

### Requirement: Each run has its own workspace for its whole life

A run SHALL get its own workspace on its first sandbox tool call and SHALL use that one workspace for every later sandbox tool call. Two runs, including a parent and its child, SHALL NEVER share a workspace, and a run SHALL NEVER use the workspace of the conversation that started it. The workspace SHALL be created for the run's tenant, with the image profile, limits and network allow list from configuration, and with the run id as its label. The network allow list SHALL come only from configuration (globally or for the tenant) and never from the model or the definition body. When the run reaches any final state (done, failed or cancelled, including a restart sweep that closes it), the agent SHALL destroy its workspace. When the agent cannot reach the runner at that moment, the workspace SHALL be left to the runner's expiry, and the agent's record SHALL say so.

#### Scenario: Same workspace across calls

- **WHEN** a run writes `a.txt` with `file_write` and later calls `shell` with `cat a.txt`
- **THEN** the output is the written content

#### Scenario: Child run has its own workspace

- **WHEN** a parent run writes `a.txt` and starts a child run that calls `shell` with `cat a.txt`
- **THEN** the child's command fails because the file does not exist in its workspace

#### Scenario: Cancel destroys the workspace

- **WHEN** a run that has a workspace is cancelled
- **THEN** the workspace is destroyed
- **AND** the record of that workspace is `destroyed` with reason `RUN_CANCELLED`

#### Scenario: The model cannot open the network

- **WHEN** a run asks in a `shell` command or in any tool input for network access to a host
- **THEN** the workspace's network policy stays the one from configuration

### Requirement: Each conversation of the main chat has its own workspace between turns

A sandbox tool call of the main chat SHALL use the workspace of its conversation, and a main chat call without a conversation SHALL be refused with a tool error. A conversation SHALL get its workspace on its first sandbox tool call and SHALL keep it across later turns until the agent closes it. Two conversations SHALL NEVER share a workspace. The workspace SHALL be created for the conversation's tenant with the same profile, limits and network allow list rules as a run workspace, the conversation id as its label, and a lifetime of the configured chat maximum. The agent SHALL close a conversation's workspace when no sandbox tool call was made for the configured idle time, when the workspace's expiry is near, when the tenant has reached the configured number of open chat workspaces and another conversation needs one (closing the least recently used one first), or when the conversation is deleted. Except when the conversation is deleted, the agent SHALL copy the folder `/workspace/out` out before destroying the workspace. After a close, the next sandbox tool call of that conversation SHALL get a new empty workspace, and its tool result SHALL say that the earlier workspace was closed and its output saved. Closing for idle time and near expiry SHALL be done by a system task of the shared scheduler that is safe to run more than once, and a deleted conversation's workspace SHALL be closed by the conversation delete itself.

#### Scenario: Files stay between turns

- **WHEN** the main chat writes `notes.txt` with `file_write` in one turn and calls `shell` with `cat notes.txt` in the next turn of the same conversation
- **THEN** the output is the written content

#### Scenario: Two conversations are separate

- **WHEN** conversation `c1` writes `notes.txt` and conversation `c2` calls `shell` with `cat notes.txt`
- **THEN** the command in `c2` fails because the file does not exist in its workspace

#### Scenario: Idle workspace is closed and its output kept

- **WHEN** a conversation that wrote `out/table.csv` makes no sandbox tool call for longer than the configured idle time
- **THEN** its workspace is destroyed with reason `CHAT_IDLE`
- **AND** the object store holds an archive for that workspace at `tenant/<tenantId>/sandbox-output/chat/<workspaceId>.tar.gz` containing `table.csv`
- **AND** the next sandbox tool call of that conversation runs in a new empty workspace and its result says that the earlier one was closed

#### Scenario: Room for a new conversation

- **WHEN** the tenant already has the configured number of open chat workspaces and a third conversation calls `shell`
- **THEN** the least recently used chat workspace of that tenant is closed with reason `CHAT_ROOM_NEEDED` and its output saved
- **AND** the third conversation's call runs in its own new workspace

#### Scenario: Deleted conversation

- **WHEN** a conversation with an open workspace is deleted
- **THEN** its workspace is destroyed with reason `CONVERSATION_GONE` by the delete and nothing is copied out
- **AND** no `sandbox_workspace` row of that conversation is left

### Requirement: Results are copied out and served

When a run that has a workspace reaches `done`, the agent SHALL copy the folder `/workspace/out` out of the workspace before destroying it, when that folder exists and is not empty, and SHALL store it as one compressed archive in the object store under the key `tenant/<tenantId>/sandbox-output/<runId>.tar.gz`. A conversation's workspace closed by the rules above SHALL be stored under `tenant/<tenantId>/sandbox-output/chat/<workspaceId>.tar.gz`. The tenant id SHALL be taken from the run's or the conversation's tenant and never from tool input. An archive SHALL be limited to the configured size, and a larger folder SHALL be stored as nothing, with the record noting that the output was too large. The agent SHALL serve a run's archive at `GET /api/v1/runs/{id}/sandbox-output` to callers who may read that run, the list of a conversation's saved archives at `GET /api/v1/conversations/{id}/sandbox-outputs` and one of them at `GET /api/v1/conversations/{id}/sandbox-outputs/{workspaceId}` to callers who may read that conversation, each keyed by the caller's tenant, and SHALL answer 404 when there is no archive or it belongs to another tenant. The object store SHALL NOT be reached by clients directly. A run's archive SHALL be deleted with the run when the run's retention ends, and a conversation's archives when the conversation no longer exists or the configured chat output retention has passed.

#### Scenario: Output is kept

- **WHEN** a run writes `out/report.md` and finishes as `done`
- **THEN** the object store holds one archive for that run at `tenant/<tenantId>/sandbox-output/<runId>.tar.gz` containing `report.md`
- **AND** `GET /api/v1/runs/{id}/sandbox-output` returns that archive

#### Scenario: No output folder

- **WHEN** a run that never wrote under `out` finishes as `done`
- **THEN** no archive is stored

#### Scenario: Another tenant's conversation output

- **WHEN** a caller of tenant `b` reads the saved archives of a conversation of tenant `a`
- **THEN** the answer is 404

### Requirement: The agent keeps a record of every workspace

The agent SHALL store one record per workspace with the tenant, the user, its owner (a run or a conversation), the conversation, the run when the owner is a run, the base URL of the sandbox runner that created it, the image profile, the network mode and allow list, the limits, the state (`creating`, `ready`, `closing`, `destroyed`, `failed`), the time it was created, its expiry time, the time it was destroyed, the reason it was destroyed, the number of commands run, and the time of the last command. At most one open workspace SHALL exist per run and per conversation. One sandbox runner runs per container engine host and is shared by every agent copy on that host, and every later call for a workspace (command, file, archive, destroy, and every close by any agent copy) SHALL go to the runner its record names, never to the calling agent copy's own configured runner. Every read of these records SHALL be keyed by the caller's tenant. The record SHALL NOT hold command text, command output or file contents. Records SHALL be deleted with their archives by the retention rules above, through a system task of the shared scheduler. The record's conversation SHALL reference `conversations.id` by a foreign key with no delete action, and deleting a conversation SHALL delete every record of that conversation in the same transaction as its history and SHALL then delete their archives. The table SHALL be created by one Flyway versioned SQL migration with every constraint and index named explicitly. An applied migration file SHALL NOT be edited, and any later schema change SHALL be a new versioned migration.

#### Scenario: Record follows the workspace

- **WHEN** a run creates a workspace, runs three commands and finishes
- **THEN** its record shows state `destroyed`, reason `RUN_FINISHED` and three commands

#### Scenario: Workspace records reference a conversation

- **WHEN** Flyway has run to the latest version
- **THEN** `sandbox_workspace.conversation_id` has the type `uuid` and carries a foreign key to `conversations.id`
- **AND** inserting a `sandbox_workspace` row whose `conversation_id` names no conversation is refused

#### Scenario: A workspace is closed through the runner that created it

- **WHEN** agent copy A creates a workspace through its runner and the idle sweep closes it on agent copy B, whose configured runner address differs
- **THEN** the record of the workspace names the runner of copy A
- **AND** the destroy call reaches the runner of copy A and never the runner of copy B

#### Scenario: Records are per tenant

- **WHEN** tenant `b` reads workspace records
- **THEN** no record of tenant `a` is returned

### Requirement: Agent side logs and metrics

The agent SHALL publish one usage event of the sandbox operation type through the usage event port of the deployment modules capability for every destroyed workspace, holding the tenant and user, the run ids for a run workspace, and the time the workspace existed, and SHALL publish none for a workspace whose create failed. The agent SHALL count sandbox tool calls by tool, outcome and owner kind, workspaces opened and closed by reason and owner kind, and the time spent waiting for the runner, with no tenant id, run id, conversation id, workspace id or command text as a tag. Every log line of a sandbox tool call SHALL carry the tenant id, the workspace id, and the run id or the conversation id. Command text, command output and file contents SHALL be logged only at DEBUG.

#### Scenario: Tool call is counted

- **WHEN** a run calls `shell` once and the command exits with code 1
- **THEN** the sandbox tool call counter for tool `shell`, outcome `nonzero_exit` and owner `run` grows by one

### Requirement: Sandbox behaviour is covered by end-to-end tests

The repository SHALL hold one deterministic end-to-end spec for the sandbox against the live stack in `apps/ascend-agent/e2e/`, covering what no lower test proves: a run that writes and runs a script in a real workspace of the runner, its output archive, a cancelled run whose workspace is removed, and a chat workspace kept between turns and hidden from another conversation. Its tool calls SHALL be forced by the scripted test model, so no sandbox spec calls a real AI model. The runner API refusals, the workspace lifecycle and the output endpoint refusals SHALL be proved by the runner integration tests, the contract test and the controller tests and SHALL NOT be repeated end to end, and no separate runner suite or probe container SHALL exist for it. Pass criteria SHALL be HTTP status, response bodies, the scripted model's request log, the output archive, the `sandbox_workspace` rows and the Docker host's container and network lists filtered on the run's label only, never log lines. The spec SHALL be listed in the full-stack run scenarios and the ascend-agent service suite of `docs/E2E_RUN_SCENARIOS.md`, and the owner SHALL be asked which scenario to run before any run.

#### Scenario: A run's output is served after the run

- **WHEN** the scripted agent spec delegates a script that writes `out/report.md` to a definition with the sandbox tools
- **THEN** `GET /api/v1/runs/{id}/sandbox-output` returns an archive whose `out/report.md` holds the text the script wrote
- **AND** the run's `sandbox_workspace` row is `destroyed` and no container or network labelled with the run's id is left on the Docker host
