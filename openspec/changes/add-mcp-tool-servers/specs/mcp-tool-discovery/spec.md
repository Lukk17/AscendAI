## Purpose

Keeps the tool list of every request small when many MCP servers are connected, by letting the model search for the tools of servers marked for search and adding only the tools it found to the rest of the same request.

## ADDED Requirements

### Requirement: Tools of search servers are not listed until found

For a request whose tool list holds at least one tool of a server with `discovery: search`, the first model call SHALL receive the agent native tools, the tools of servers with `discovery: always`, and one tool search tool, and SHALL NOT receive any tool of a search server. When the model calls the tool search tool, the tools it returns SHALL be added to every later model call of the same request, and only those. A request whose tool list holds no tool of a search server SHALL be sent exactly as before this change, with no tool search tool.

#### Scenario: Notes tools appear only after a search

- **WHEN** the `notes` server has `discovery: search` and the user asks "what did I write about the boiler"
- **THEN** the first model call holds no `notes_` tool and holds the tool search tool
- **AND** after the model searches for "search my notes" the next model call holds `notes_search_notes` and the other returned tools
- **AND** the model's call of `notes_search_notes` runs

#### Scenario: Only always servers connected

- **WHEN** only our own servers with `discovery: always` are connected
- **THEN** the tool list sent to the model is the same as before this change and holds no tool search tool

### Requirement: The search returns only tools the request may use

The tool search SHALL return only tools that are in the request's own tool list, which is already filtered by the server exposure rules, the connected state, the tenant scope of run-time entries and the tenant's module grants, and by every tool filter a later change registers at the same point. A tool search SHALL return at most `app.mcp.discovery.max-results` (default 5) tools at or above `app.mcp.discovery.score-threshold`, best first. A tool returned by the search that is not in the request's own tool list SHALL never be added.

#### Scenario: Excluded tool never found

- **WHEN** the `notes` entry lists `delete_note` in `tools.exclude` and the model searches for "delete a note"
- **THEN** `notes_delete_note` is not in the result and is never added to the request

#### Scenario: Disconnected server not found

- **WHEN** the `notes` server is `FAILED` and the model searches for "search my notes"
- **THEN** no `notes_` tool is returned

### Requirement: MCP tools are entries of type tool in the capability index

Each exposed tool of a search server SHALL be one entry of type `tool` in the capability index of `add-agent-skills`, for every indexed embedding provider, with the prefixed name, the server title and the tool description as its embedded text. An entry SHALL be global for a server without a tenant, and keyed by the tenant for a tenant-scoped run-time entry. The entries SHALL follow the tool listing: a tool that appears is added, a tool whose description changes is written again, a tool that disappears, a server whose module is off, a removed run-time entry and a tool that becomes excluded are removed, and a server that goes `FAILED` keeps its entries, because the request's own tool list already hides it. A search of type `skill` or `subagent` SHALL never return a tool entry.

#### Scenario: Tool list change reaches the index

- **WHEN** the `notes` server reports a tools change that adds `export_notes`
- **THEN** the index holds an entry for `notes_export_notes` for every indexed provider after the next sync

#### Scenario: Types stay apart

- **WHEN** a skill named `notes-ops` and the tool `notes_search_notes` are both indexed and a skill search for "notes" runs
- **THEN** no hit is of type `tool`

### Requirement: Tool search works when the index is not ready

When the request's embedding provider is not indexed, not ready, or the vector search fails, the tool search SHALL answer with the text match of `add-agent-skills` over the request's searchable tools, and the answer SHALL say which method produced each hit. A tool whose entry is still pending SHALL be findable through the text match.

#### Scenario: Qdrant down

- **WHEN** Qdrant cannot be reached and the model searches for "export notes"
- **THEN** the search returns `notes_export_notes` through the text match and the request goes on

### Requirement: Tool search is measured

The agent SHALL publish the timer `mcp.tool.search` tagged `outcome` (`hit`, `no_match`, `text_match`, `error`) and the gauge `mcp.tool.deferred` with the number of search server tools that the last request did not send to the model. The search log line SHALL hold the query length and the returned names, never the query text.

#### Scenario: Deferred count visible

- **WHEN** a request holds 40 tools of search servers and the model finds 3
- **THEN** `mcp.tool.deferred` reads 37 after the request
