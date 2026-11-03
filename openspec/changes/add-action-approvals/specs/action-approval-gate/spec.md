## Purpose

Stops a short, configured list of risky actions until the owner approves them, while every other action of the agent runs at once. Covers which calls and actions are gated, the approval record, how a chat turn and a run wait without holding an HTTP request, the exact and at most once execution, timeouts, remembered choices, limits, restart behaviour, and the metrics and logs of approvals.

## ADDED Requirements

### Requirement: A tool can require approval

Each tool the model can be given SHALL have one effective mode: `allowed`, `requires_approval` or `denied`. A `denied` tool SHALL NOT be given to the model. A `requires_approval` tool SHALL be given to the model like an `allowed` tool, but a call to it SHALL NOT run until it is approved. The mode SHALL apply to MCP tools and to agent native tools alike, by the tool name the model sees. The deployment default list of tools that require approval SHALL be the configuration list `app.policy.default.approval-required-tools`, which ships empty, plus every tool that a registered `ApprovalDefaultsSource` marks, such as an MCP tool whose server entry gives it the default mode `requires_approval`. No agent native tool and no tool of the own MCP servers (weather, web search, page reading, file download, transcription, OCR and semantic memory) SHALL be on the shipped default list. The approval metadata of a tool (category, rememberable, scope arguments) SHALL come only from the `ApprovalDefaultsSource` that describes it, and a tool that no source describes SHALL have the category `other`, no remembered allow and the whole canonical arguments as its scope. The gate SHALL read the mode through the `ToolModeResolver` interface. Its default implementation SHALL read the deployment default list and SHALL answer `allowed` for every tool not on it, and it SHALL exist only while no other `ToolModeResolver` is registered. No tool, skill, subagent definition or model output SHALL be able to change the list.

#### Scenario: Normal work needs no approval

- **WHEN** the shipped defaults are in use and the agent writes a skill, writes a subagent definition, updates user facts, stores a memory and calls web search in one chat turn
- **THEN** every one of these runs at once
- **AND** no approval request is created

#### Scenario: A listed tool is offered but does not run

- **WHEN** the owner lists the MCP tool `discord_send_message` as requiring approval and the model calls it
- **THEN** the model had the tool in its tool list
- **AND** the call does not reach the MCP server
- **AND** one approval request with state `pending` exists for that call

#### Scenario: An MCP server entry brings its gated tools

- **WHEN** an MCP server entry sets the default mode `requires_approval` and the model calls one of its tools that is not overridden to `allowed`
- **THEN** the call does not reach the MCP server
- **AND** one approval request with state `pending` exists for that call, with the category from the entry

#### Scenario: A registered resolver replaces the default

- **WHEN** a deployment registers its own `ToolModeResolver` that answers `requires_approval` for `payments_create`, and the configuration list is empty
- **THEN** a call of `payments_create` does not run and one approval request with state `pending` exists for it
- **AND** the default resolver does not exist

### Requirement: Other parts of the agent can submit one action for approval

Besides tool calls, a component of the agent SHALL be able to submit one action of a registered kind for approval through the same service. Each kind SHALL declare its category, whether it may be remembered, how its scope is built, how its preview is built and how it is executed. The registered kinds and their categories SHALL be: `tool_call` (category from the tool's metadata), `personality_change` (`personality`), `self_change` (`self_change`), `obsidian_note_write` (`other`), `coding_push` (`code_publish`), `coding_project_cleanup` (`workspace_cleanup`), `integration_credential` (`integration_credential`), `integration_egress` (`integration_egress`) and the rule-only kind `integration_tool_review` (`tool_review`), for which no approval request is ever submitted and whose remembered rules hold the tool reviews of `add-self-built-integrations`. This change SHALL provide the handlers of `tool_call` and `personality_change`. The handlers of the other kinds SHALL be provided by the change that owns the action: `add-self-improvement`, `add-obsidian-vault`, `add-coding-agent-delegation` and `add-self-built-integrations`. The application SHALL refuse to start when a handler declares a category other than the registered one, or when two handlers declare the same kind. The category SHALL be one of `personality`, `self_change`, `integration_credential`, `integration_egress`, `tool_review`, `outside_message`, `spend_money`, `outside_delete`, `code_publish`, `workspace_cleanup` or `other`. A tool that requires approval SHALL take its category from the `ApprovalDefaultsSource` that describes it and SHALL be `other` when none describes it.

#### Scenario: Personality proposal waits for the owner

- **WHEN** the model calls `personality_propose` with new content in a clean owner request
- **THEN** one approval request of kind `personality_change` and category `personality` is created for that proposal
- **AND** the personality file is unchanged

#### Scenario: Denied personality proposal is rejected

- **WHEN** the owner denies a pending approval of kind `personality_change`
- **THEN** the proposal is `rejected`
- **AND** the personality file is unchanged

#### Scenario: Timed out personality proposal expires

- **WHEN** a pending approval of kind `personality_change` passes its expiry and the sweep runs
- **THEN** the approval is `expired` and the proposal is `expired`, not `rejected`
- **AND** the personality file is unchanged

#### Scenario: A registered kind without its handler is refused

- **WHEN** a component submits an action of kind `integration_credential` while no handler for that kind is present
- **THEN** the submission is refused with an error naming the kind
- **AND** no approval request is created

#### Scenario: A handler cannot change the category of its kind

- **WHEN** a handler for kind `coding_push` declares the category `other`
- **THEN** the application refuses to start and names the kind and the registered category `code_publish`

### Requirement: Personality proposals are approval requests decided by the approval service

A personality proposal SHALL be one approval request of kind `personality_change` and SHALL be stored nowhere else. Every accepted `personality_propose` call of the agent personality capability SHALL create it in the same request through the implementation of the proposal port that this capability registers, with a payload holding the base commit, the proposed content and the optional reason, and the unified diff between the personality file at the base commit and the proposed content as its preview. The approval id SHALL be the proposal id that the tool result and the read endpoints of the agent personality capability name. The read endpoints SHALL read the approval requests of kind `personality_change` of the caller's tenant, with the proposal status read from the record: `pending`, `approved`, `stale`, `rejected`, `expired` or `cancelled`. The owner SHALL decide a proposal once, only through the approval service. Approving the approval request SHALL call the approve operation of the proposal service, denying it the reject operation, and an approval request that expires SHALL call the expire operation. A `stale_proposal` refusal of the approve operation SHALL be the reason of a failed execution, and the proposal SHALL then read `stale`.

#### Scenario: Proposal is an approval request

- **WHEN** the model calls `personality_propose` as the first tool of a clean owner request
- **THEN** one approval request of kind `personality_change` exists for the proposal, with the base commit, the proposed content and the reason in its arguments
- **AND** the tool result names its id as the proposal id, and `GET /api/v1/personality/proposals/{id}` with that id answers 200 with status `pending`

#### Scenario: Stale proposal

- **WHEN** the owner changes the personality file after a proposal was made and then approves the proposal
- **THEN** the execution is `failed` with detail `stale_proposal`, the file keeps the owner's text, and the proposal reads `stale`

#### Scenario: Owner approves a proposal once

- **WHEN** the owner sends `POST /api/v1/approvals/{id}/approve` for the approval request of a pending proposal whose base commit is the newest
- **THEN** `SOUL.md` holds the proposed content and the repository has one new commit with origin `agent`, the chat request id and the proposal id
- **AND** the proposal is `approved`, and a second approve of the same request is refused with 409 and commits nothing

### Requirement: The approval record holds exactly what will run

Every approval request SHALL be stored in PostgreSQL from the moment it is created until its retention ends or its conversation is deleted, and it SHALL be the only record of that approval: no other table SHALL copy its decision. The record SHALL hold: id, tenant id, the id of the user whose request caused it, the conversation id, the run id, the chat request id, the source (`chat`, `run` or `system`), the kind, the category, the tool name the model saw, the MCP server name and the tool's original name for an MCP tool, a SHA-256 digest of the tool's name, description and input schema, the full arguments as canonical JSON (RFC 8785) and their SHA-256 digest, the scope digest and a readable scope text, a preview built by the server, whether it may be remembered, the decision (`pending`, `approved`, `denied`, `expired` or `cancelled`), who or what decided (`owner`, `rule` or `timeout`, `system` for a cancel), the deciding user id, the channel the decision came through, the id of a remembered rule that decided it, the execution state (`none`, `running`, `succeeded`, `failed` or `unknown`), a short execution detail, the result capped to the configured length, and the times it was created, expires, was decided and was executed. A request started by a timed job of the agent itself SHALL have the source `system` and SHALL have no user, no conversation and no run, and a submission of source `system` that names any of the three SHALL be refused. A request of source `chat` or `run` SHALL have a user. An `ADMIN` of the tenant SHALL decide a request of source `system` like any other request. Arguments larger than the configured limit SHALL be refused with a tool error naming the limit and SHALL never be cut, because a cut action would not be the action that runs. The model's own text SHALL NOT be stored as the description of the action. The schema SHALL be created by one Flyway versioned SQL migration with every constraint and index named explicitly. An applied migration file SHALL NOT be edited.

#### Scenario: Arguments are stored exactly

- **WHEN** the model calls a gated tool with arguments `{"to":"alice@example.com","text":"Hi"}`
- **THEN** the record holds those arguments as canonical JSON and the SHA-256 digest of that canonical text

#### Scenario: Too large to show is refused, not cut

- **WHEN** a gated call carries arguments larger than `app.approvals.max-arguments-bytes`
- **THEN** the model receives a tool error naming the limit
- **AND** no approval request is created and nothing runs

#### Scenario: A timed job asks before cleaning coding projects

- **WHEN** the system task `coding-area-free-space-check` finds free space below 10 percent and submits an action of kind `coding_project_cleanup`
- **THEN** one approval request of source `system`, kind `coding_project_cleanup` and category `workspace_cleanup` is `pending`, with no user, no conversation and no run
- **AND** no coding project is cleaned before an `ADMIN` of the tenant approves it with the digest of the view he read

#### Scenario: Schema is created by Flyway

- **WHEN** the agent starts against an empty PostgreSQL database
- **THEN** Flyway applies the migration and both approval tables with their named constraints and indexes exist

### Requirement: A chat turn never waits for an approval

When a call that requires approval happens in the main chat, the agent SHALL NOT run it and SHALL NOT hold the HTTP request or the stream open for the decision. The agent SHALL create the approval request and no run row, and SHALL return to the model a fixed tool result that says the action waits for the owner's approval, has not run, names the approval id, and asks the model to tell the user and not to call the tool again for the same action. The chat turn SHALL then end normally. A streamed turn SHALL send one `approval_required` event with the approval view and one `run_started` event with the run view before its terminal event. The run API of the subagent run status capability SHALL show the request as a run of kind `approval` whose id and approval id are the approval id, in the list (also with the `kind=approval` filter), the read, the cancel, the event stream and the finished runs block, with the state read from the request: `awaiting_approval` while pending, `running` while the approved action executes, `done` when it succeeded, `failed` with `TOOL_ERROR` when it failed or its outcome is unknown, `failed` with `APPROVAL_DENIED` or `APPROVAL_EXPIRED` after a denial or an expiry, and `cancelled` when it was cancelled. Cancelling that run SHALL cancel the request with decided by `system`. When the same tool is called with the same canonical arguments in the same conversation while an earlier request is still pending, the agent SHALL return the existing approval id and SHALL NOT create a second request.

#### Scenario: Turn ends while the action waits

- **WHEN** the model calls a gated tool during `POST /api/v1/ai/prompt`
- **THEN** the response is 200 with the assistant's answer before any decision is made
- **AND** the approval request is `pending`, no run row exists for it, and `GET /api/v1/runs?kind=approval` lists it in state `awaiting_approval`

#### Scenario: Stream announces the approval

- **WHEN** the same happens on `POST /api/v1/ai/prompt/stream`
- **THEN** the stream carries one `approval_required` event before its `done` event

#### Scenario: Repeated call is not a second request

- **WHEN** the model calls the same gated tool with the same arguments twice in one conversation while the first request is pending
- **THEN** only one approval request exists and both tool results name its id

### Requirement: A subagent run pauses for an approval

When a call that requires approval happens inside a subagent run, the run SHALL move to `awaiting_approval`, SHALL release its worker slot, SHALL NOT count the waiting time against its time limit, and SHALL make no model call or tool call until the decision. The decision SHALL reach the paused run from the stored approval request, so a decision taken on another agent instance reaches it within one run heartbeat interval. After an approval the run SHALL execute the stored call and continue with its real result. After a denial or a timeout the run SHALL continue with a tool result that says the owner denied the action or that the approval timed out and was treated as a denial. When the run being paused, or any run above it, is a foreground run that the main chat waits for, the root of that run tree SHALL move to the background and the main chat's `Task` call SHALL return at once with the run id and a note that the run waits for approval, so the chat request ends. Cancelling a run that is `awaiting_approval` SHALL cancel its pending approval with decided by `system`.

#### Scenario: Run pauses and resumes

- **WHEN** a background run calls a gated tool and the owner approves it
- **THEN** the run was `awaiting_approval` until the decision
- **AND** the tool ran once with the stored arguments and the run went on with its result

#### Scenario: Foreground run moves to the background

- **WHEN** the main chat starts a foreground run with `Task` and that run calls a gated tool
- **THEN** the chat request ends without waiting for the decision
- **AND** the run is marked as a background run and stays `awaiting_approval`

#### Scenario: A decision on another instance reaches the paused run

- **WHEN** a run paused on one agent instance and the owner's approve is handled by another instance
- **THEN** the paused run executes the call and goes on with its result within one heartbeat interval

#### Scenario: Denial lets the run go on

- **WHEN** the owner denies the call of a paused run
- **THEN** the tool never ran
- **AND** the run receives a tool result saying the owner denied it and continues

### Requirement: An approved action runs exactly as shown, at most once

On approval the server SHALL execute the stored action, never a new call from the model. For a tool call it SHALL resolve the tool by the stored name for the tenant and the stored tool context, SHALL check that the tool is still not `denied` for the tenant, and SHALL check that the digest of the tool's current name, description and input schema equals the stored digest. A failed check SHALL end the execution as `failed` with the detail `tool_unavailable`, `tool_denied` or `tool_changed` and SHALL NOT run anything. The execution SHALL pass the stored canonical arguments to the tool. Execution SHALL be claimed with a conditional update from `none` to `running`, so a second decision, a second agent instance or a retry can never run the action twice. A denied, expired or cancelled request SHALL never be executed. The result of a main chat approval SHALL be its result in the run view, which reads `done` on success and `failed` with reason `TOOL_ERROR` on failure, and the next chat turn of the conversation SHALL see it once in the finished runs block.

#### Scenario: Tool changed after the request

- **WHEN** the MCP server changes the input schema of a gated tool after the request and the owner then approves it
- **THEN** nothing is sent to the MCP server
- **AND** the execution is `failed` with detail `tool_changed`

#### Scenario: Two approvals race

- **WHEN** two approve calls for the same pending request arrive at the same moment
- **THEN** the tool runs once
- **AND** one call answers 200 and the other answers 409

#### Scenario: Result reaches the conversation

- **WHEN** an approved main chat action succeeds and the user sends the next prompt in that conversation
- **THEN** that turn's dynamic system message lists the approval with state `done` and the start of the tool result
- **AND** the turn after it does not list it again

### Requirement: A pending approval expires and counts as a denial

Every approval request SHALL expire at its creation time plus `app.approvals.timeout` (24 hours by default). The expiry sweep SHALL be the system task `approval-expiry-sweep` of the shared scheduler of `add-shared-scheduler`, on the five-field cron `app.scheduler.system-tasks.approval-expiry-sweep.cron` (default every minute), run by exactly one agent instance per firing, and SHALL also run once at startup before readiness. It SHALL move every `pending` request past its expiry to `expired` with decided by `timeout`, with a conditional update so it never overwrites a decision that landed first. An expired action SHALL never run. The run view of an expired main chat request SHALL read `failed` with reason `APPROVAL_EXPIRED`, and of a denied one `failed` with reason `APPROVAL_DENIED`. A decision that arrives after the expiry time SHALL be refused with 409, also before the sweep has marked the request. For every expired request the agent SHALL write one owner notification with source `approval` and kind `expired` into the owner notification store of `add-shared-scheduler`, naming the approval's kind and the approval id, and says that the action did not run and can be asked for again.

#### Scenario: Owner does not answer

- **WHEN** a request stays `pending` past its expiry and the sweep runs
- **THEN** the request is `expired`, the action did not run, and its run view is `failed` with reason `APPROVAL_EXPIRED`
- **AND** one owner notification says the action expired and can be asked for again
- **AND** the next chat turn of that conversation lists the expired approval in its finished runs block

#### Scenario: Late approve

- **WHEN** the owner approves a request that already expired
- **THEN** the response is 409 with `code` `approval_already_decided` and nothing runs

#### Scenario: Approve after the expiry time but before the sweep

- **WHEN** the owner approves a request whose expiry time has passed and the sweep has not run yet
- **THEN** the response is 409 with `code` `approval_already_decided` and nothing runs

### Requirement: Decided requests are removed after the retention

Decided approval requests SHALL be deleted `app.approvals.retention` (default 30 days) after their decision time by the one retention task of the shared scheduler, through one entry this capability registers there (table `approval_request`, time column `decided_at`). A `pending` request SHALL never be deleted by retention, and a request of kind `personality_change` SHALL be kept, so the personality proposal history stays readable. Remembered rules SHALL be kept until they are removed. Running the task twice SHALL delete nothing more than running it once.

#### Scenario: Old decided request is removed

- **WHEN** the retention task runs and one request was decided 31 days ago and another is `pending` for 31 days
- **THEN** the decided request is deleted
- **AND** the pending request is kept

#### Scenario: A decided personality proposal is kept

- **WHEN** the retention task runs and a request of kind `personality_change` was decided 31 days ago
- **THEN** the request is kept and its proposal is still readable

### Requirement: The owner can remember a choice for the same tool and target

A decision SHALL be able to carry "remember this choice". A remembered choice SHALL become a rule of the tenant with the tool or kind, the scope digest, a readable scope text, the effect (`allow` or `deny`), the deciding user and the approval it came from. The scope SHALL be built from the scope arguments that the tool's `ApprovalDefaultsSource` names (for example the recipient), and SHALL be the whole canonical argument set when none are configured. A later gated call with the same tenant, tool and scope digest SHALL be decided by the rule at once: `allow` runs it and `deny` refuses it with a tool result that names the rule. Each such call SHALL still be stored as an approval request decided by `rule`. A remembered `allow` SHALL be refused with `approval_not_rememberable` for the categories `personality`, `self_change`, `spend_money`, `outside_delete`, `code_publish` and `workspace_cleanup`, whatever the configuration says. For kind `obsidian_note_write` a remembered `allow` SHALL be possible only for operation `append`, scoped to the connector and the note path. A remembered `deny` SHALL be allowed for every category except `personality`. A remembered choice SHALL never expire on its own. Approving a request of category `integration_egress` SHALL always remember an `allow` for that integration and destination, because only the first send to a destination needs the owner. Approving a request of category `integration_credential` SHALL always remember an `allow` scoped to the integration, the credential name and the binding digest, and that rule SHALL be the grant of the credential, so a changed binding needs a new approval.

#### Scenario: Remembered recipient

- **WHEN** the owner approves a `discord_send_message` call to channel `family` with remember on, and the model later sends another message to `family`
- **THEN** the second call runs at once with no pending request
- **AND** its approval record is `approved` with decided by `rule`

#### Scenario: A new target still asks

- **WHEN** the same tool is later called for channel `work`
- **THEN** a new approval request is created and the call does not run

#### Scenario: Money is never remembered as allowed

- **WHEN** the owner approves a request of category `spend_money` with remember on
- **THEN** the response is 400 with `code` `approval_not_rememberable`
- **AND** the request stays `pending` and nothing runs

### Requirement: The number of pending approvals is bounded

A tenant SHALL have at most `app.approvals.max-pending-per-tenant` (default 20) pending approval requests. A gated call beyond that SHALL NOT create a request and SHALL return a tool error saying that too many approvals are waiting. The application SHALL refuse to start when any approval limit or duration is zero or negative.

#### Scenario: Too many waiting

- **WHEN** a tenant has 20 pending requests and the model calls another gated tool
- **THEN** the model receives a tool error naming the limit
- **AND** the number of pending requests stays 20

### Requirement: Restart and shutdown never run or lose a pending action

A pending approval of a main chat request SHALL survive an agent restart, because it is only a request row and holds no thread and no half done work. A subagent run paused for approval holds its conversation in memory, so when its process dies the run SHALL be closed with `AGENT_RESTARTED` as any other run, and its pending approval SHALL be cancelled with decided by `system`. An execution in state `running` SHALL renew its execution heartbeat while it runs, and an execution whose heartbeat is older than the configured number of run heartbeat intervals (the stale interval count of the subagent runs, default 3) SHALL be set to `unknown` by the expiry sweep, also at startup, and SHALL NOT be run again. Several agent instances SHALL be able to run at once: every decision, claim, duplicate check, pending count and expiry SHALL work on the shared PostgreSQL rows, never on the memory of one instance alone.

#### Scenario: Pending main chat approval survives a restart

- **WHEN** the agent restarts while a main chat approval is pending and the owner approves it afterwards
- **THEN** the action runs once and its approval run ends `done`

#### Scenario: Paused subagent run at a restart

- **WHEN** the agent process is killed while a subagent run is `awaiting_approval` and the agent starts again
- **THEN** the run is `failed` with reason `AGENT_RESTARTED`
- **AND** its approval request is `cancelled` and can no longer be approved

#### Scenario: Crash during execution

- **WHEN** the agent dies while an approved action is `running` and starts again
- **THEN** the execution is `unknown` and the action is not run again

#### Scenario: Two instances cannot pass the pending limit together

- **WHEN** a tenant has 19 pending requests and two agent instances each submit one at the same moment
- **THEN** exactly 20 requests are pending and the other submission returns the tool error naming the limit

### Requirement: Approvals are measured and logged

The agent SHALL publish a counter `approval.requests` by `category` and `source`, a counter `approval.decisions` by `category`, `decision` and `decided_by`, a timer `approval.wait.duration` from creation to decision by `category` and `decision`, a gauge `approval.pending`, and a counter `approval.executions` by `category` and `outcome`. Metric tags SHALL NOT include the approval id, the tool name, the tenant id, the user id, the scope or any argument. Every creation, decision and execution SHALL produce one INFO line with the approval id, tenant id, run id, conversation id, kind, category, tool name, arguments digest, decision, decided by and execution outcome. The arguments, the preview and the result SHALL be logged only at DEBUG. The startup banner SHALL show the timeout, the pending limit and the tools in the deployment default list.

#### Scenario: Decision is counted

- **WHEN** the owner denies a request of category `outside_message`
- **THEN** `approval.decisions{category=outside_message,decision=denied,decided_by=owner}` grows by one

#### Scenario: Arguments stay out of INFO logs

- **WHEN** a gated call with the argument text "secret plan" is created, approved and executed at log level INFO
- **THEN** no log line contains "secret plan"
