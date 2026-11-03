## Purpose

Makes every subagent run visible and controllable: a persisted record with its state, parent run, parent conversation, cost so far and last step, a REST API to list, read and cancel runs, a stable view and change event that a later Discord bot and the mobile app can use, clean handling of runs that were in flight when the agent restarted, and the metrics and logs of runs.

## ADDED Requirements

### Requirement: Every run is a persisted record

Every subagent run, foreground or background, and every run of the other kinds below, SHALL be stored in PostgreSQL from the moment it is accepted until the retention period ends. The record SHALL hold: run id, kind, parent run id (empty for a run started by the main chat or with no parent), root run id, tenant id, conversation id (empty only for a run with no conversation), user id, depth, the approval id and the scheduled job id when the kind has them, definition name and the git version of the definition used when the kind has a definition, the task description, the provider and model used, whether it runs in the background, state, the times it was created, started, last updated and finished, input and output tokens, cost so far in US dollars, whether usage was estimated, the cost, token and time limits that apply to it, the last step (at most 500 characters) and its time, the result text when done, and the failure reason and detail when failed or cancelled. The schema SHALL be created by one Flyway versioned SQL migration, with every constraint and index named explicitly. An applied migration file SHALL NOT be edited, and any later schema change SHALL be a new versioned migration. The conversation id SHALL be a nullable `UUID` column with the foreign key `fk_subagent_run_conversation` to `conversations(id)` of `add-chat-streaming-and-conversations`, which lands earlier.

#### Scenario: A run cannot name a conversation that does not exist

- **WHEN** the `conversations` table exists and a run row is inserted whose conversation id names no conversation
- **THEN** the database refuses the insert

#### Scenario: Background run is visible while it works

- **WHEN** a background run has made two model calls and is executing a tool
- **THEN** reading the run returns state `running`, tokens and cost greater than zero, and a last step that names the tool

#### Scenario: Schema is created by the Flyway migration

- **WHEN** the agent starts against an empty PostgreSQL database
- **THEN** Flyway applies the migration and the run table, its named constraints and its named indexes exist
- **AND** Flyway validation of the applied migrations passes

### Requirement: The run table holds one closed set of kinds

Every run SHALL have one kind from a closed set: `subagent` (a run of a definition), `coding` (a coding agent run), `scheduled` (a firing of a scheduled job), `self_review` (a self-improvement review) and `integration` (a build of a self-built integration). This capability owns the table, the states, the failure reasons and the kind set, and the first migration SHALL already hold every kind, state and reason, so a change that adds the behaviour of a kind never alters the table's checks. A check constraint SHALL tie the columns a kind needs to the kind: a `subagent` run SHALL have a definition, a conversation, a prompt and a model, and a `scheduled` run SHALL have a scheduled job id. An approval id SHALL be set only on a run in state `awaiting_approval`. A main chat tool call that waits for the owner SHALL NOT be a row of this table. A registered `RunViewSource` MAY show it in the run list, the read, the cancel, the event stream and the finished runs block with kind `approval`.

#### Scenario: A row of kind approval is refused

- **WHEN** a row of kind `approval` is inserted
- **THEN** the insert is refused by the kind check

#### Scenario: Every kind is accepted from the first migration

- **WHEN** the agent starts against an empty PostgreSQL database and one row of each of the five kinds is inserted with the columns its kind needs
- **THEN** every insert succeeds

### Requirement: A run moves through six states in one direction

A run SHALL be in one of `waiting`, `running`, `awaiting_approval`, `done`, `failed` or `cancelled`. The allowed moves SHALL be `waiting` to `running`, `waiting` to `cancelled`, `waiting` to `failed`, `running` to `done`, `running` to `failed`, `running` to `cancelled`, `running` to `awaiting_approval`, `awaiting_approval` to `running`, `awaiting_approval` to `cancelled` and `awaiting_approval` to `failed`. A run of kind `approval` SHALL be created in state `awaiting_approval`. `done`, `failed` and `cancelled` SHALL be final. A move that is not allowed SHALL be refused and SHALL NOT change the record. Every failure SHALL carry one reason from a closed set: `COST_LIMIT`, `TOKEN_LIMIT`, `TIME_LIMIT`, `QUOTA_EXCEEDED`, `MODEL_ERROR`, `TOOL_ERROR`, `AGENT_RESTARTED`, `AGENT_SHUTDOWN`, `DEFINITION_UNAVAILABLE`, `INTERNAL_ERROR`, `APPROVAL_DENIED`, `APPROVAL_EXPIRED`, `CODING_AGENT_ERROR`, `SANDBOX_ERROR`, `REPOSITORY_ERROR`, `PROVIDER_LIMIT`, `DISK_LOW`, `INTEGRATION_VERIFY_FAILED` or `INTEGRATION_IMAGE_FAILED`. A cancelled run SHALL record who cancelled it: `owner`, `parent` or `cascade`.

A run in state `awaiting_approval` SHALL hold no worker slot, and its time limit SHALL be paused, so waiting for the owner never counts against the run's time limit. When it moves back to `running` it SHALL take a slot again in arrival order. Every kind SHALL take its slots from one slot pool with a limit per run kind, whose counts hold across every agent instance. Runs of kind `coding`, `integration` and `self_review` SHALL take their slots from pools of their own, never from the subagent worker slots. The pool of kind `integration` SHALL bound only the builds that run at once, and SHALL let any number of builds wait in arrival order.

#### Scenario: Finished run cannot be revived

- **WHEN** something tries to move a `done` run back to `running`
- **THEN** the record stays `done`

#### Scenario: Waiting for approval holds no slot

- **WHEN** 4 worker slots are configured, 4 runs are `running`, and one of them moves to `awaiting_approval`
- **THEN** a waiting background run becomes `running`
- **AND** the paused run's time limit does not count the time it spends in `awaiting_approval`

#### Scenario: A paused run is closed by the restart sweep

- **WHEN** the process of a run in state `awaiting_approval` dies and the sweep runs
- **THEN** the run is `failed` with reason `AGENT_RESTARTED`

### Requirement: The run list merges the views of every run view source

The run list SHALL include the views of every registered `RunViewSource`, merged newest first by creation time and id with the same opaque cursor. The read, the cancel and the event stream of an id the run table does not hold SHALL be answered by the source that holds it. With no source registered, the run list SHALL hold run rows only.

#### Scenario: A source item is merged into the list

- **WHEN** a stub source holds one pending item older than one run row and newer than another
- **THEN** `GET /api/v1/runs` lists the three newest first
- **AND** a page of `limit=1` followed by its cursor walks them in that order

### Requirement: Runs can be listed, read and cancelled through REST

The agent SHALL expose:

- `GET /api/v1/runs` with optional filters `conversationId`, `parentRunId`, `kind` (repeatable), `state` (repeatable) and `updatedSince`, newest first, with cursor pagination (`limit` at most the configured maximum page size, 100 by default, the configured default page size when absent, 20 by default, and an opaque `cursor`).
- `GET /api/v1/runs/{id}`: one run, with an `ETag` that changes on every update, answering 304 to a matching `If-None-Match`.
- `POST /api/v1/runs/{id}/cancel`: answers 202 and moves a `waiting`, `running` or `awaiting_approval` run and every descendant that is not final to `cancelled`. Cancelling a run that is already `cancelled` SHALL answer 202 again without change. Cancelling a `done` or `failed` run SHALL answer 409.

These endpoints SHALL be part of the core chat and SHALL exist whatever deployment modules are active, so runs of every kind can be followed even when the module `subagents` is off. Every read and cancel SHALL be limited to runs of the caller's tenant. A personal deployment runs as the tenant `default`. A caller SHALL see and cancel only runs of their own user id, and a caller with the `ADMIN` role SHALL see and cancel every run of their tenant, through this change's own rows in the authorization matrix of `add-keycloak-login`. A run id that does not exist or that the caller may not see SHALL answer 404.

#### Scenario: List runs of a conversation

- **WHEN** a conversation has started three runs and the caller lists runs with that `conversationId`
- **THEN** the response holds exactly those three runs, newest first

#### Scenario: Cancel reaches the running work and its children

- **WHEN** the owner cancels a `running` run that has a `running` child
- **THEN** the response is 202
- **AND** within 5 seconds both runs are `cancelled`, the parent with `owner` and the child with `cascade`
- **AND** no model call or tool call of either run starts after the cancel was accepted

#### Scenario: Cancelling a finished run

- **WHEN** the owner cancels a `done` run
- **THEN** the response is 409 and the run stays `done`

#### Scenario: Foreign run is hidden

- **WHEN** a non admin user reads a run of another user
- **THEN** the response is 404

#### Scenario: Tenant admin sees every run of the tenant

- **WHEN** a caller with the `ADMIN` role lists runs
- **THEN** the response holds the runs of every user of the caller's tenant

#### Scenario: Another tenant's run is hidden

- **WHEN** an `ADMIN` of tenant A reads or cancels a run of tenant B
- **THEN** the response is 404 and the run is unchanged

### Requirement: The run view and change event are ready for other clients

The JSON view of a run SHALL be the same in the list, the single read, and the change event, and SHALL use these fields: `id`, `kind`, `parentRunId`, `rootRunId`, `conversationId`, `approvalId`, `scheduledJobId`, `subagent`, `description`, `depth`, `state` (lower case), `background`, `provider`, `model`, `createdAt`, `startedAt`, `updatedAt`, `finishedAt`, `durationMs`, `costSoFarUsd`, `tokens` (`input`, `output`, `estimated`), `limits` (`costUsd`, `tokens`, `timeMs`), `lastStep` (`text`, `at`), `failure` (`reason`, `detail`, `cancelledBy`) and, when done, `result`. Times SHALL be ISO 8601 in UTC. Adding a field later SHALL NOT rename or remove an existing one. On every state change and every last step change, the agent SHALL publish an in-process event carrying this view, so a later Discord bot, a push notification or the sandbox of `add-agent-sandbox` (which removes a run's container when the run is final) can follow runs without changing run code.

#### Scenario: Same view everywhere

- **WHEN** a run is read through the single read, the list, and the change event of its last update
- **THEN** the three views have the same fields with the same values

#### Scenario: Every state change publishes an event

- **WHEN** a run goes from `waiting` to `running` to `done`
- **THEN** three events are published in that order, with states `waiting`, `running` and `done`

### Requirement: A client can follow a run after its chat request has ended

A background run SHALL keep working after the HTTP request or stream of the chat turn that started it has ended, for any reason, including a client disconnect. `GET /api/v1/runs/{id}/events` SHALL answer with a `text/event-stream` that first sends one `subagent_status` event with the current run view, then one `subagent_status` event for every later change, and ends after the event that carries a final state. Each event SHALL carry the run's update counter as its SSE `id`. A client that reconnects with `Last-Event-ID` SHALL receive the current view only when it is newer than that id, then the later changes, so a dropped connection can be resubscribed without missing the final state. The same access rules as `GET /api/v1/runs/{id}` SHALL apply. Following a run that is already final SHALL send its final view once and end. A client connected to one agent instance SHALL receive the changes of a run that works on another agent instance as well, within one second, or within the poll interval of the fallback when the shared notification is lost.

When a chat turn is served as a stream, the stream SHALL send a `run_started` event with the run view when the turn starts a run, and a `subagent_status` event for every change of that run while the stream is open. Both events SHALL be non-terminal. When a chat turn ends because its client disconnected, the foreground runs of that turn SHALL be cancelled with `cancelledBy` `parent`, and its background runs SHALL keep working. When a run pauses in `awaiting_approval` inside a tree whose root is a foreground run of the main chat, the root SHALL become a background run and the waiting `Task` call SHALL return at once with the run id and a note that the run waits for approval, so the tree is not cancelled when the chat request ends.

#### Scenario: Background run outlives the chat request

- **WHEN** a chat turn starts a background run and the client disconnects before the run finishes
- **THEN** the run keeps working and ends `done`
- **AND** `GET /api/v1/runs/{id}` returns the final view

#### Scenario: A run on another instance is followed

- **WHEN** a client follows `GET /api/v1/runs/{id}/events` on one agent instance while the run works on another instance and moves to `done`
- **THEN** the client receives a `subagent_status` event with state `done` and the stream ends

#### Scenario: Resubscribe after a dropped connection

- **WHEN** a client following `GET /api/v1/runs/{id}/events` loses the connection after the event with id 3, and reconnects with `Last-Event-ID: 3` after the run moved to `done`
- **THEN** the client receives one `subagent_status` event with state `done` and the stream ends

#### Scenario: Stream announces a started run

- **WHEN** a streamed chat turn calls `Task` with `run_in_background: true`
- **THEN** the turn's stream carries a `run_started` event with the run id before its terminal event

### Requirement: Runs in flight at a restart are closed, never resumed

When the agent starts, every run in state `waiting`, `running` or `awaiting_approval` that was owned by an agent process that is no longer alive SHALL be moved to `failed` with reason `AGENT_RESTARTED`, and the conversation SHALL be told in its next chat turn as for any finished run. A run SHALL NOT be resumed or started again automatically, because its tools may already have had side effects. A running run, a waiting run and a run of kind `subagent` paused in `awaiting_approval` SHALL renew a heartbeat at a fixed interval, and such a run whose heartbeat is older than three intervals SHALL be treated as owned by a process that is no longer alive, so a crash is handled the same way as a restart. Besides the sweep at startup, the periodic sweep SHALL run as the system task `run-orphan-sweep` of the shared scheduler, on exactly one agent instance at a time. On a graceful shutdown, the agent SHALL stop accepting new runs, SHALL cancel every run it owns, and SHALL record them as `failed` with reason `AGENT_SHUTDOWN` before the process exits.

#### Scenario: Restart closes a running run

- **WHEN** the agent process is killed while a background run is `running` and the agent starts again
- **THEN** that run is `failed` with reason `AGENT_RESTARTED`
- **AND** no new model call is made for it

#### Scenario: A source item survives a restart

- **WHEN** a registered `RunViewSource` shows a pending item and the agent restarts
- **THEN** `GET /api/v1/runs/{id}` of that item still answers 200 with state `awaiting_approval`

#### Scenario: Graceful shutdown

- **WHEN** the agent receives a stop signal while a run is `running`
- **THEN** the run is `failed` with reason `AGENT_SHUTDOWN` when the process exits

### Requirement: Finished runs are reported back to their conversation

At the start of each main chat turn, the agent SHALL add to the turn's dynamic system message a short block listing the runs of that conversation that finished since the conversation's previous turn, each with run id, kind, subagent name (or for a main chat approval shown through a `RunViewSource` the tool name), final state, cost, and the first 500 characters of its result or its failure reason. A run of kind `coding` SHALL also name its result endpoint. A run of kind `self_review` SHALL never be listed, and a run with no conversation has no block to appear in. A run SHALL be listed in at most one turn. Items of every registered `RunViewSource` that finished since the previous turn SHALL be listed the same way and only once. The static system prefix SHALL NOT change, so prompt caching keeps working.

#### Scenario: Background result reaches the next turn

- **WHEN** a background run finishes between two chat turns of its conversation
- **THEN** the second turn's dynamic system message lists that run with its state and the start of its result
- **AND** the third turn's message does not list it again

### Requirement: Finished runs are kept for a configured time

Runs SHALL be deleted one run tree at a time (a run started by the main chat or with no parent, with all its descendants), when every run in the tree is final and the last of them finished longer ago than a configured retention period (default 30 days). A tree with any run that is not final SHALL NOT be deleted by retention. Retention SHALL run as the entry of this table in the one shared retention task of the shared scheduler, on exactly one agent instance at a time.

#### Scenario: Old run tree is removed

- **WHEN** a `done` run and its `done` child both finished more than the retention period ago and the retention job runs
- **THEN** neither run exists any more and reading either answers 404

#### Scenario: Tree with live work is kept

- **WHEN** a run finished long ago but one of its background children is still `running`
- **THEN** the retention job deletes neither

### Requirement: Runs are measured and logged

The agent SHALL publish: a counter of runs started by depth and origin of the definition, a counter of runs finished by state and reason, a timer of run duration by state, a gauge of runs `waiting`, `running` and `awaiting_approval` by state and kind, a counter of subagent tokens by provider and token type, a counter of subagent cost in US dollars by provider, and a counter of limit hits by limit (`depth`, `concurrency`, `queue`, `cost`, `tokens`, `time`, `model`). Metric tags SHALL NOT include the run id, the definition name, the user id or any free text. Every state change SHALL produce one log line with the run id, parent run id, tenant id, conversation id, definition name, depth, state, reason, tokens and cost. Every log line written while a run works, including lines of the tools it calls, SHALL carry the run id and depth as log fields. The prompt and the result SHALL NOT be logged at INFO level or above. Each run SHALL be one trace span that is a child of the span of the chat turn or run that started it.

#### Scenario: Limit hit is visible

- **WHEN** a run is stopped for cost
- **THEN** the limit hit counter with limit `cost` grows by one
- **AND** the finished counter with state `failed` and reason `COST_LIMIT` grows by one

#### Scenario: Tool log lines carry the run

- **WHEN** a run calls an MCP tool
- **THEN** the agent's log lines for that tool call carry the run id and the depth

### Requirement: A streamed turn reports and follows the runs it starts

A streamed turn of `POST /api/v1/ai/prompt/stream` SHALL write `run_started` for the first change event of each run it starts and `subagent_status` for each later change of that run while the stream is open, both before the terminal event. Both event names SHALL be added by this capability to the closed event set of the chat stream, with their OpenAPI entries on the stream operation. The turn SHALL read the changes of its runs from the shared run store, so a run that works on another agent instance still reaches the stream. A client disconnect SHALL cancel only the turn's foreground runs, recorded with `cancelledBy` `parent`, and SHALL leave its background runs working.

#### Scenario: Stream announces and follows a started run

- **WHEN** a streamed turn starts a background run and the run changes state twice while the stream is open
- **THEN** the stream carries one `run_started` event and two `subagent_status` events with the run view, all before the terminal event

#### Scenario: Client disconnect cancels foreground runs only

- **WHEN** a streamed turn has started one foreground run and one background run and the client closes the connection
- **THEN** the foreground run is cancelled with `cancelledBy` `parent`
- **AND** the background run keeps working and can be followed through `GET /api/v1/runs/{id}/events`

### Requirement: Runs belong to a conversation and go with it

`subagent_run.conversation_id` SHALL be a nullable `UUID` column that references `conversations.id` by a foreign key. Deleting a conversation SHALL cancel its runs that are not final and SHALL delete its `subagent_run` rows in the same transaction as its history.

#### Scenario: Run rows reference a conversation

- **WHEN** Flyway has run to the latest version
- **THEN** `subagent_run.conversation_id` has the type `uuid` and carries a foreign key to `conversations.id`
- **AND** inserting a `subagent_run` row whose `conversation_id` names no conversation is refused

#### Scenario: Delete removes the conversation's runs

- **WHEN** the owner deletes a conversation with one running run and one finished run
- **THEN** the running run is cancelled
- **AND** no `subagent_run` row of that conversation is left

### Requirement: Run cancels are audited

Every accepted `POST /api/v1/runs/{id}/cancel` and every cancel of a foreground run on a client disconnect SHALL be published as one audit event through the audit event port of the deployment modules capability with the action `SUBAGENT_RUN_CANCELLED`, carrying the actor, the tenant, the run id, the run's kind, who cancelled it (`owner` or `parent`) and the number of descendants cancelled with it by cascade. Descendants cancelled by cascade SHALL NOT get events of their own. No audit event SHALL contain a prompt or a result.

#### Scenario: Owner cancel audited once

- **WHEN** the owner cancels a `running` run that has two `running` children and a capturing audit event port is registered
- **THEN** the port receives one `SUBAGENT_RUN_CANCELLED` event for that run with `owner` and a cascade count of two
- **AND** no `SUBAGENT_RUN_CANCELLED` event exists for either child

### Requirement: Subagent and run behaviour is covered by end-to-end tests

The repository SHALL hold end-to-end tests for subagent definitions and runs against the live stack in `apps/ascend-agent/e2e/`. Every behaviour that an HTTP status, a response body or persisted state can prove on the live stack, and that no unit or integration test already proves, SHALL be checked by a deterministic spec whose Bruno requests call no AI model. The nesting depth limit, the cost limit, the queue limit and the run events of a streamed turn SHALL be checked by unit and integration tests, not by an end-to-end spec. No spec of subagents SHALL need the scripted model or the fake MCP server of the shared e2e harness. Only the behaviours that need a real model to judge, finding a definition and delegating to it in the foreground and in the background, SHALL be checked by an AI-run spec. Pass criteria SHALL be HTTP status, response bodies, the run event stream, the run table and the definition history only, never log lines. Every spec SHALL be listed in the full-stack run scenarios and the ascend-agent service suite of `docs/E2E_RUN_SCENARIOS.md`, and the owner SHALL be asked which scenario to run before any run.

#### Scenario: Definition and run endpoints are checked without a model

- **WHEN** the deterministic subagents spec runs against the live stack
- **THEN** every request of `docs/api/request/AscendAI/ascend-agent/testing/subagents-api/` passes its status and body assertions
- **AND** no request of that folder names a provider or a model

#### Scenario: A background run is followed to its end

- **WHEN** the AI-run spec asks the agent to delegate work in the background and follows the returned run through `GET /api/v1/runs/{id}/events`
- **THEN** the chat answers before the run is final
- **AND** the stream ends with a `subagent_status` event with state `done`
- **AND** `GET /api/v1/runs/{id}` returns the same final view with a `result`

#### Scenario: An owner cancel is visible end to end

- **WHEN** the AI-run spec cancels a running background run through `POST /api/v1/runs/{id}/cancel`
- **THEN** the call answers 202 and within 5 seconds the run reads `cancelled` with `cancelledBy` `owner`
