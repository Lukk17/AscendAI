## Purpose

Lets the main agent find a loaded subagent through the shared capability index and hand it a task, in the foreground or in the background, with nesting up to a configured depth, the tools its definition allows and never more than its parent has, shell and file tools only inside an isolated sandbox, the model it asks for when that model is allowed, and hard limits on how many run at once, what each run may cost, how many tokens it may use and how long it may take.

## ADDED Requirements

### Requirement: The main chat can start a subagent through a Task tool

The main chat SHALL offer a tool named `Task` whose input has `description`, `prompt`, `subagent_type`, and the optional `model`, `resume` and `run_in_background`. When search is turned on (`app.skills.search.enabled` is true), its description SHALL NOT list the loaded subagents, and it SHALL tell the model to find a subagent with the `skill_search` tool of `add-agent-skills` filtered to the type `subagent`, and then to call `Task` with the name found. When search is turned off, `skill_search` is not offered, and the `Task` description SHALL instead list the name and description of every definition of the caller's tenant that was loaded when the chat turn or run started, in name order, with characters that could open or close a markup element escaped, the same fallback the `Skill` tool of `add-agent-skills` uses for skills. The `Task` call SHALL resolve the name in the definitions of the caller's tenant that were loaded when the chat turn or run started, never in the search index. A call naming a subagent that is not loaded SHALL return a tool error naming the requested subagent and telling the model to search with `skill_search`, without starting a run. A call with `resume` set SHALL return a tool error stating that resume is not supported, without starting a run. A foreground call SHALL return the subagent's final answer together with its run id. A background call SHALL return the run id at once.

The main chat SHALL also offer a tool named `TaskOutput` that takes a run id, an optional `block` flag and an optional timeout in milliseconds (at most the configured maximum wait, 600000 by default), and returns the run's state and, when finished, its result or failure. It SHALL return the run of the same conversation only, and SHALL answer an unknown or foreign id with a tool error.

Adding these tools SHALL NOT register a second tool provider that could expose MCP tools of a server that is not connected.

The subagent definitions, their registry, the definition endpoints and the tools `Task`, `TaskOutput` and the definition write tool SHALL be the module `subagents` of the deployment module catalog, which requires the module `skills`. The run record, the run service, the run loop, the run endpoints under `/api/v1/runs` and the run sweeps SHALL be part of the core chat and SHALL exist in every deployment, whatever modules are active, because runs of other kinds use them. There SHALL be no separate configuration flag that turns the subagent feature on or off. When `subagents` is not in the module list the agent reads from `ASCEND_MODULES`, neither `Task` nor `TaskOutput` nor the definition write tool SHALL be offered, and `/api/v1/subagents/definitions` SHALL not exist. When the module is active but the request's tenant is not granted it, none of these tools SHALL be offered to that tenant's requests.

#### Scenario: Foreground run returns its answer

- **WHEN** the model calls `Task` with a loaded `subagent_type` and no `run_in_background`
- **THEN** the tool result contains the subagent's answer and the run id
- **AND** the run's record is `done`

#### Scenario: Background run returns at once

- **WHEN** the model calls `Task` with `run_in_background: true`
- **THEN** the tool result contains a run id and returns before the subagent finishes
- **AND** `TaskOutput` with that id and `block: true` later returns the result

#### Scenario: Unknown subagent

- **WHEN** the model calls `Task` with a `subagent_type` that is not loaded
- **THEN** the tool result is an error naming the requested type and pointing to `skill_search`
- **AND** no run record is created

#### Scenario: The Task description does not grow with the definitions

- **WHEN** search is turned on and a tenant has 100 loaded definitions
- **THEN** the `Task` tool description sent to the model names none of them
- **AND** a `skill_search` with type `subagent` finds a definition by its description

#### Scenario: Search turned off lists every subagent

- **WHEN** `app.skills.search.enabled` is false and the caller's tenant has the loaded definitions `researcher` and `summariser`
- **THEN** no `skill_search` tool is offered
- **AND** the `Task` tool description lists `researcher` and `summariser` with their descriptions, in name order
- **AND** no definition of another tenant is listed

#### Scenario: The subagents module is not active

- **WHEN** the agent starts with `ASCEND_MODULES` holding `skills` and not `subagents`
- **THEN** no chat request offers `Task` or `TaskOutput`
- **AND** `GET /api/v1/subagents/definitions` answers 404
- **AND** `GET /api/v1/runs` answers 200

#### Scenario: No definitions behaves like today

- **WHEN** the definitions folder is empty and a user sends a prompt that needs no subagent
- **THEN** `POST /api/v1/ai/prompt` answers with the same response shape as before this change

### Requirement: Subagents can start subagents up to a configured depth

The main chat SHALL be depth 0, and a run SHALL have the depth of its caller plus one. The maximum depth SHALL be set by configuration (default 3). A run below the maximum depth SHALL be offered `Task` and `TaskOutput` when its definition allows them. A run at the maximum depth SHALL NOT be offered `Task`. A `Task` call that would create a run deeper than the maximum SHALL return a tool error and SHALL NOT create a run, whatever tools the caller holds.

#### Scenario: Nesting stops at the configured depth

- **WHEN** the maximum depth is 3 and a depth 3 run's definition lists `Task`
- **THEN** the depth 3 run is not offered `Task`

#### Scenario: Depth is configurable

- **WHEN** the maximum depth is set to 1
- **THEN** subagents started by the main chat are not offered `Task`

### Requirement: A subagent never has more tools than its parent

A run's tools SHALL be computed when it starts: the tools its definition names (or, when the definition has no `tools` key, the tools of its caller), minus the tools in `disallowedTools`, kept only when the caller also has them, kept only when the tenant's tool policy allows them, minus `Task` at the maximum depth, minus the tools never offered to a run: the definition write tool, the personality proposal and user facts tools of the agent soul capability, and the scheduling tools, always. This computation from definition and caller SHALL apply to runs of kind `subagent` only. A run of a kind other than `subagent` has no definition, so its starting tool set SHALL come from the change that owns its kind, and the tenant policy and the never-offered tools SHALL apply to it the same way. The one exception SHALL be a run of kind `self_review`, whose fixed tool set may keep the definition write tool (create only), the user facts tool and the personality proposal tool (proposal only). No other kind of run SHALL be offered any of those three tools. Tool names in a definition SHALL be the names the model sees, including the prefixed names of MCP tools. Before each model call of a run, the tools offered SHALL be the run's computed tools. `Task`, `TaskOutput` and the definition write tool SHALL be subject to the tenant's tool policy like any other tool, so a tenant whose policy does not allow them gets no subagents. A run SHALL act as the tenant and user of the chat turn that started its tree, on whichever thread it works. Tool names that the definition lists and that are not available at that moment SHALL be left out and logged at WARN, and the run SHALL still start. A tool call from the model that names a tool outside the run's computed tools SHALL NOT be executed and SHALL be answered with a tool error.

#### Scenario: Definition narrows the tools

- **WHEN** a definition lists `tools: weather_current` and its caller has `weather_current`, `weather_forecast` and `Task`
- **THEN** the run is offered only `weather_current`

#### Scenario: Definition cannot widen the tools

- **WHEN** a depth 2 run's definition lists a tool its depth 1 caller does not have
- **THEN** the depth 2 run is not offered that tool

#### Scenario: Tenant policy narrows every level

- **WHEN** a definition lists `web_search` and the tenant's tool policy does not allow `web_search`
- **THEN** the run is not offered `web_search`

#### Scenario: Tenant without the Task tool gets no subagents

- **WHEN** the tenant's tool policy does not allow `Task`
- **THEN** the main chat of that tenant is not offered `Task`

#### Scenario: Disallowed tools are removed

- **WHEN** a definition has no `tools` key and lists `disallowedTools: web_search`
- **THEN** the run has every tool of its caller except `web_search`

#### Scenario: A self review run keeps the definition write tool

- **WHEN** a run of kind `self_review` starts with a fixed tool set that holds the definition write tool, and a run of kind `subagent` starts from a definition that lists it
- **THEN** the `self_review` run is offered the definition write tool
- **AND** the `subagent` run is not

### Requirement: Shell and file tools run only in an isolated sandbox

A definition MAY list the sandbox tools of `add-agent-sandbox`, named `shell`, `file_read` and `file_write`. A sandbox tool SHALL be offered to a run only when `add-agent-sandbox` is applied and the tenant's tool policy allows it, and it SHALL pass every rule of the requirement above like any other tool. The main chat SHALL be offered the same three tools under the same two conditions, and each conversation SHALL use its own sandbox workspace, apart from the workspace of every run and of every other conversation. Before `add-agent-sandbox` is applied, a sandbox tool named by a definition SHALL be left out and logged at WARN, and the run SHALL still start. A sandbox tool call SHALL run only in the run's own throwaway sandbox container, separated from the agent and the host, and SHALL NEVER run in the agent's own process. No shell tool and no file system tool that runs inside the agent's process SHALL ever be offered to the main chat or to any run.

#### Scenario: No in-process shell or file tool exists

- **WHEN** the agent starts, with or without `add-agent-sandbox` applied
- **THEN** no tool that can be offered to the main chat or to a run executes a shell command or reads or writes files inside the agent's process

#### Scenario: Sandbox tool without the sandbox

- **WHEN** `add-agent-sandbox` is not applied and a definition lists `shell`
- **THEN** the run starts without `shell`
- **AND** one WARN line names `shell`

#### Scenario: The main chat uses the sandbox of its conversation

- **WHEN** `add-agent-sandbox` is applied, the tenant's tool policy allows `shell`, and the model of the main chat calls `shell` in conversation A and later in conversation B
- **THEN** the two calls run in two different sandbox workspaces, one for each conversation
- **AND** neither call runs in the agent's process

#### Scenario: Sandbox tool needs the tenant policy

- **WHEN** `add-agent-sandbox` is applied, a definition lists `shell` and the tenant's tool policy does not allow `shell`
- **THEN** the run is not offered `shell`

### Requirement: The model of a run is chosen in a fixed order and checked against an allowlist

The model of a run SHALL be, in this order: the `model` of the `Task` call, else the `model` of the definition, else the provider and model of the caller. A model SHALL be written as `<provider>:<model>`, as a configured alias (`opus`, `sonnet` or `haiku`), or as `inherit`. Each of the three aliases SHALL resolve to the latest model of its family as set in configuration, so moving an alias to a newer model needs no code change. The resolved provider SHALL be an enabled provider and the resolved provider and model SHALL be on the configured allowlist. A `Task` call whose resolved model is not allowed SHALL return a tool error naming the model and SHALL NOT create a run. The run record SHALL store the provider and model actually used.

#### Scenario: Per-call override wins

- **WHEN** a definition says `model: haiku` and the `Task` call says `model: openai:gpt-4o-mini`, and both are allowed
- **THEN** the run uses `openai` with `gpt-4o-mini`

#### Scenario: Alias follows the configuration

- **WHEN** the configuration maps `opus` to `anthropic:<model id A>`, a definition says `model: opus`, and the configuration is later changed to map `opus` to `anthropic:<model id B>`
- **THEN** runs started before the change use model id A and runs started after the change use model id B

#### Scenario: Model not on the allowlist

- **WHEN** a `Task` call asks for a model that is not on the allowlist
- **THEN** the tool result is an error naming the model and no run is created

### Requirement: The number of runs at once is limited

A run SHALL hold a worker slot while it works, and the number of slots SHALL be set by configuration (default 4). A foreground run started by another run SHALL work in its caller's slot, because the caller waits for it. A foreground run started by the main chat SHALL take a free slot or be refused at once with a tool error. A background run SHALL take a free slot, or wait in state `waiting` in the order it arrived, or be refused when the configured number of waiting runs (default 16) is reached. A refused call SHALL NOT create a run record. The slots SHALL be one slot pool with a limit per run kind, and the running and waiting limits SHALL hold across every agent instance, with waiting runs started in the order they arrived in the whole cluster.

#### Scenario: Background runs wait for a slot

- **WHEN** 4 slots are busy and the model starts a background run
- **THEN** the run's state is `waiting`
- **AND** it becomes `running` when a slot frees

#### Scenario: The limit holds across agent instances

- **WHEN** two agent instances share one database, 4 runs are `running` on the first instance and the model starts a background run on the second
- **THEN** the new run is `waiting`
- **AND** it becomes `running` on the second instance when a run of the first instance ends

#### Scenario: Full queue refuses

- **WHEN** 4 slots are busy and 16 runs are waiting, and the model starts another background run
- **THEN** the tool result is an error stating the limit and no run is created

### Requirement: Each run has a cost, token and time budget that covers its descendants

Each run SHALL have a cost limit in US dollars (default 1.00), a token limit (default 200000 input plus output tokens) and a time limit (default 10 minutes), set by configuration. The one exception SHALL be a run of kind `self_review`, which has no cost limit: its cost SHALL still be counted, recorded on the run and shown in the run view, and its token and time limits SHALL apply as for every run. A run's cost and tokens SHALL include those of all its descendants. A child's limits SHALL be the configured limits or what its parent has left, whichever is smaller. The time limit SHALL count from the moment the run starts working, not from when it was queued. Before each model call, the agent SHALL stop the run when its cost or tokens have reached a limit. Each model call SHALL ask for no more output tokens than the run has left. When the time limit passes, the agent SHALL stop the run at once. A stopped run SHALL end in state `failed` with reason `COST_LIMIT`, `TOKEN_LIMIT` or `TIME_LIMIT`, and its caller SHALL receive that reason as a tool error.

#### Scenario: Cost limit stops a run

- **WHEN** a run's cost reaches its cost limit after a model call
- **THEN** no further model call is made for that run
- **AND** the run ends `failed` with reason `COST_LIMIT`

#### Scenario: A self review run has no cost limit

- **WHEN** a run of kind `self_review` has cost more than the configured per-run cost limit
- **THEN** the run is not stopped for cost
- **AND** its cost so far is recorded on the run

#### Scenario: Child cannot outspend its parent

- **WHEN** a parent with 0.20 dollars left starts a child while the configured per-run limit is 1.00
- **THEN** the child's cost limit is 0.20

#### Scenario: Time limit stops a run

- **WHEN** a run is still working when its time limit passes
- **THEN** the run ends `failed` with reason `TIME_LIMIT` within 5 seconds of the limit

#### Scenario: Waiting time is not charged

- **WHEN** a background run waits 3 minutes for a slot and then works for 8 minutes with a 10 minute limit
- **THEN** the run is not stopped for time

### Requirement: Cost is computed from the token usage of every model call

After each model call of a run, the agent SHALL add the call's input and output tokens to the run and to every ancestor run, and SHALL add the call's cost computed as input tokens times the provider's input price plus output tokens times the provider's output price, from the same price table the token cost dashboard reads. A provider missing from the price table SHALL be priced at the highest input and output price in the table and SHALL be logged at WARN at startup. A model call whose response carries no usage SHALL be counted with the input and output token counts estimated from the text length and SHALL be marked as estimated on the run. Subagent model calls SHALL also be counted in the existing token usage metric.

Each model call of a run SHALL be published as one usage event through the usage event port of the deployment modules capability, with the run id, the parent run id and the request type of the run's kind: `subagent` for a run of kind `subagent`, `scheduled` for kind `scheduled` and `self-review` for kind `self_review`. A coding run's model calls SHALL be published as `coding-agent` events by the coding orchestrator when the run ends, and runs of kind `approval` and `integration`, which make no model call of their own, SHALL publish no model usage event. Every other usage event published while the run works (for example a metered web search or OCR job called by one of its tools) SHALL carry the same run id and parent run id. Before each model call of a run, the agent SHALL ask the quota gate port of the deployment modules capability for the run's tenant and user. The default of the usage event port SHALL record nothing and the default of the quota gate port SHALL allow every call, so with no other implementation registered the run's own counters and limits SHALL work alone. A call the quota gate refuses SHALL end the run `failed` with reason `QUOTA_EXCEEDED`, and the caller SHALL receive that reason as a tool error.

#### Scenario: Cost matches the price table

- **WHEN** a run makes one `anthropic` call using 1000 input tokens and 500 output tokens, and the price table lists 0.003 and 0.015 dollars per 1000 tokens
- **THEN** the run's cost so far is 0.0105 dollars

#### Scenario: Limits work with the default ports

- **WHEN** no implementation of the usage event port or the quota gate port is registered and a run's cost reaches its cost limit
- **THEN** the run ends `failed` with reason `COST_LIMIT`

#### Scenario: Usage events name the run

- **WHEN** a capturing usage event port is registered and a depth 2 run makes one model call
- **THEN** the port receives one event with request type `subagent`, that run's id and its parent's run id

#### Scenario: The request type follows the run's kind

- **WHEN** a capturing usage event port is registered and a run of kind `scheduled` and a run of kind `self_review` each make one model call
- **THEN** the port receives one event with request type `scheduled` carrying the scheduled run's id and one event with request type `self-review` carrying the review run's id
- **AND** neither event has request type `subagent`

#### Scenario: Exhausted quota stops a run

- **WHEN** a registered quota gate refuses the next model call of a working run
- **THEN** the run makes no further model call and ends `failed` with reason `QUOTA_EXCEEDED`

#### Scenario: Cost rolls up to the parent

- **WHEN** a child run costs 0.05 dollars
- **THEN** its parent's cost so far grows by 0.05 dollars

### Requirement: Definitions name skills that are preloaded into the run

A definition's `skills` SHALL name skills known to the agent's skill registry. When a run starts, the instructions of each named skill SHALL be added to the run's system instructions after the definition body. A named skill that is not known SHALL be left out and logged at WARN, and the run SHALL still start.

#### Scenario: Skill is preloaded

- **WHEN** a definition lists a skill that the skill registry knows
- **THEN** the run's system instructions contain that skill's instructions after the definition body
