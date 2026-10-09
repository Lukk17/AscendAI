## MODIFIED Requirements

### Requirement: A subagent never has more tools than its parent

A run's tools SHALL be computed when it starts: the tools its definition names (or, when the definition has no `tools` key, the tools of its caller), minus the tools in `disallowedTools`, kept only when the caller also has them, kept only when the tenant's tool policy allows them, minus `Task` at the maximum depth, minus the tools never offered to a run: the definition write tool, the personality proposal and user facts tools of the agent soul capability, and the scheduling tools, always. This computation from definition and caller SHALL apply to runs of kind `subagent` only. A run of a kind other than `subagent` has no definition, so its starting tool set SHALL come from the change that owns its kind, and the tenant policy and the never-offered tools SHALL apply to it the same way. The one exception SHALL be a run of kind `self_review`, whose fixed tool set may keep the definition write tool (create only), the user facts tool and the personality proposal tool (proposal only). No other kind of run SHALL be offered any of those three tools. Tool names in a definition SHALL be the names the model sees, including the prefixed names of MCP tools, and a definition MAY name an MCP tool that the chat offers only after a tool search. Such a tool SHALL be offered to the run from its first model call. Before each model call of a run, the tools offered SHALL be the run's always offered tools, the tool search tool when the run has tools that are offered only after a search, and the tools found by the run's earlier searches. `Task`, `TaskOutput` and the definition write tool SHALL be subject to the tenant's tool policy like any other tool, so a tenant whose policy does not allow them gets no subagents. A run SHALL act as the tenant and user of the chat turn that started its tree, on whichever thread it works. Tool names that the definition lists and that are not available at that moment SHALL be left out and logged at WARN, and the run SHALL still start. A tool call from the model that names a tool outside the run's computed tools SHALL NOT be executed and SHALL be answered with a tool error.

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

#### Scenario: A definition names a tool found only by search

- **WHEN** the chat offers the MCP tool `notes_search` only after a tool search, and a definition lists `notes_search` and its caller has it
- **THEN** the run is offered `notes_search` from its first model call
