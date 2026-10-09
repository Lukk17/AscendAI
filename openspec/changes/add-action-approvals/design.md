## Context

See proposal.md for why. This section holds only the current state that shapes the approach.

- Tools reach the model through one composition point, `ChatToolset` with `AgentNativeTool` beans, owned by `add-agent-skills` (its D3). It takes the filtered MCP callbacks from `FilteredToolCallbackProvider` and the callbacks of every agent native tool, once per chat request and once per subagent run. `add-tenant-policy` (company, build group 5) adds a tenant allow-list filter there and inside `FilteredToolCallbackProvider` later. The tool context carries `user_id`, `request_id`, `tenant_id` and `embedding_provider` (`add-agent-skills`), and `conversation_id`, `subagent_run_id`, `subagent_depth` and `user_message` (`add-agent-subagents`).
- The main chat runs Spring AI's internal tool loop inside the one chat executor `StreamingChatExecutor` of `add-chat-streaming-and-conversations` (its D3, owner answer 89.1 of 2026-10-08, which removed `ChatExecutor`, and `POST /api/v1/ai/prompt` collects its stream into one answer), so no code of ours runs between the model's tool call and the tool's execution, except inside the tool callback itself.
- A subagent run runs its own user controlled tool loop (`add-agent-subagents` D8) with checkpoints before every model call and every tool call, on its own virtual thread, with a fair semaphore of worker slots, a deadline watchdog, a heartbeat, and a restart sweep that closes `waiting` and `running` runs with `AGENT_RESTARTED` and never resumes them (its D10, D14).
- Runs live in `subagent_run` (its D13) with six states (`waiting`, `running`, `awaiting_approval`, `done`, `failed` and `cancelled`), a closed set of failure reasons, a REST API under `/api/v1/runs`, an event stream per run, a run view and `SubagentRunChangedEvent`, and a block in the next chat turn's dynamic system message that lists finished runs once (its D16). The run path was chosen kind neutral so that later kinds of background work can share it (its D17). Since owner answer 89.4 of 2026-10-08 a main chat approval is not a run row: `add-agent-subagents` offers `SubagentRunService.pauseForApproval(runId, approvalId)` and `resumeAfterDecision(runId)` for a paused run (its D10) and the port `RunViewSource` (its D17), through which a later change shows work that is not a row of its table in the run list, the read, the cancel, the event stream and the finished runs block.
- `add-agent-soul` keeps no proposal table (owner answer 89.4 of 2026-10-08). Its `personality_propose` tool hands a proposal to its port `PersonalityProposalPort`, which has no implementation until this change registers one, and its read endpoints `GET /api/v1/personality/proposals` and `GET /api/v1/personality/proposals/{id}` read through the same port. `PersonalityProposalService` offers `diff(baseCommit, content)`, `approve(approvalId, proposal)` (with a stale check against the base commit), `reject(approvalId)` and `expire(approvalId)`, called only by the approval handler of this change (its D7). Its Non-Goals say that every proposal is decided through `/api/v1/approvals` of this change.
- `add-tenant-policy` (company, build group 5) registers its implementation later: an allow-list of tools per tenant, narrow-only against the deployment default `app.policy.default.*`. This change does not wait for it.
- `add-chat-streaming-and-conversations` has a closed set of SSE events (`delta`, `sources`, `done`, `error`), and each later change adds its own event names when it lands (owner answer 93 of 2026-10-08): `run_started` and `subagent_status` from `add-agent-subagents`, `approval_required` from this change (D5), `citations` from `add-passage-level-citations`.
- `add-deployment-modules` (build group 3, position 6) owns `AuditEventPort` (`record(AuditEvent)`). Its default `LogAuditEventPort`, registered with `@ConditionalOnMissingBean`, writes one structured INFO log line with the event name, tenant, actor, target and outcome, never a secret or content. `add-audit-and-gdpr-compliance` (company, build group 5) registers its `AuditRecorder` backed implementation later, with its closed action vocabulary.
- Every agent error is the RFC 7807 problem detail of `upgrade-spring-boot-4` D19, built from one `ApiErrorCode` enum. Schema changes are Flyway versioned SQL migrations.
- Security is the Keycloak login of `add-keycloak-login`, which lands before this change (build group 3, position 3 of the owner build order of 2026-10-04): an OAuth2 resource server with the roles `USER` and `ADMIN` and one authorization matrix that each later change extends with its own rows (its D4). The owner's Keycloak account holds `ADMIN`. The tenant of a request is `TenantContext.currentTenantId()` of the same change (its D3), `default` in the personal deployment, and a background worker that acts for a stored row binds the row's tenant with `TenantContext.runAs`.
- `add-shared-scheduler` runs every periodic job of the agent on db-scheduler. A system task is a bean with a name from the closed enum `SchedulerTaskName`, a five-field cron and a zone from `app.scheduler.system-tasks.<name>.cron` and `.time-zone`, and a handler that is safe to run twice. Exactly one agent instance runs each firing. The same change keeps the owner notification store, which records a message for the owner and hands it to the app and the plugin host.
- `add-mcp-tool-servers` (build group 4, position 6, lands after this change and carries its own part) describes every MCP server in one entry with a `default-mode` and per tool overrides (`mode`, `category`, `rememberable`, `scope-arguments`). Its `McpToolModeDefaults` turns those into default modes and approval metadata for prefixed tool names.
- `add-openclaw-plugin-host` (build group 4, position 10, lands after this change and carries its own part) delivers messages without an inbound message through its outbox table `channel_outbox`, filled by listeners of `ApprovalChangedEvent` and `SubagentRunChangedEvent` after commit (its D12). Discord buttons carry the outbox id, and a press reaches the agent at the one action endpoint `POST /api/v1/channel-host/actions` with the action type `approval_approve` or `approval_deny` (owner answer 89.6 of 2026-10-08).

## Goals / Non-Goals

Goals:

- One approval service, one record, one decision path, used by tool calls and by other actions alike, so no second approval mechanism ever appears (the personality proposal included). `approval_request` is the only record of an approval and `approval_rule` the only record of a remembered decision (owner answer 89.4 of 2026-10-08): no other table of any change copies a decision.
- Approve exactly what runs: the stored action is what executes, never a fresh model call.
- Never hold an HTTP request or a worker slot while waiting.
- At most once execution, also across restarts and concurrent decisions.
- A short default list, so normal work never asks.

Non-Goals:

- Push notifications to the phone. The app reads the pending list when it opens and after each event (made in `add-flutter-chat-app`). Push belongs with a later notification change.
- The Discord bot itself. `add-openclaw-plugin-host` owns it: its outbox posts the prompt and its relay calls `ApprovalService.decide` as the linked user (D11, D12). This change provides the view, `ApprovalChangedEvent` and a decision call that takes the deciding identity.
- The handlers of kinds that belong to other changes. This change registers the kinds and fixes their category rules (D3, D9). `add-self-improvement`, `add-obsidian-vault`, `add-coding-agent-delegation` and `add-self-built-integrations` provide the handlers.
- Approving model spend. Model cost is limited by the quotas of `add-usage-metering-and-quotas` and the run limits of `add-agent-subagents`, not by approvals. "Spending money" here means a tool that pays for something outside the system.
- Inspecting tool arguments to guess risk. The mode is per tool, set by the owner, which is the robust control.
- Several owners who must all agree. One decision by one `ADMIN` of the tenant is enough.
- A non-admin user deciding approvals caused by his own chat. Only the tenant `ADMIN` decides (owner decision of 2026-10-02).

## Decisions

### D1: A third tool mode, read through one seam with a configuration default

The mode of a tool is `allowed`, `requires_approval` or `denied`. This change reads it through its own seam, `ToolModeResolver`, and ships a default that reads the deployment configuration key `app.policy.default.approval-required-tools`. `add-tenant-policy` (company, build group 5) registers its implementation later: it adds a per tenant approval list whose effective value is the union of the deployment default and the tenant's own list (narrow-only, so a tenant can add a tool and never remove one the deployment lists), and the mode `denied` for a tool outside the tenant's allow-list. This change does not wait for it.

The deployment default list is `app.policy.default.approval-required-tools` plus every tool that a registered `ApprovalDefaultsSource` bean marks. The interface has two methods: `approvalRequiredTools()` returns the tool names it marks as `requires_approval`, and `metadata(toolName)` returns the approval metadata (category, rememberable, scope arguments) of a tool it describes. `McpToolModeDefaults` of `add-mcp-tool-servers` is one source: every MCP tool whose server entry gives it the default mode `requires_approval` is on the list, and its metadata comes from the entry's per tool override. `add-self-built-integrations` feeds the same source with the tools of its integrations, whose modes come from the tool review rules of kind `integration_tool_review` (D3, D9). A tool that only the configuration list names, for example an agent native tool, has no metadata of its own: its category is `other`, it is never offered a remembered allow, and its scope is the whole canonical arguments (answer 93 of 2026-10-08 removed the `app.approvals.tools.*` block, which described no gated tool).

The gate reads the mode through one small interface, `ToolModeResolver`, so it does not depend on how a policy is stored. This change ships the default `ConfigToolModeResolver`, registered with `@ConditionalOnMissingBean`: it reads the deployment default list above, and every tool not on that list is `allowed`. A test registers its own `ToolModeResolver` bean and shows that it replaces the default with no edit of this change (task 2.4). Company registers its implementation later: `TenantPolicyService` of `add-tenant-policy`, and the default bean then does not exist. The key name is the same in both, so the configuration of a deployment does not change.

Alternatives considered: a separate `app.approvals.tools` list next to the policy (rejected: two places would decide whether a tool runs, and they could disagree), and a mode inferred from MCP tool annotations such as `destructiveHint` or `openWorldHint` (rejected: annotations come from the MCP server and are hints the MCP specification itself calls untrusted, and `openWorldHint` is true for web search, which the owner wants to run freely).

### D2: A short default list, from configuration and from the MCP server entries

Minimal list, owner decision of 2026-10-02 on what counts as risky, and kept as it is by the owner's answer of the same day:

| Risk | How it is gated | In the shipped default |
| :--- | :--- | :--- |
| Changing the personality file | Kind `personality_change`, submitted by `personality_propose` of `add-agent-soul` | Always, it is not a tool mode but the only way the agent's proposal applies |
| A self change written in the chat right after outside content | Kind `self_change`, submitted by the self change gate of `add-self-improvement` | Always, when that change stages a write |
| Writing a note outside the agent's own folder of the vault | Kind `obsidian_note_write`, submitted by the note tools of `add-obsidian-vault` | Always, except an append to today's daily note |
| Publishing the result of a coding run to a repository | Kind `coding_push`, submitted by `coding_publish` of `add-coding-agent-delegation` | Always |
| Cleaning coding projects when free disk space falls below 10 percent | Kind `coding_project_cleanup` (owner answer 47.1 of 2026-10-02), submitted by `add-coding-agent-delegation` | Always |
| Giving a self-built integration a credential | Kind `integration_credential`, submitted by `add-self-built-integrations` | Always |
| A self-built integration sending outside the system for the first time | Kind `integration_egress`, submitted by `add-self-built-integrations` | Always, once per integration and host |
| Sending a message to another person | A tool on the approval list, category `outside_message` | The send tools of the outside MCP servers of `add-mcp-tool-servers` (for example the Gmail send tool), through their server entries |
| Spending money | A tool on the approval list, category `spend_money` | No such tool today |
| Deleting the owner's data outside the system | A tool on the approval list, category `outside_delete` | Every write tool of an outside MCP server is gated by its entry's default mode, which covers deletes |

So `app.policy.default.approval-required-tools` ships empty, and the MCP tools that start gated come from their server entries (D1). No agent native tool is on the default list. The own MCP servers (weather, web search, page reading and file download, transcription, OCR, semantic memory) read or work inside the system and stay `allowed`, and so does `knowledge_add_download` of `add-download-ingestion`. Memory delete and wipe in AscendMemory remove data inside the system, which the owner wants to run without asking. Skill writes, subagent definition writes and user facts updates stay `allowed` by owner decision. A test asserts this default (task 2.6).

The approval metadata of a tool (`category`, `rememberable` and `scope-arguments`, a list of top-level argument names) comes only from the `ApprovalDefaultsSource` that describes it: the MCP server entry for an MCP tool, the integration for a tool of a self-built integration. A tool with no source (an agent native tool the owner lists in `app.policy.default.approval-required-tools`) gets category `other`, `rememberable` false and an empty `scope-arguments` (D1). This is metadata about how to show and remember a call, not a second list: a tool with metadata and no `requires_approval` mode is never gated.

### D3: One service, kinds with handlers, and `tool_call` is just one kind

`ApprovalService` owns the record, the decision, the rules, the expiry and the execution. Anything that needs the owner submits an `ApprovalAction` (kind, source, tenant, user, conversation, run, request id, payload as canonical JSON, preview, scope) and gets back either a decision taken by a rule or a pending approval id.

The source says what started the request: `chat` for the main chat, `run` for a run, and `system` for a timed job of the agent itself, a system task of `add-shared-scheduler` (owner decision 49.2 of 2026-10-03). A request of source `system` has no user, no conversation and no run, because no person's request caused it, and the service refuses a `system` submission that names any of the three. The tenant `ADMIN` decides it as usual (D12). Its first user is kind `coding_project_cleanup`: the system task `coding-area-free-space-check` of `add-coding-agent-delegation` asks the tenant administrator before it cleans coding projects. A non-admin caller never sees a `system` request, because he sees only requests his own requests caused (`action-approval-decisions` spec). Each kind has one `ApprovalActionHandler` bean that declares its category, whether it may be remembered as an allow, how its scope and preview are built, and how it executes, denies and expires. This change ships two handlers:

- `ToolCallApprovalHandler` for kind `tool_call`. Payload: tool name, MCP server and original tool name, tool definition digest, canonical arguments. Preview: the tool name and server followed by the arguments pretty printed. Execute: D7.
- `PersonalityChangeApprovalHandler` for kind `personality_change`. The approval request is the proposal itself, there is no proposal table (owner answer 89.4 of 2026-10-08). Payload, stored as the canonical arguments: the newest commit of the tenant's `soul/` repository when the proposal was made (`base_commit`), the proposed content (`proposed_content`, already passed `SoulTextValidator`) and the optional reason (`reason`, at most `app.soul.reason-max-chars` characters of `add-agent-soul`, default 300). The chat request id is the record's own `request_id`. Preview: the unified diff that `PersonalityProposalService.diff` computes between the file at the base commit and the proposed content. Execute: `PersonalityProposalService.approve(approvalId, proposal)`, whose stale check stays the soul change's and whose commit carries the approval id in the `Soul-Proposal-Id` trailer. Deny: `PersonalityProposalService.reject(approvalId)`. Expiry: `PersonalityProposalService.expire(approvalId)`. Reject and expire change no file and only count and audit the outcome. A refusal of the approve call (`stale_proposal`) comes back as the reason of a failed execution, never as an HTTP status. The execution claim of D7 makes a second apply impossible, so no `proposal_not_pending` check is needed. Never rememberable. This change registers `ApprovalPersonalityProposalPort`, the implementation of the soul change's `PersonalityProposalPort`: `submit` creates the approval request of kind `personality_change` in the same request and returns its id, which is the proposal id, and `page` and `find` read the requests of that kind as the proposal screen's filtered view (task 3.7). The proposal status the soul read endpoints show is read from the record: `pending`, `approved` (approved and executed), `stale` (approved and failed with `stale_proposal`), `rejected` (denied), `expired` and `cancelled`.

Every kind is registered here with its category, so the category rules of D9 stay in this one place, and the change named in the table provides its handler:

| Kind | Category | Handler provided by | Remember `allow` |
| :--- | :--- | :--- | :--- |
| `tool_call` | From the tool's metadata (D2), default `other` | This change | Per category (D9) |
| `personality_change` | `personality` | This change | Never |
| `self_change` | `self_change` | `add-self-improvement` | Never |
| `obsidian_note_write` | `other` | `add-obsidian-vault` | Only for operation `append`, scope connector and path. A create never |
| `coding_push` | `code_publish` | `add-coding-agent-delegation` | Never |
| `coding_project_cleanup` | `workspace_cleanup` | `add-coding-agent-delegation` | Never |
| `integration_credential` | `integration_credential` | `add-self-built-integrations` | Always on approve, scoped to the credential binding (D9) |
| `integration_egress` | `integration_egress` | `add-self-built-integrations` | Always on approve (D9) |
| `integration_tool_review` | `tool_review` | `add-self-built-integrations` | Rule-only kind, see below |

`integration_credential` is always remembered as an `allow` on approve, scoped to the integration, the credential name and the binding digest, because that rule is the grant (owner answer 89.4 of 2026-10-08): a new version with the same binding is covered by it, and a changed binding needs a new approval. `integration_tool_review` is a rule-only kind: no approval request is ever submitted for it. Its rules are the owner's tool reviews of `add-self-built-integrations` (scope `integration=<id>, tool=<name>, definition=<definition digest>`, effect `allow`), written by `ApprovalService.putRule` from that change's review endpoint and removed by `deleteRules` (D9). Its handler only builds the scope text.

A handler declares the category of its kind, and the application refuses to start when a handler declares a category other than the one in this table. A submission of a registered kind whose handler is not present (its change is not applied yet) is refused with an error naming the kind, and a submission of a kind that is not in the table is refused the same way. Handlers are found by kind in a map built at startup, and two handlers for one kind stop the application from starting.

A handler builds the scope text of its kind as `key=value` pairs joined by `, ` in a fixed key order, starting with the key of the object the rule is about (for example `integration=<id>, host=<host>` for `integration_egress`). That makes the prefix of a scope text name its object, which `deleteRules` relies on (D9).

Why kinds and not only tool modes: the personality change, the self changes, the note writes, the coding publish and cleanup and the integration actions are not tool calls the model makes. They are steps inside the agent's own code. One service with handlers keeps one record, one decision API and one audit trail for both, which the owner asked for.

### D4: The gate wraps callbacks in `ChatToolset`

`ChatToolset` (made in `add-agent-skills`, its D3 step 5) asks `ToolModeResolver` for the mode of every tool it returns for a request or run and wraps each `requires_approval` callback in `ApprovalGatedToolCallback`. The wrapper keeps the tool definition, so the model sees the same tool, and the prompt cache sees the same tool list bytes. Its `call(input, toolContext)`:

1. Canonicalises the input (RFC 8785) and refuses it with a tool error when it is larger than `app.approvals.max-arguments-bytes` (default 64 KiB). Refused input is never cut, because a cut action would not be the action that runs.
2. Computes the arguments digest, the scope digest from `scope-arguments` (the whole canonical input when the list is empty), and the definition digest (SHA-256 of the canonical JSON of name, description and input schema).
3. Looks up a remembered rule for tenant, tool and scope digest (D9). An `allow` rule executes the delegate at once. A `deny` rule returns a refusal naming the rule. Both are stored as an approval request decided by `rule`.
4. Otherwise branches on the tool context: with a `subagent_run_id` it pauses the run (D6), without one it leaves the call waiting as a main chat approval (D5).

The wrapper is the only place a gated tool can be reached from the model. The unwrapped delegate is used only by the execution of D7. An architecture test asserts that no code path other than `ApprovalService` calls a delegate of a gated tool.

Why not in `FilteredToolCallbackProvider`: the gate must cover agent native tools too, and `ChatToolset` is where every tool of a request is assembled once.

### D5: A main chat call waits as an approval request, shown in the run list

The main chat's tool loop runs inside one chat request of `StreamingChatExecutor`, so it cannot pause. The wrapper therefore creates the approval request of source `chat` and nothing else: the request is the only record of the waiting action (owner answer 89.4 of 2026-10-08), and no row of `subagent_run` is written for it. It publishes `ApprovalRequestedEvent`, so the turn sends `approval_required`, an event name this change adds itself to the closed event set of the chat stream of `add-chat-streaming-and-conversations` D2 (`{"approval": <approval view>}`, 0..n, non-terminal, one per call in the turn that needs approval, sent before the terminal `done` or `error`), with its row in that table's documentation in `apps/ascend-agent/AGENTS.md`, its OpenAPI entry on `POST /api/v1/ai/prompt/stream` and its serialization test (owner answer 93 of 2026-10-08), and `SubagentRunChangedEvent` with the run view below, so a streamed turn sends `run_started`. The tool result returned to the model is fixed text: the action waits for the owner's approval, it has not run, its approval id, tell the user, do not call the tool again for the same action. The model writes its answer and the turn ends.

The run list keeps showing it. `ApprovalRunViewSource`, this change's implementation of the port `RunViewSource` of `add-agent-subagents` (its D17), shows every approval request of kind `tool_call` and source `chat` as a run view of kind `approval`: its id and `approvalId` are the approval id, depth 1, background, the conversation and user of the request, the tool name as its description, no definition and no model. Its state is read from the record: `pending` is `awaiting_approval`, approved with execution `none` or `running` is `running`, `succeeded` is `done` with the result, `failed` or `unknown` is `failed` with `TOOL_ERROR`, `denied` is `failed` with `APPROVAL_DENIED`, `expired` is `failed` with `APPROVAL_EXPIRED`, and `cancelled` is `cancelled`. So `GET /api/v1/runs` (also with `kind=approval`), `GET /api/v1/runs/{id}`, its event stream and `POST /api/v1/runs/{id}/cancel` (which cancels the pending request with decided by `system`) work for it as before. Every change of such a request publishes `SubagentRunChangedEvent` with the new view after commit, which wakes the run event stream on every instance the way a run row's event does (`add-agent-subagents` D17).

A waiting request holds no thread, no slot and no heartbeat. It is a row. On approve, the instance that took the decision claims it (D7) and executes the stored action on a virtual thread. The execution is one tool call, not a run, so it takes no run slot. On deny or expiry nothing runs. The conversation learns the outcome through the finished runs block of `add-agent-subagents` D16: `ApprovalRunViewSource.takeUnreported` returns the final requests of the conversation whose `reported_at` is null and sets `reported_at` in the block's transaction, so each outcome is listed once with the tool name, the outcome and the start of the result.

Duplicates: a partial unique index on `(tenant_id, conversation_id, tool_name, arguments_digest) WHERE decision = 'pending'` makes a second identical call in the same conversation return the existing approval id instead of a second request. A model that retries after the "do not call again" text therefore cannot fill the queue with copies.

Alternative considered: keep the main chat HTTP request open until the decision (rejected by owner direction, a decision may take hours). Alternative considered: a run row of kind `approval` next to the approval request (the earlier design, replaced by owner answer 89.4 of 2026-10-08, because the run row copied every decision of the request and needed exceptions in the restart sweep, the slots and the report block). Alternative considered: a separate "decided approvals" block and stream (rejected: it would add a second report path next to the finished runs block and a second follow stream next to the run events, which the port `RunViewSource` avoids).

### D6: A subagent run pauses in place

Inside a run the wrapper is called on the run's own virtual thread by the run's user controlled tool loop. The wrapper creates the approval request of source `run` linked to the run, then calls `SubagentRunService.pauseForApproval(runId, approvalId)` of `add-agent-subagents` (its D10), which moves the run from `running` to `awaiting_approval`, stores the approval id on the run, releases the run's worker slot, pauses the deadline watchdog and applies the foreground detach below. The thread then blocks on a per approval waiter until the decision. Blocking a virtual thread costs no platform thread. The heartbeat keeps running, because the run's conversation exists only in this thread's memory. On approve the thread calls `resumeAfterDecision(runId)`, which takes a slot again (in arrival order, like a waiting run), moves the run back to `running` and resumes the watchdog, then executes through D7 and returns the real result to the loop. On deny or expiry it calls `resumeAfterDecision(runId)` too and returns the fixed denial or timeout text as the tool result, and the loop goes on, so the model can adapt or report. Cancel of the run sets the waiter, cancels the approval with decided by `system`, and the run ends `cancelled` as before.

Several agent instances run at once (owner answer 87 of 2026-10-08, CANON 26.1), so the decision is read from the shared row, never only from memory. When the decision lands on the instance that runs the paused run, the deciding call also sets the local waiter at once. In every case the waiter wakes at each run heartbeat interval of `add-agent-subagents` (its D14) and reads the decision of its `approval_request` row, so a decision taken by another instance reaches it within one interval. A cancel of the run written by another instance reaches it the same way, through the run's `cancel_requested_at` that the heartbeat reads (`add-agent-subagents` D15).

Foreground detach: when a paused run belongs to a tree whose root is a foreground run that the main chat waits for in a `Task` call, the root is marked background and that `Task` call returns at once with the run id and a note that the run waits for approval. The chat request then ends. The client disconnect rule of `add-agent-subagents` (cancel foreground runs) no longer applies to the tree, because it is now background. A foreground run started by another run is not detached, because only a thread waits for it, not an HTTP request. `pauseForApproval` applies it (`add-agent-subagents` D14a).

Why the paused subagent run is not made restart safe like a main chat approval: that would need its message history persisted and replayed, which `add-agent-subagents` rejected for good reasons (its D14). A restart closes it with `AGENT_RESTARTED`. A listener of `SubagentRunChangedEvent` of this change cancels, with decided by `system`, every pending approval whose `run_id` names a run that became final, so a late approval can never run an action whose run is gone.

### D7: Exact execution, at most once

Execution starts only after the decision row is committed as `approved`. Steps:

1. Claim: `UPDATE approval_request SET execution = 'running', executor_instance = ?, executed_at = now() WHERE id = ? AND decision = 'approved' AND execution = 'none'`. Zero rows means another caller has it, and this caller stops.
2. For `tool_call`: build the tool list of the stored tenant and tool context through `ChatToolset` without wrapping, find the stored tool name, refuse with `tool_unavailable` when it is missing, `tool_denied` when the tenant mode is now `denied`, and `tool_changed` when the definition digest differs. For an MCP tool the stored server name must match too, so a renamed collision can never send the call to another server.
3. Call the delegate with the stored canonical arguments and a tool context rebuilt from the stored `user_id`, `tenant_id`, `request_id`, `conversation_id` and, for a paused subagent run, its `subagent_run_id` and depth. The call runs inside `TenantContext.runAs(<stored tenant_id>, ...)` of `add-keycloak-login`, so code that reads `TenantContext.currentTenantId()` sees the request's tenant also hours after the request ended.
4. Store `succeeded` or `failed` with a short detail and the result capped to `app.approvals.result-max-chars` (default 4000).

While an execution is `running`, its instance renews `execution_heartbeat_at` at the run heartbeat interval of `add-agent-subagents` (its D14), the same liveness rule as runs. The expiry sweep of D8, which runs on exactly one instance per firing and once at startup before readiness, sets every `running` execution whose `execution_heartbeat_at` is older than `app.subagents.limits.heartbeat-stale-intervals` intervals (default 3, the setting of `add-agent-subagents`, so runs and executions share one liveness rule) to `unknown`, and it is never retried, because the tool may already have had its effect. `executor_instance` names the instance that claimed it, for the log and the view. This replaces a startup check of instance liveness, because an instance cannot know from its own memory whether another instance is alive (owner answer 87 of 2026-10-08). The result of a `tool_call` is also returned to the paused run, or becomes the result in the run view of a main chat approval (D5).

Why the server executes and not the model: the owner approved one exact action. A new model call after the decision could produce different arguments, and showing the owner one thing and running another is the failure this change exists to prevent.

### D8: Expiry

`app.approvals.timeout` (24 hours, owner decision of 2026-10-02, refused at startup when zero or negative) sets `expires_at` when a request is created. The upper bound `max-timeout` is removed (answer 93 of 2026-10-08), because nobody asked for it. The decision's conditional update also requires `expires_at > now()`, so a decision that arrives after the expiry time is refused with 409 even when the sweep has not run yet.

The sweep is the system task `approval-expiry-sweep` of `add-shared-scheduler`, registered by this change under that change's contract: a name in `SchedulerTaskName`, the five-field cron `app.scheduler.system-tasks.approval-expiry-sweep.cron` (default `* * * * *`, every minute, the shortest step a five-field cron has) and its zone `.time-zone` (default `UTC`). Exactly one agent instance runs each firing. `ApprovalExpirySweep` also runs once at startup before readiness, on the instance itself, so requests that expired while the agent was down are closed before any decision can arrive. Each run moves `pending` rows past `expires_at` to `expired` with a conditional update, one row at a time so each expiry fires its handler (a paused run reads the expiry at its next heartbeat, a main chat approval reads `failed` with `APPROVAL_EXPIRED` in the run view, `PersonalityProposalService.expire(approvalId)` counts and audits the expired proposal). The same run sets orphaned executions to `unknown` (D7). Running it twice is harmless, because the updates match only `pending` rows and stale `running` executions. The partial index on `expires_at WHERE decision = 'pending'` keeps it cheap. A timeout counts as a denial (owner direction): an action nobody looked at must not run. This is the one system task of this change on its tables: the retention of decided requests is an entry of the one retention task of `add-shared-scheduler` (D10, owner answer 89.7 of 2026-10-08).

The owner learns about every expiry, so he can ask again (owner decision of 2026-10-02):

- The sweep writes one owner notification per expired request through `OwnerNotificationService.create` of `add-shared-scheduler` (owner answer 89.6 of 2026-10-08), whose store belongs to the module `core-chat`, with source `approval` and kind `expired`. The pair is a row of that change's table `owner_notification_kind`, inserted by this change's own migration (D10, owner answer 93 of 2026-10-08). Its body names the approval's kind, the preview's first line and the approval id, and says that the action did not run and can be asked for again. The app and the plugin host deliver it like every other owner notification.
- For a main chat request the run view reads `failed` with `APPROVAL_EXPIRED`, so the next chat turn of the conversation lists it in the finished runs block (D5) and the assistant tells the owner that the action expired and offers to ask again. A paused subagent run receives the timeout text as its tool result and reports it in its own result.

Why 24 hours: the owner may be asleep or away from the phone, and most outside sends that matter can wait a day. A shorter value would expire useful requests overnight. A longer value keeps paused subagent runs in memory longer, which raises the chance that a restart closes them, and outlives the 24 hour lifetime of the Discord buttons of `add-openclaw-plugin-host`.

### D9: One-time decisions and remembered choices

A decision is one time by default. With `remember: true` the decision also writes an `approval_rule` row: tenant, kind, tool name (empty for a non-tool kind), scope digest, readable scope text (for example `channel=family`), effect `allow` or `deny`, the deciding user, the source approval, creation time and last use time. The unique key is `(tenant_id, kind, tool_name, scope_digest)`, and a newer decision replaces the effect of an older rule with the same key.

Categories and remembering, fixed in code so configuration cannot loosen them:

| Category | Remember `allow` | Remember `deny` |
| :--- | :--- | :--- |
| `personality` | Never | Never, a proposal is always a new text |
| `self_change` | Never | Yes |
| `integration_credential` | Always remembered on approve, scoped to the integration, the credential name and the binding digest, because the rule is the grant (owner answer 89.4 of 2026-10-08) | Yes |
| `tool_review` | Rule-only, written by `putRule` (below), never by a decision | Never |
| `spend_money` | Never | Yes |
| `outside_delete` | Never | Yes |
| `code_publish` | Never | Yes |
| `workspace_cleanup` | Never | Yes |
| `outside_message` | When the tool's `rememberable` is true (the default for this category is true) | Yes |
| `integration_egress` | Always remembered on approve, it is the first time rule | Yes |
| `other` | For a tool, when its `rememberable` is true. For another kind, when its handler allows it for that action (`obsidian_note_write`: only `append`) | Yes |

Owner decision of 2026-10-02: spending money and deleting outside data can never be remembered as an allow, whatever the configuration says.

Scope: for a tool, the values of the `scope-arguments` (canonical JSON of an object holding only those arguments, a missing argument counts as `null`). With no `scope-arguments` the scope is the whole canonical arguments, so a remembered allow then matches only the identical call. For another kind the handler builds the scope (D3): for `integration_egress` the integration id and the destination host, for `integration_credential` the integration id, the credential name and the binding digest, for `integration_tool_review` the integration id, the tool name and the definition digest, for `obsidian_note_write` the connector id and the note path.

A rule that no decision creates: `ApprovalService.putRule(tenantId, kind, toolName, scopeText, effect, decidingIdentity)` writes or replaces one rule of a rule-only kind (today only `integration_tool_review`), for the agent's own code only, never for a tool or a REST caller of `/api/v1/approvals`. The service checks `ADMIN` of the tenant on the deciding identity, refuses a kind that is not rule-only, stores the identity's user as `created_by` with no source approval, publishes `ApprovalRuleChangedEvent` and records `APPROVAL_RULE_CHANGED` (D15). `add-self-built-integrations` calls it from its tool review endpoint (owner answer 89.4 of 2026-10-08: reviewed tools are remembered rules).

Rules never expire on their own (owner decision of 2026-10-02). The owner removes them through `DELETE /api/v1/approvals/rules/{id}`.

Every rule change is published after commit as `ApprovalRuleChangedEvent` (rule id, tenant, kind, tool name, scope text, effect, and `created`, `replaced` or `removed`), so a component that derives state from rules, such as the egress reconciler of `add-self-built-integrations`, reacts at once. `ApprovalService.deleteRules(tenantId, kind, scopePrefix)` removes every rule of the tenant and kind whose scope text starts with the prefix (matched with `LIKE` after escaping `%`, `_` and `\` in the prefix), in one transaction, publishes one event per removed rule and records one audit event per removed rule. `add-self-built-integrations` calls it with `integration=<id>,` for each of its three kinds when an integration is removed, with `integration=<id>, credential=<name>,` when a credential is revoked, and with `integration=<id>, tool=<name>,` when a tool review is withdrawn. The prefix must be non-empty, so the call can never remove every rule of a kind by accident.

### D10: The tables

One Flyway versioned SQL migration `V<n>__create_action_approval.sql` in `apps/ascend-agent/src/main/resources/db/migration/` (`<n>` is the next free version at implementation time). Every constraint and index is named. The same migration inserts the notification pair `('approval', 'expired')` into the table `owner_notification_kind` of `add-shared-scheduler` with `ON CONFLICT DO NOTHING`, because that change's first migration holds no pair of a later change (owner answer 93 of 2026-10-08). The project is under development, so there is no data migration and no backfill. Owner answer 73.1 of 2026-10-06 confirms that the data in today's development stores is disposable.

Tenant column: both tables carry `tenant_id VARCHAR(64) NOT NULL`, written from `TenantContext.currentTenantId()` of `add-keycloak-login` (`default` in the personal deployment), with no foreign key. `add-tenant-isolation` (company, build group 5) creates the `tenants` table later and adds the foreign keys from `approval_rule.tenant_id` and `approval_request.tenant_id` to `tenants(id)` in its own migration (its decision 8 and task 2.3). This change does not wait for it. Every other foreign key of the two tables is in this change's own migration: `approval_request.run_id` to `subagent_run(id)`, `approval_request.rule_id` to `approval_rule(id)` and `approval_request.conversation_id` to `conversations(id)` with no delete action (owner answer 76.6 of 2026-10-08).

`approval_rule`:

| Column | Type | Notes |
| :--- | :--- | :--- |
| `id` | `UUID` primary key | |
| `tenant_id` | `VARCHAR(64)` not null | From `TenantContext.currentTenantId()`, no foreign key (see above) |
| `kind` | `VARCHAR(32)` not null | Check in the nine kinds of D3: `tool_call`, `personality_change`, `self_change`, `obsidian_note_write`, `coding_push`, `coding_project_cleanup`, `integration_credential`, `integration_egress`, `integration_tool_review` |
| `tool_name` | `VARCHAR(128)` not null default `''` | |
| `scope_digest` | `CHAR(64)` not null | |
| `scope_text` | `VARCHAR(500)` not null | |
| `effect` | `VARCHAR(8)` not null | Check in `allow`, `deny` |
| `created_by` | `VARCHAR(255)` null | Set to null by user erasure |
| `source_approval_id` | `UUID` null | |
| `created_at`, `last_used_at` | `TIMESTAMPTZ` | |

Unique `(tenant_id, kind, tool_name, scope_digest)`.

`approval_request`:

| Column | Type | Notes |
| :--- | :--- | :--- |
| `id` | `UUID` primary key | |
| `tenant_id` | `VARCHAR(64)` not null | From `TenantContext.currentTenantId()`, no foreign key (see above) |
| `user_id` | `VARCHAR(255)` null | The user whose request caused it. Null only for source `system`, and then `conversation_id` and `run_id` are null too (a named check constraint ties the three to the source) |
| `conversation_id` | `UUID` null | The conversation, the same type as `subagent_run.conversation_id` and `conversations.id`, with the foreign key `fk_approval_request_conversation` to `conversations(id)` of `add-chat-streaming-and-conversations` and no delete action, the same rule as `fk_subagent_run_conversation` of `add-agent-subagents` D13, because conversation delete removes the conversation's rows itself in its transaction (owner answer 76.6 of 2026-10-08) |
| `run_id` | `UUID` null | FK to `subagent_run(id)` `ON DELETE SET NULL` |
| `request_id` | `VARCHAR(64)` null | |
| `source` | `VARCHAR(8)` not null | Check in `chat`, `run`, `system` (D3) |
| `kind` | `VARCHAR(32)` not null | Check in the nine kinds of D3: `tool_call`, `personality_change`, `self_change`, `obsidian_note_write`, `coding_push`, `coding_project_cleanup`, `integration_credential`, `integration_egress`, `integration_tool_review` |
| `category` | `VARCHAR(32)` not null | Check in the eleven categories of D9: `personality`, `self_change`, `integration_credential`, `integration_egress`, `tool_review`, `outside_message`, `spend_money`, `outside_delete`, `code_publish`, `workspace_cleanup`, `other` |
| `tool_name`, `tool_server`, `tool_original_name` | `VARCHAR(128)`, `VARCHAR(64)`, `VARCHAR(128)` | Null for a non-tool kind |
| `definition_digest` | `CHAR(64)` null | |
| `arguments` | `TEXT` not null | Canonical JSON |
| `arguments_digest` | `CHAR(64)` not null | |
| `scope_digest` | `CHAR(64)` not null | |
| `scope_text` | `VARCHAR(500)` not null | |
| `preview` | `TEXT` not null | |
| `rememberable` | `BOOLEAN` not null | |
| `decision` | `VARCHAR(16)` not null | Check in `pending`, `approved`, `denied`, `expired`, `cancelled` |
| `decided_by` | `VARCHAR(8)` null | Check in `owner`, `rule`, `timeout`, `system` |
| `decided_by_user` | `VARCHAR(255)` null | |
| `decision_channel` | `VARCHAR(16)` null | Check in `rest`, `app`, `discord` |
| `rule_id` | `UUID` null | FK to `approval_rule(id)` `ON DELETE SET NULL` |
| `execution` | `VARCHAR(16)` not null default `none` | Check in `none`, `running`, `succeeded`, `failed`, `unknown` |
| `execution_detail` | `VARCHAR(1000)` null | |
| `executor_instance` | `VARCHAR(64)` null | |
| `execution_heartbeat_at` | `TIMESTAMPTZ` null | Renewed while the execution is `running` (D7) |
| `result` | `TEXT` null | Capped |
| `reported_at` | `TIMESTAMPTZ` null | When the finished runs block listed the outcome of a main chat approval (D5) |
| `created_at`, `expires_at`, `decided_at`, `executed_at` | `TIMESTAMPTZ` | |
| `version` | `BIGINT` not null | Optimistic lock and `ETag` |

Index on `approval_rule`: `(tenant_id, kind, scope_text text_pattern_ops)` for the prefix match of `deleteRules`.

Indexes on `approval_request`: `(tenant_id, created_at DESC)`, `(tenant_id, user_id, created_at DESC)`, `(tenant_id, kind, created_at DESC)` for the filtered views (the proposal screen of `add-agent-soul` and the run list), `(run_id)`, `(conversation_id)` for the conversation delete, partial `(conversation_id) WHERE reported_at IS NULL AND source = 'chat' AND kind = 'tool_call'` for the finished runs block, partial `(expires_at) WHERE decision = 'pending'`, partial `(execution_heartbeat_at) WHERE execution = 'running'`, the partial unique index of D5, and `(decided_at)` for retention. Decisions and execution claims are conditional updates (`WHERE decision = 'pending'`, `WHERE execution = 'none'`), the same pattern as the run table, so racing callers on any instance cannot both win. The pending limit per tenant (D13) is checked and the row inserted in one transaction that first takes the transaction-level Postgres advisory lock of the tenant, so two instances cannot both pass the count (owner answer 87 of 2026-10-08).

Retention (owner answer 89.7 of 2026-10-08): decided requests are deleted `app.approvals.retention` (default 30 days, the run retention) after `decided_at` by the shared retention task `record-retention` of `add-shared-scheduler` (its D15), through the `RetentionEntry` bean `approval-request` that this change registers with no `@ConditionalOnModule`: table `approval_request`, time column `decided_at`, age `app.approvals.retention`, and the fixed condition `decision <> 'pending' AND kind <> 'personality_change'`. A pending request is never deleted by retention. A personality proposal is kept like the proposal rows were before answer 89.4, so the proposal screen keeps its history. For the same reason the conversation delete (task 5.1) cancels a pending `personality_change` request of the conversation like every pending request, and then sets its `conversation_id` to null instead of deleting it, because the proposal belongs to the tenant's personality, not to the conversation, and holds no text of the conversation. Rules are kept until removed. This change registers no retention system task of its own.

### D11: REST, view and channels

`ApprovalController` under `/api/v1/approvals`, contract in the `action-approval-decisions` spec. The view is one record, `ApprovalView`, used by the controller, the `approval_required` event and `ApprovalChangedEvent`, which is published after commit on every change so the plugin host follows approvals without touching approval code. Cursor pagination encodes `(created_at, id)` as an opaque base64 cursor, the same as the run list, with the page sizes `default-page-size` and `max-page-size` of D13.

Channels:

- REST. Bruno requests cover list, read, approve, deny, rules list and rule removal.
- The mobile app (made in `add-flutter-chat-app`): it shows the `approval_required` event as a card with the preview, the exact arguments, approve and deny buttons and a "remember this choice" switch (shown only when `rememberable`), reads `GET /api/v1/approvals?state=pending` when it opens, when it comes back to the foreground and after every `approval_required` or `subagent_status` event, and sends the decision with `channel: app` and the digest of the view it shows.
- Discord, through `add-openclaw-plugin-host` (its D12). A listener of `ApprovalChangedEvent` writes an `approval_prompt` row into its outbox `channel_outbox` for a new pending approval, with the view and the `argumentsDigest`, and an `approval_update` row for every later change. The host posts the prompt with Approve and Deny buttons that are the action types `approval_approve` and `approval_deny` of the one action endpoint `POST /api/v1/channel-host/actions` of that change (owner answer 89.6 of 2026-10-08). The button carries the outbox id, never the digest, because a digest does not fit Discord's 100 character limit. A press calls that endpoint with the action type, the outbox id and the presser's account id. The agent resolves the presser through the channel link to an agent user and calls `ApprovalService.decide` with that user as the deciding identity, the digest from the outbox row, `remember: false` and channel `discord`. The same `ADMIN` and digest checks as on REST apply (D12), so a press from an account linked to a non-admin user, or from an account with no link, is refused. Buttons live 24 hours, the same as the approval timeout.

### D12: Who decides, and why the model never can

- Decide: an authenticated caller with `ADMIN` of the approval's tenant, owner decision of 2026-10-02 (a non-admin user never decides, not even for his own chat). In the personal deployment the owner's Keycloak account holds `ADMIN`. This change adds its own rows to the authorization matrix of `add-keycloak-login` (its D4): `/api/v1/approvals/*/approve`, `/deny` and the rules endpoints `ADMIN` only, the list and read endpoints for an authenticated caller scoped by the controller (task 4.3).
- `ApprovalService.decide(approvalId, decision, argumentsDigest, remember, channel, decidingIdentity)` takes the deciding identity as an argument: the user id, the tenant and the roles. `ApprovalController` builds it from the authenticated principal. The plugin host relay of `add-openclaw-plugin-host` builds it from the agent user linked to the platform account that pressed the button. The service, not the caller, checks `ADMIN` of the approval's tenant and the digest, so every channel goes through the same checks, and it stores the identity's user id as `decided_by_user`.
- No tool can decide, list for decision, or change rules. A test reads the tool list of a chat turn and of a run and asserts it (task 6.4).
- A chat message never decides, whatever it says. The model only sees text, and treating "yes" in chat as an approval would let any injected text that the model repeats count as the owner.
- The digest echo makes a stale or tampered client screen fail with 409 instead of approving something the owner did not see. The stored action is immutable after creation, so the digest also proves which action was approved in the audit trail.
- The tool definition digest stops a "rug pull": an MCP server that changes what a tool does between request and approval cannot reuse the approval.
- Under the `dev` profile of `add-keycloak-login` the decision endpoints are open like every other endpoint. The startup banner logs one WARN line saying that any caller who reaches port 9917 can decide approvals. The production guard of `add-keycloak-login` (its D21) keeps `dev` out of a public deployment. Requests from a sandbox workspace cannot reach the agent, because its egress proxy refuses private addresses (`add-agent-sandbox` D6), and the web reading tools only send `GET`, which the decision endpoints refuse. The browser server of `add-mcp-tool-servers` can send any request, but it reaches no private address because of its own egress proxy.

### D13: Configuration

`ApprovalProperties` binds `app.approvals`:

| Key | Default | Meaning |
| :--- | :--- | :--- |
| `timeout` | `24h` | Time until a pending request expires (owner decision of 2026-10-02) |
| `max-pending-per-tenant` | `20` | Pending requests per tenant |
| `max-arguments-bytes` | `65536` | Largest canonical arguments |
| `result-max-chars` | `4000` | Stored result length |
| `retention` | `30d` | Retention of decided requests, the age of this change's entry in the one retention task of `add-shared-scheduler` |
| `default-page-size` | `20` | Page size of `GET /api/v1/approvals` when the caller gives no `limit` |
| `max-page-size` | `100` | Largest `limit` of `GET /api/v1/approvals` |

The deployment default list is `app.policy.default.approval-required-tools` (D1), empty by default, plus the tools the registered `ApprovalDefaultsSource` beans mark. The schedule of the one system task is a key of `add-shared-scheduler`: `app.scheduler.system-tasks.approval-expiry-sweep.cron` (default `* * * * *`) with its `.time-zone` (default `UTC`). The application refuses to start on a zero or negative value, and refuses an `ApprovalDefaultsSource` that gives an unknown category or a blank `scope-arguments` entry.

Settings (owner rule 98 of 2026-10-08). Every key with a default is a setting: `application.yaml` writes `key: ${ENV:default}`, `ApprovalProperties` carries the same default, the `ascend-agent` service of `compose.yaml` writes `- ENV=${ENV:-default}`, and each gets one row in `apps/ascend-agent/docs/CONFIGURATION.md` whose description ends "Added by `add-action-approvals`." in the same commit (task 1.1). ENV is Spring Boot's canonical environment form of the property:

| Property | Environment variable | Default |
| :--- | :--- | :--- |
| `app.approvals.timeout` | `APP_APPROVALS_TIMEOUT` | `24h` |
| `app.approvals.max-pending-per-tenant` | `APP_APPROVALS_MAXPENDINGPERTENANT` | `20` |
| `app.approvals.max-arguments-bytes` | `APP_APPROVALS_MAXARGUMENTSBYTES` | `65536` |
| `app.approvals.result-max-chars` | `APP_APPROVALS_RESULTMAXCHARS` | `4000` |
| `app.approvals.retention` | `APP_APPROVALS_RETENTION` | `30d` |
| `app.approvals.default-page-size` | `APP_APPROVALS_DEFAULTPAGESIZE` | `20` |
| `app.approvals.max-page-size` | `APP_APPROVALS_MAXPAGESIZE` | `100` |
| `app.policy.default.approval-required-tools` | `APP_POLICY_DEFAULT_APPROVALREQUIREDTOOLS` | empty (comma separated tool names) |
| `app.scheduler.system-tasks.approval-expiry-sweep.cron` and `.time-zone` | `APP_SCHEDULER_SYSTEMTASKS_APPROVALEXPIRYSWEEP_CRON` and `APP_SCHEDULER_SYSTEMTASKS_APPROVALEXPIRYSWEEP_TIMEZONE` (`add-shared-scheduler` D2) | `* * * * *` and `UTC` |

Read from other changes, not new settings here: the stale interval count of an execution is `app.subagents.limits.heartbeat-stale-intervals` and the heartbeat interval is `app.subagents.limits.heartbeat-interval` of `add-agent-subagents` (D7), and the length of a proposal's reason is `app.soul.reason-max-chars` of `add-agent-soul` (D3). Kept as constants, because they are not operational: the kinds, categories, sources and decision values (closed enums of D3, D9 and D10), the column sizes of D10 (`scope_text` 500, `execution_detail` 1000, schema), the canonical JSON rule (RFC 8785) and the SHA-256 digests (formats), the fixed tool result text of D5, the error codes of D16 and the metric names of D14. The 24 hour life of the Discord buttons belongs to `add-openclaw-plugin-host`.

Removed by answer 93 of 2026-10-08, because nobody asked for them and none of them gated a tool: `enabled` (approvals are always on, so a sending tool can never run unasked because of a switch), `max-timeout`, and the block `tools.<name>.category`, `.rememberable` and `.scope-arguments` (D1, D2).

### D14: Metrics, logs and traces

Names follow `add-observability` D2 and D5 with the domain `approval.`, as listed in the `action-approval-gate` spec. No approval id, tool name, tenant, user, scope or argument as a tag. The AI Pipeline dashboard gains one row with pending approvals, decisions by outcome, wait time and executions by outcome.

Logs: one INFO line per creation, decision and execution with the fields of the spec. Arguments, preview and result only at DEBUG. One WARN line per refused submission (unknown kind, too large, too many pending), per digest mismatch and per `tool_changed`.

Traces: creation is a span in the chat turn's or run's trace. Execution is an `Observation` named `approval.execute`, with the creating span recorded as a link because it may run hours later in another trace.

### D15: Audit, erasure and export

`ApprovalService` records four events through `AuditEventPort` of `add-deployment-modules`: `APPROVAL_REQUESTED`, `APPROVAL_DECIDED` (outcome `APPROVED`, `DENIED`, `EXPIRED` or `CANCELLED`, with decided by and channel), `APPROVAL_RULE_CHANGED` (created or removed) and `APPROVED_ACTION_EXECUTED` (outcome `SUCCEEDED`, `FAILED` or `UNKNOWN`). Each event holds the tenant, the actor, the approval id as its target, and the kind, category, tool name and arguments digest, never the arguments, the preview or the result. The default `LogAuditEventPort` writes each one as a structured INFO log line. Because an audit write may be lost, the approval row stays the source of truth.

`add-audit-and-gdpr-compliance` (company, build group 5) registers its `AuditRecorder` backed implementation of `AuditEventPort` later, which stores the four events as audit rows with its closed action vocabulary (made there). It also owns erasure and export of the two tables later: user erasure deletes the user's `approval_request` rows (their arguments may hold personal data) and sets `created_by` of the user's rules to null, a request of source `system` belongs to no user so only tenant erasure and retention remove it, user export includes the user's approval requests, and tenant erasure deletes both tables' rows of the tenant (tasks 5.3 and 5.4 moved there in the dependency fix of 2026-10-05). This change does not wait for it.

### D16: Errors

New `ApiErrorCode` values, added by this change to the enum of `upgrade-spring-boot-4` D19: `approval_not_found` (404), `approval_already_decided` (409), `approval_digest_mismatch` (409), `approval_forbidden` (403), `approval_not_rememberable` (400), `approval_rule_not_found` (404). Errors inside a gated tool call (too large, too many pending, unknown kind) are tool results for the model, never HTTP errors of the chat request.

## Required edits to other changes

This change does not edit any other change. Each edit below was asked of the named change, and every one of them is now made there, checked on 2026-10-03 and noted under its heading. No task here waits for an edit. A task that uses an edit of a change that lands earlier uses it as it is. A company change of build group 5 registers its implementation later, and no task here waits for it.

### `add-tenant-policy`

Company, build group 5. It registers its implementation later, and this change does not wait for it. Made in that change, checked on 2026-10-03 (its proposal "What Changes", its D3, D4 and D5, and `specs/tool-policy/spec.md`):

1. Proposal "What Changes" and design D2: a third tool mode. Next to the tool allow-list, a tenant policy holds an approval-required list. A tool on both is `requires_approval`: it is given to the model, and its calls go through the approval gate of this change. A tool not on the allow-list stays `denied`.
2. Design D3: the deployment default gains `app.policy.default.approval-required-tools` (empty by default), and the effective approval list is the union of the default and the tenant's list, so a tenant can add tools and can never remove one the default lists.
3. Design D4 and task 1.1: the `tenant_policy` row gains a JSONB column for the approval-required list.
4. `specs/tool-policy/spec.md`: a requirement that a `requires_approval` tool is offered to the model and never runs before an approval, with a scenario, and that the policy API reads and updates the approval list under the same narrow-only rule.
5. `TenantPolicyService` implements the `ToolModeResolver` interface of this change (D1), so the gate reads the mode through it, and the default `ConfigToolModeResolver` then does not exist.

### `add-agent-subagents`

That change lands earlier (build group 4, position 2) and builds every part below with stub callers, so it waits for nothing of this change. The text of answer 89.4 of 2026-10-08 was sent to it on 2026-10-08 through `inbox93/add-agent-subagents__from__add-action-approvals.md`, and its worker writes it there (its D10, D13, D14, D14a, D16, D17, D19 and its `subagent-run-status` spec):

1. Its `specs/subagent-run-status/spec.md` holds six states, `waiting`, `running`, `awaiting_approval`, `done`, `failed` and `cancelled`, with the moves `running` to `awaiting_approval`, `awaiting_approval` to `running`, `awaiting_approval` to `cancelled` and `awaiting_approval` to `failed`, and the reasons `APPROVAL_DENIED` and `APPROVAL_EXPIRED` in the closed failure set, used in the run view of a main chat approval (D5).
2. Design D13: `subagent_run` has `kind` with five run kinds, `subagent`, `coding`, `scheduled`, `self_review` and `integration`. A main chat approval is not a row of it (owner answer 89.4 of 2026-10-08). `approval_id` (`UUID` null) names the approval a run in `awaiting_approval` waits for. The state check holds `awaiting_approval`.
3. Design D17: the run view carries `kind` and `approvalId` from its first version, and the port `RunViewSource` (`page`, `find`, `cancel`, `takeUnreported`) merges the views of a registered source into the run list, the read, the cancel, the event stream and the finished runs block. This change registers `ApprovalRunViewSource` (D5).
4. Design D10: `SubagentRunService.pauseForApproval(runId, approvalId)` and `resumeAfterDecision(runId)`. A run in `awaiting_approval` holds no worker slot and its deadline watchdog is paused, so waiting time never counts against `max-duration-per-run`.
5. Design D14: the restart sweep has no exception for approvals, because no approval is a run row. Paused runs of kind `subagent` keep their heartbeat and are closed with `AGENT_RESTARTED`, and the `SubagentRunChangedEvent` of that close is how this change cancels their pending approvals (D6).
6. Design D14a and the `Task` tool: when a run in a tree whose root is a foreground run of the main chat pauses for approval through `pauseForApproval`, the root becomes a background run and the waiting `Task` call returns at once with the run id and a note that the run waits for approval.
7. Design D16: the finished runs block also lists the outcomes that `RunViewSource.takeUnreported` returns, here the main chat approvals with the tool name, the outcome and the start of the result.
8. Design D19: the gauge `subagent.runs.active` has the `state` value `awaiting_approval`, for paused runs. Pending approvals are counted by `approval.pending` of this change.

### `add-agent-soul`

Made in that change on 2026-10-02 and changed there on 2026-10-08 for owner answer 89.4 (its D7, D8, Non-Goals and its row for this change under "Required edits to other changes"). Both changes are planned by the same worker:

1. Design D7: the soul change has no proposal table. `personality_propose` validates the content and hands the proposal (base commit, proposed content, reason) to the soul port `PersonalityProposalPort`, which has no implementation in the soul change, so the tool is offered only once an implementation exists. This change registers `ApprovalPersonalityProposalPort` (D3, task 3.7): `submit` creates the approval request of kind `personality_change` and returns its id, which is the proposal id the tool result and `fileChanges` name. There is nothing to bridge at the first start, because no proposal exists before this change lands (this replaces owner decision 65.25 of 2026-10-04).
2. Design D7: the soul change has no approve or reject endpoint. The owner decides through `/api/v1/approvals/{id}/approve` and `/deny` of this change. The read endpoints `GET /api/v1/personality/proposals` and `GET /api/v1/personality/proposals/{id}` stay in the soul change and read the approval requests of kind `personality_change` through the port, as the proposal screen's filtered approval view.
3. Design D7: `PersonalityProposalService` offers `diff(baseCommit, content)`, `approve(approvalId, proposal)`, `reject(approvalId)` and `expire(approvalId)`. This change calls `diff` for the preview, `approve` on approval, `reject` on a denial and `expire` on a timeout (D3, D8). The proposal status is read from the approval record (D3).
4. Its Non-Goals line: deciding a personality proposal belongs to this change, whose `ApprovalService` decides every proposal through `/api/v1/approvals`. Nothing else is needed there.

### `add-chat-streaming-and-conversations`

Made in that change, checked on 2026-10-03 (its D2 event table, its conversation delete steps, `specs/chat-streaming/spec.md` and `specs/conversation-management/spec.md`):

1. Design D2 and `specs/chat-streaming/spec.md` "SSE event schema": the non-terminal event `approval_required` (`{"approval": <approval view>}`, 0..n), emitted before the terminal event when a call in the turn needs approval. Since owner answer 93 of 2026-10-08 that change no longer reserves the name, and this change adds it to the closed event set itself (D5, task 5.1). The approval view is the one in this change's `action-approval-decisions` spec.
2. Conversation delete: cancel the conversation's pending approvals with decided by `system` before its runs are cancelled, then, in the same Postgres transaction as the history rows, delete the conversation's `approval_request` rows, the delete rule of `subagent_run` (owner answer 76.6 of 2026-10-08), except that a `personality_change` request keeps its row with `conversation_id` set to null (D10). Since the dependency fix of 2026-10-05 the code is this change's task 5.1 (moved from that change's task 9.2). Its two e2e rows (moved from that change's tasks 10.2 and 10.5 as this change's tasks 9.6 and 9.7) were removed by owner answer 91.3 of 2026-10-08: the conversation delete row repeated `ApprovalConversationDeleteIT`, and the streamed `approval_required` event is now checked by the scripted spec of task 7.4.

### `add-flutter-chat-app`

Made in that change, checked on 2026-10-03 (its D3, D10 and D11, its `specs/flutter-chat/action-approvals/spec.md` and its task group 14). The card and the pending approvals screen sit in its own `action-approvals` spec rather than in its core chat spec, which changes nothing here:

1. `specs/flutter-chat/core-chat/spec.md`: a requirement that an `approval_required` event shows an approval card in the conversation with the preview, the exact arguments, the expiry time, an Approve button, a Deny button and a "remember this choice" switch shown only when `rememberable` is true.
2. The same spec: pressing a button sends `POST /api/v1/approvals/{id}/approve` or `/deny` with `channel: app`, the `argumentsDigest` of the view on screen and the switch value, and the card shows the outcome or the problem detail `detail` of a refusal (409 shows "already decided" and reloads the view).
3. A pending approvals screen reachable from the conversation list, filled from `GET /api/v1/approvals?state=pending` when the app opens, when it returns to the foreground and after each `approval_required` or `subagent_status` event.
4. Design section 3: the API client gains the approval endpoints and the `approval_required` event.

### `add-audit-and-gdpr-compliance`

Company, build group 5. It registers its `AuditEventPort` implementation later, and this change does not wait for it. Made in that change, checked on 2026-10-03 (its audit action table, its erasure table, `specs/audit-logging/spec.md`, `specs/data-erasure/spec.md` and `specs/data-portability/spec.md`). The four events reach it through `AuditEventPort`, and the tasks that store them and erase and export the two tables are its own (moved from this change's tasks 5.3 and 5.4 in the dependency fix of 2026-10-05):

1. `specs/audit-logging/spec.md` and design line 42: add `APPROVAL_REQUESTED`, `APPROVAL_DECIDED`, `APPROVAL_RULE_CHANGED` and `APPROVED_ACTION_EXECUTED` to the closed action vocabulary, with details that hold the approval id, kind, category, tool name and arguments digest and never the arguments.
2. `specs/data-erasure/spec.md`: user erasure deletes the user's `approval_request` rows and sets `created_by` of their `approval_rule` rows to null. Tenant erasure deletes both tables' rows of the tenant.
3. `specs/data-portability/spec.md`: user export includes the user's approval requests.
4. Owner answer 89.4 of 2026-10-08, sent on 2026-10-08 through `inbox93/add-audit-and-gdpr-compliance__from__add-action-approvals.md`: the tables `personality_proposal` of `add-agent-soul` and `integration_tool_review` of `add-self-built-integrations` no longer exist. Their data are approval requests of kind `personality_change` and rules of kind `integration_tool_review`, covered by the erasure and export of the two tables of this change.

### `add-agent-skills`

Made in that change (its D3 step 5 and its row for this change under "Required edits to other changes"), checked on 2026-10-03:

1. Made. Design D3: `ChatToolset` also wraps every tool whose mode is `requires_approval` in the approval gate of this change, after the policy filter, so the gate covers every MCP and agent native tool in this one place. Since the dependency fix of 2026-10-05 the code step is this change's task 2.7 (moved from `add-agent-skills` task 10.6).

### `add-keycloak-login`

Its D4 table of later changes lists this change's rows (split of 2026-10-04 from `add-auth-and-identity`, owner rule of 2026-10-04). `add-keycloak-login` lands before this change, so this change adds the rows itself (task 4.3):

1. Its role matrix: `POST /api/v1/approvals/*/approve`, `POST /api/v1/approvals/*/deny`, `GET /api/v1/approvals/rules` and `DELETE /api/v1/approvals/rules/*` need tenant `ADMIN`. `GET /api/v1/approvals` and `GET /api/v1/approvals/*` need an authenticated caller, scoped by the controller.

### `add-shared-scheduler`

1. The owner notification store, part of the module `core-chat`: it accepts source `approval` with kind `expired` (owner decision of 2026-10-02, made in that change), used by the expiry notice of D8 (title fixed by the source and kind, body naming the approval's kind, the first preview line and the approval id). The one system task name `approval-expiry-sweep` is added to `SchedulerTaskName` by this change under that change's registration contract, and the retention of decided requests is one entry of that change's one retention task (owner answer 89.7 of 2026-10-08, D10), so no other edit is needed there.

### Edits other changes asked of this change, made here

- `add-mcp-tool-servers` (its "Required edits", `add-action-approvals` items 1 to 3): D1 adds `ApprovalDefaultsSource` with `McpToolModeDefaults` as one source, D2 no longer says that the default list holds no MCP tool and takes MCP tool metadata from the server entry only, and D12 names the browser server and its egress proxy.
- `add-obsidian-vault`: D2 and D3 register kind `obsidian_note_write`, category `other`, a remembered allow only for `append` scoped to connector and path, handler provided by that change.
- `add-openclaw-plugin-host` (its "Required edits", `add-action-approvals` items 1 and 2): D11 describes the Discord buttons through its outbox, D12 and the `action-approval-decisions` spec make `decide` take the deciding identity, with the Discord scenarios.
- `add-file-download` and `add-download-ingestion` (its agent part since the split of 2026-10-04): D2 lists file download among the own MCP tools that stay `allowed`, and `knowledge_add_download` of `add-download-ingestion` stays `allowed` too.
- `add-coding-agent-delegation`: D3 and D9 register kind `coding_push` with the category `code_publish`, and kind `coding_project_cleanup` (owner answer 47.1 of 2026-10-02) with the category `workspace_cleanup` for its question to the owner before it cleans coding projects when free disk space falls below 10 percent. Neither can be remembered as an allow. That change provides both handlers. D3 and D10 add the source `system` (owner decision 49.2 of 2026-10-03), so its system task `coding-area-free-space-check` submits a `coding_project_cleanup` approval with no user, no conversation and no run, and the tenant `ADMIN` decides it.
- `add-self-improvement`: D3 and D9 register kind `self_change` with the category `self_change`, never remembered as an allow, remembered as a deny. That change provides the handler, whose preview is the unified diff and whose deny and expiry mark the change `refused`.
- `add-self-built-integrations`: D3 names that change as the provider of the `integration_credential` and `integration_egress` handlers, and D9 adds `ApprovalRuleChangedEvent` and `ApprovalService.deleteRules(tenantId, kind, scopePrefix)`, which that change calls with this exact signature. Owner answer 89.4 of 2026-10-08 adds, sent to that change on 2026-10-08 through `inbox93/add-self-built-integrations__from__add-action-approvals.md`: an `integration_credential` approval always remembers its grant as an `allow` rule scoped to the binding, the rule-only kind `integration_tool_review` (category `tool_review`) holds the tool reviews, and `ApprovalService.putRule` writes them (D3, D9). That change stops copying decisions into `integration_destination`, `integration_credential` and `integration_tool_review`, and reads the states of its views from the approval and rule records.

### Checked, no edit needed

- `upgrade-spring-boot-4`: this change adds its six codes to `ApiErrorCode` itself, the way every sibling change does.
- `add-tenant-isolation` (company, build group 5): it lands after this change, and its migration adds the foreign keys from `approval_rule.tenant_id` and `approval_request.tenant_id` to `tenants(id)` (its decision 8 and task 2.3, D10 here). This change does not wait for it. Owner answer 89.4 of 2026-10-08 removes `personality_proposal` and `integration_tool_review` from its table lists, sent on 2026-10-08 through `inbox93/add-tenant-isolation__from__add-action-approvals.md`.
- `add-deployment-modules`: approvals belong to `core-chat`, because the personality proposal and every gated tool need them whatever modules are on. The controller and the system tasks carry no module marking and are in the `core-chat` list of its coverage test.
- `add-usage-metering-and-quotas`: an approved tool that is metered writes its ledger row through the existing tool wrapper, with the paused run's id from the run context that `add-agent-subagents` already binds, and with no run id for a main chat approval. Model spend is not an approval matter.
- `add-agent-sandbox`: its network allow-list stays configuration only. `add-self-built-integrations` uses kind `integration_egress` for a first outside send.

## Risks / Trade-offs

- [The owner never sees a request and an important send expires] → The tool result tells the user in the same turn, the app lists pending requests, Discord posts a prompt, and an expiry is reported to the owner by a notification and in the next chat turn, so he can ask again. A timeout is a denial on purpose, because the opposite would let unseen actions run.
- [A prompt injection makes the model call a gated tool many times] → One request per identical call per conversation (D5), at most 20 pending per tenant, and each one needs the owner.
- [A remembered allow is broader than the owner thought] → `scope-arguments` default to the whole call, the scope text is shown in the rule list, rules can be removed, and money, deletes, personality, self changes, code publishing and workspace cleanup can never be remembered as an allow. A credential grant is remembered only for its exact binding (integration, credential name, host, header and path prefixes), so a changed binding asks again.
- [An MCP server changes a tool between request and approval] → the definition digest check refuses execution with `tool_changed`.
- [A paused subagent run is lost on restart] → it is closed and its approval cancelled, never run late. Main chat approvals survive restarts.
- [Execution crashes midway] → `unknown`, never retried. The owner sees it in the view and the audit trail and can check the outside system.
- [The `dev` profile of `add-keycloak-login` is active in a local stack] → the decision endpoints are as open as every other endpoint, the banner says so, and the sandbox and the web tools cannot reach them.
- [Discord buttons stop working after 24 hours] → equal to the approval timeout, so a button never outlives its request. The app and the REST list work from any client.
- [The expiry sweep runs once a minute] → a decision after `expires_at` is refused by the decision's own condition, so the sweep only closes rows and sends the notice, at most one minute late.
- [Several agent instances (owner answer 87 of 2026-10-08)] → claims, decisions, the duplicate rule and the expiry are Postgres conditional updates, a partial unique index and a db-scheduler task that one instance runs per firing. The pending limit takes a tenant advisory lock. A paused run on another instance learns the decision from the shared row at its next heartbeat, at most one interval later, and an orphaned execution is found by its stale `execution_heartbeat_at`, not by an instance's own memory. No state of this change lives only in one instance's memory, except the waiter of a paused run, which the shared row backs.

## Migration Plan

1. Land at build group 4, position 5 of the owner build order of 2026-10-04, after `close-agent-test-gaps`, `upgrade-spring-boot-4`, `add-keycloak-login`, `add-deployment-modules`, `add-shared-scheduler`, `add-chat-streaming-and-conversations`, `add-agent-skills`, `add-agent-subagents` and `add-agent-soul`. Every required edit of this change is made in its target change (checked on 2026-10-03). `add-flutter-chat-app` lands later and carries its own part. `add-tenant-policy` and `add-audit-and-gdpr-compliance` (company, build group 5) register their implementations later, and no task here waits for them.
2. Flyway applies the new migration on startup. There is no data to move.
3. With the empty configuration list, nothing changes for chat or runs until the owner lists a tool or turns on an outside MCP server whose entry gates tools. `personality_propose` of `add-agent-soul` is offered from this start on, because this change registers the implementation of its proposal port, and every proposal is an approval request from then on.
4. Rollback: deploy the previous image. The tables stay and are ignored. Flyway runs forward only, so removing them is a new versioned migration, written only if the owner asks for it.

## Owner decisions of 2026-10-02

The five questions of the first draft are answered, and the design follows the answers:

1. The timeout is 24 hours, and a timeout counts as a denial. When a request expires, the assistant tells the owner through a notification and in the next chat turn, so he can ask again (D8).
2. Spending money and deleting outside data can never be remembered as an allow, fixed in code (D9).
3. Remembered choices never expire on their own. The owner removes them from the rule list (D9).
4. Only the tenant `ADMIN` decides, also for messages caused by another user's chat (D12).
5. The default tool list stays as designed: the configuration list ships empty, and outside MCP servers bring their gated tools through their entries (D1, D2).

## Owner decisions of 2026-10-06

Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores. This change needs none of today's data. It creates its two tables empty and starts from empty stores.

## Owner decisions of 2026-10-07

Answer 75.1: the owner approved the fix of every item of the review of the group 3, 4 and 5 changes of 2026-10-07. Fixed here: item 23 (`action_approval.conversation_id` is a `UUID`, like `subagent_run.conversation_id`), item 60 (the decision endpoints under the `dev` profile of `add-keycloak-login`), item 61 (a run has six states) and item 63 (the scripted spec of task 7.4 is in group B).

## Owner decisions of 2026-10-08

Answer 76.6: `approval_request.conversation_id` gets the same foreign key to `conversations(id)` and the same delete rule as `subagent_run.conversation_id` of `add-agent-subagents` (checked on 2026-10-08 in its D13, task 2.1 and `subagent-run-status` spec: the key `fk_subagent_run_conversation` with no delete action, and the conversation delete cancels the runs that are not final and deletes the rows in the same transaction as the history). Here the key is `fk_approval_request_conversation` with no delete action, and the conversation delete cancels the pending approvals with decided by `system` and then deletes the conversation's `approval_request` rows in the same transaction as its history (D10, the edit to `add-chat-streaming-and-conversations`, tasks 1.2, 5.1 and 9.6, `specs/action-approval-decisions/spec.md`). A deleted conversation's approvals are therefore no longer readable after the delete: `GET /api/v1/approvals/{id}` answers 404 `approval_not_found`. The approvals of source `system` have no conversation and are not touched.

Answer 76.2: the scripted model of the shared harness of `close-agent-test-gaps` is Mockoon (the `mockoon/cli` image, pinned by version and digest). This change adds its script rules to the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json`, which holds every rule of every change, and keeps its reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/approvals/` (tasks 7.4 and 9.7, spec `action-approval-decisions`). Every check that read the request journal now reads the scripted model's request log, `GET /mockoon-admin/logs` of the Mockoon admin API, and clears it with `POST /mockoon-admin/state/purge`.

Answer 77.2 (accepted): after a conversation delete, its approvals answer 404, and the `system` decision of a cancelled pending approval is proved by the unit test of the delete only (task 5.1).

Answer 77.3: the names `fk_approval_request_conversation` and `ApprovalConversationDeleteIT` stay.

Approved fix of 2026-10-08: every deterministic spec of this change that runs a scripted chat turn wipes in AscendMemory the memories of its users in its Reset state and Post-run cleanup (`POST /api/v1/memory/wipe` with the provider `openai` and the service token), because the memory extraction of a scripted turn embeds through the scripted model into `ascend_memory_1536` (task 7.4, which already wiped and now names the call). Superseded by answer 91.1 below for the deterministic phase.

Answer 85.1: every key and secret lives in the repository `.env`, never in the shell. No plan text of this change exports a secret. The scripted spec of task 7.4 runs in the deterministic phase of `close-agent-test-gaps` D7, where the test overlay is copied into the running agent and every key comes from `.env` (updated by answer 98.1 below: no `SPRING_PROFILES_ACTIVE` change and no `e2e` profile).

Answer 87 (rule R1, CANON 26.1): several agent instances run at once, and every mechanism of this change was checked for it. Kept: `executor_instance`, the conditional decision and claim updates, the partial unique duplicate index, and the expiry sweep on the shared scheduler (one instance per firing). Changed: the paused run's waiter reads the decision from the shared `approval_request` row at every run heartbeat interval instead of relying on one instance (D6), an orphaned execution is found by its own `execution_heartbeat_at` in the expiry sweep instead of a startup liveness check of instance ids (D7, D10), and the pending limit takes a transaction-level advisory lock of the tenant so two instances cannot both pass the count (D10). Cancels of a paused run come through the run row's `cancel_requested_at` (`add-agent-subagents` D15), and run list updates of a main chat approval wake the run event stream through `SubagentRunChangedEvent` on every instance (D5).

Answer 88 (rule R2): every company plug-in point stays: `ToolModeResolver` with its default `ConfigToolModeResolver` for `add-tenant-policy`, `AuditEventPort` for `add-audit-and-gdpr-compliance`, the tenant column of both tables for the foreign keys of `add-tenant-isolation`, and the source `system`.

Answer 89.4: `approval_request` is the only record of an approval and `approval_rule` the only record of a remembered decision. A main chat approval is no longer also a run row of kind `approval`: it is shown in the run list, the run read, cancel and event stream and the finished runs block through `ApprovalRunViewSource`, the implementation of the port `RunViewSource` of `add-agent-subagents` (D5). A paused subagent run pauses and resumes with the real tool result through `pauseForApproval` and `resumeAfterDecision` of that change (D6). A personality proposal is an approval request of kind `personality_change` whose payload holds the base commit, the proposed text and the reason, there is no `personality_proposal` table and no bridge at the first start, and the proposal screen of `add-agent-soul` reads it through the soul port `PersonalityProposalPort`, which this change implements (D3, task 3.7). Decided proposals are kept by retention and keep their row on a conversation delete (D10). The credential approval of `add-self-built-integrations` stays and its grant is an `allow` rule scoped to the credential binding, approved hosts stay `integration_egress` rules, and reviewed tools are rules of the new rule-only kind `integration_tool_review`, written by the new `ApprovalService.putRule` (D3, D9, D10). The text for `add-agent-subagents`, `add-self-built-integrations`, `add-tenant-isolation` and `add-audit-and-gdpr-compliance` was sent through `inbox93`.

Answer 89.7: the retention of decided requests is one entry of the one retention task of `add-shared-scheduler` (table `approval_request`, time column `decided_at`, age `app.approvals.retention`, decided rows other than `personality_change` only), so the system task `approval-retention` is gone and only `approval-expiry-sweep` works on the approval tables (D8, D10, D13, task 5.5).

Answer 90: checked, no test-only setting or branch of this change is in real logic or service configuration. The gated tool `write_note` of the scripted spec is listed only in the test overlay `apps/ascend-agent/e2e/overlay/application-e2e.yaml` (task 7.4).

Answer 91.1: the scripted spec of task 7.4 runs in the deterministic phase of `close-agent-test-gaps` D7, where the agent's semantic memory points at the AscendMemory fake under the route prefix `/ascend-memory/` of `e2e-scripted-model`. AscendMemory is never restarted, there is no dummy key, and the spec no longer wipes memories (task 7.4). Answer 91.2: the fake MCP server `e2e-fake-mcp` that gives the spec its gated `write_note` is the one fake MCP server class of the agent's test sources, packaged as `ascend-e2e-fake-mcp:local` by `close-agent-test-gaps` task 4.2, and this change writes no fake MCP server of its own.

Answer 91.3: this change keeps one deterministic spec, the scripted spec of task 7.4, because it proves what no lower test proves: a gated call made over the live MCP connection to the fake MCP server, the streamed `approval_required` event on the live stack (moved in from task 9.7), the call reaching the fake exactly once after approve, and the result in the next turn. Its requests that repeated `ApprovalRunIT`, `SubagentApprovalPauseIT`, `ApprovalRuleIT`, `ApprovalDecisionTest` and `ApprovalSafetyTest` (chat text saying approve, wrong digest, approve again, deny, remembered choice, the paused subagent run and its definition) are removed. The endpoint-only spec of tasks 9.1 and 9.2 is removed, because `ApprovalControllerTest` and `ApprovalSecurityTest` prove each of its requests. The conversation delete row of task 9.6 is removed, because it seeded rows with psql and proved only what `ApprovalConversationDeleteIT` proves. Task 7.7 is removed, because the spec `<N>-soul-scripted` of `add-agent-soul` is removed by the same answer. The AI-run proposal requests of task 7.6 stay.

Answer 89.1: `StreamingChatExecutor` of `add-chat-streaming-and-conversations` is the one chat executor, and the gate of this change works inside it once, for the blocking and the streaming endpoint alike (Context, D5).

Answer 89.6: the expiry notice is created through `OwnerNotificationService.create` of `add-shared-scheduler` (D8), and the Discord Approve and Deny buttons are the action types `approval_approve` and `approval_deny` of the one action endpoint `POST /api/v1/channel-host/actions` of `add-openclaw-plugin-host`, whose handlers call `ApprovalService.decide` exactly as before, with the digest from the outbox row, `remember: false`, channel `discord` and the linked user (Context, D11).

Answer 93: this change adds the chat stream event name `approval_required` itself, because `add-chat-streaming-and-conversations` no longer reserves it (D5, task 5.1), and its migration inserts its notification pair `('approval', 'expired')` into `owner_notification_kind` of `add-shared-scheduler` (D10, task 1.2). Also removed with no feature cut: the `app.approvals.tools.*` block, which described no gated tool (D1, D2), the keys `enabled` and `max-timeout`, which nobody asked for (D8, D13), and the second system task on the approval tables (`approval-retention`, now a retention entry, D10). Kept, because removing them would cut a feature or a multi-instance mechanism: `executor_instance` (R1).

Answer 94.5: the new change `scale-ocr-and-audio-across-containers` takes build group 3, position 5, directly after `harden-cloud-deployment`, so `add-deployment-modules` is now position 6, `add-shared-scheduler` 7, `add-document-management-api` 8 and `add-chat-streaming-and-conversations` 9 (`openspec/BUILD_ORDER.md`). Every position of those changes that this change names was moved by one. Nothing else in this change changes.

Answer 98: every value of this change that has a default is a setting with an environment variable, the same default in code and a compose line `${VAR:-default}` on `ascend-agent`, listed in D13, with its row in `apps/ascend-agent/docs/CONFIGURATION.md` in the same commit (task 1.1). Made external: the five `app.approvals` keys D13 already had, the new page sizes `app.approvals.default-page-size` (20) and `app.approvals.max-page-size` (100) that the list endpoint had written as fixed numbers, the deployment default list `app.policy.default.approval-required-tools` (empty) and the cron and zone of `approval-expiry-sweep`. The stale execution rule now reads `app.subagents.limits.heartbeat-stale-intervals` of `add-agent-subagents` instead of a fixed three intervals, and the reason length reads `app.soul.reason-max-chars` of `add-agent-soul` (D3, D7). Kept as constants, with the reason in D13: the closed enums, the column sizes, the digest and canonical JSON formats, the fixed tool result text, the codes and the metric names. No test or measurement of this change uses LM Studio as a default.

Answer 98.1: there is no test line in `compose.yaml` and no `e2e` profile. In the deterministic phase the test overlay `apps/ascend-agent/e2e/overlay/application-e2e.yaml`, which holds `write_note` in the approval list, is copied into the running agent as `/app/config/application.yaml` and the agent is restarted, and the end step recreates the agent from its image, with the steps of `close-agent-test-gaps` D7 (task 7.4, Answer 85.1 above).

## Open Questions

None.
