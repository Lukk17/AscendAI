## Purpose

Lets the owner, and the agent itself, define focused helper agents as Claude Code style Markdown files that the agent loads at startup, keeps current while it runs, validates on every write, registers in the shared capability index so the main agent can find them, and records in a git history so any change can be undone.

## ADDED Requirements

### Requirement: Definitions are Claude Code style Markdown files with front matter

A subagent definition SHALL be one UTF-8 Markdown file whose name ends in `.md`, starting with a YAML front matter block between two `---` lines, followed by the body that becomes the subagent's system instructions. The front matter SHALL accept these keys: `name` (required), `description` (required), `tools`, `disallowedTools`, `model`, `skills`, `permissionMode` and `origin`. `tools`, `disallowedTools` and `skills` SHALL be accepted both as one comma separated line and as a YAML list. `name` SHALL match `^[a-z][a-z0-9-]{1,63}$`. The body SHALL NOT be empty. Any other front matter key SHALL be accepted, ignored and reported as a warning.

#### Scenario: Comma separated and list forms load the same way

- **WHEN** one definition declares `tools: weather_current, Task` and another declares `tools` as a YAML list with the items `weather_current` and `Task`
- **THEN** both definitions load
- **AND** both report the tool list `weather_current`, `Task`

#### Scenario: Missing name is rejected

- **WHEN** a definition has front matter without a `name` key
- **THEN** the definition is rejected with a message that names the missing key
- **AND** no subagent with an empty or guessed name becomes available

#### Scenario: Unknown key is a warning, not an error

- **WHEN** a definition carries `color: blue` in its front matter
- **THEN** the definition loads
- **AND** the load result lists a warning naming the key `color`

### Requirement: Unsupported permission modes are refused

A definition whose `permissionMode` is present with any value other than `default` SHALL be rejected with a message stating that tool permission is expressed only through `tools` and `disallowedTools`. The agent SHALL NOT load a definition while silently ignoring a permission statement in it.

#### Scenario: Plan mode is refused

- **WHEN** a definition declares `permissionMode: plan`
- **THEN** the definition is rejected
- **AND** the message names `permissionMode` and tells the author to use `tools` and `disallowedTools`

### Requirement: Definitions are kept per tenant in a git repository

Definitions SHALL belong to a tenant. Each tenant SHALL have its own definitions folder, `tenants/<tenantId>/.claude/agents/` under one root folder set by configuration, and that root SHALL be the agent home root of `add-agent-skills`, so the tenant folder `tenants/<tenantId>/` is shared with the tenant's skills in `tenants/<tenantId>/skills/`, which this capability SHALL never read or write, and a personal deployment SHALL use the tenant `default`. A chat turn, a run and every definition endpoint SHALL see only the definitions of the caller's tenant. The root SHALL NOT be the repository's own `.claude/agents/` folder that holds developer agents. Each tenant definitions folder SHALL be its own git repository, and neither the root nor a tenant folder `tenants/<tenantId>/` SHALL be one. At startup the agent SHALL create the root and the `default` tenant definitions folder if they are missing and SHALL make the `default` tenant definitions folder a git repository if it is not one, with an initial commit. The folder and repository of any other tenant SHALL be created on that tenant's first write. Every change the agent makes to a definitions folder SHALL be one git commit in that tenant's repository whose message names the definition, the action (`create`, `update`, `delete`, `revert`), the source (`rest`, `chat`, `agent`, `startup`), the origin (`owner`, `agent`, or `guard` for a revert made by the self-improvement guard, which no tool SHALL ever write), and the chat request and run that caused it when there is one. When the caller gives them, the commit SHALL also record a reason, a self-change id and a provenance, each as one line, so a value can never add a line of its own. A commit SHALL NOT hold a user id or a conversation id. Deleting a tenant's definitions folder SHALL remove that tenant's definitions and their whole history without changing any other tenant's repository. Shipped read-only definitions, if any are added later, SHALL stay global, outside every tenant repository, and SHALL never be written by the write path.

#### Scenario: Fresh volume is initialised

- **WHEN** the agent starts with an empty root folder
- **THEN** the folder `tenants/default/.claude/agents/` exists and is a git repository with one commit
- **AND** neither the root nor `tenants/default/` is a git repository
- **AND** the agent starts and offers no subagents

#### Scenario: A write is one commit

- **WHEN** a definition is created through any write source
- **THEN** the git log of that tenant's repository gains exactly one commit for that file
- **AND** the commit message names the definition, the action `create` and the source
- **AND** the commit holds no user id and no conversation id

#### Scenario: Removing a tenant folder removes its history only

- **WHEN** tenants A and B both have definitions and the folder of tenant A is deleted
- **THEN** no definition and no commit of tenant A remains
- **AND** the repository and history of tenant B are unchanged

#### Scenario: Tenants do not see each other's definitions

- **WHEN** tenant A has a definition `researcher` and a caller of tenant B lists definitions or calls `Task` with `subagent_type: researcher`
- **THEN** the list does not contain it and the `Task` call is refused as an unknown subagent

### Requirement: Definitions are loaded at startup and kept current while the agent runs

The agent SHALL load every definition file of every tenant definitions folder at startup. While it runs, it SHALL watch the tenant definitions folders and, within 5 seconds of a file being added, changed or deleted, SHALL offer the new set of subagents to every chat turn and run that starts after the reload. A run that already started SHALL keep the definition version it started with. On a file system that delivers no file events, a rescan SHALL pick the change up within the configured rescan interval. When several agent instances share one agent home root, a write or reload made through one instance SHALL reach every other instance through a shared notification within 5 seconds. The watcher and the rescan SHALL be the ones that serve skills too. A file that fails validation SHALL NOT replace the last valid version of the same definition, SHALL be reported with its error, and SHALL produce one WARN log line naming the file and the first validation message. An agent instance that holds no last valid version of a definition in memory (it started after the broken edit, or restarted) SHALL take it from the newest commit of the file whose content is valid, so every instance serves the same version. Two files declaring the same `name` SHALL both be reported as a conflict, and the last valid version of that name, if any, SHALL stay active.

#### Scenario: Added file becomes available without restart

- **WHEN** a valid definition file is copied into the folder while the agent runs
- **THEN** within 5 seconds the definition list reports it as loaded
- **AND** in the next chat turn a `Task` call naming it starts a run

#### Scenario: Deleted file disappears

- **WHEN** a loaded definition file is deleted from the folder
- **THEN** within 5 seconds the definition list no longer reports it
- **AND** a `Task` call naming it is refused with a message that the subagent does not exist

#### Scenario: A write on one instance reaches another instance

- **WHEN** two agent instances share one agent home root and the owner writes the definition `researcher` through the first instance
- **THEN** within 5 seconds the definition list of the second instance reports it as loaded, even when the second instance received no file event

#### Scenario: Broken edit keeps the last good version

- **WHEN** a loaded definition file is overwritten with content that has no `description`
- **THEN** the previous valid version stays active
- **AND** the definition list reports the file as invalid with the validation message
- **AND** one WARN log line names the file and the missing `description`

### Requirement: A reload endpoint is the backup for missed folder events

`POST /api/v1/subagents/definitions/reload` SHALL re-read the caller's tenant folder, apply the same validation and last-good rules as the watcher, and answer HTTP 200 with the number of definitions loaded, the files rejected with their messages, and the warnings. It SHALL require the `ADMIN` role outside the `dev` profile of `add-keycloak-login`.

#### Scenario: Reload picks up a file the watcher missed

- **WHEN** a definition file is placed in the folder in a way that produces no folder event, and the reload endpoint is called
- **THEN** the response is 200 and counts the new definition as loaded
- **AND** a `Task` call naming it in the next chat turn starts a run

### Requirement: Every write goes through one validated write path

Creating, replacing, deleting and reverting a definition SHALL go through one write path, whichever source started it: the REST API, a definition the owner pastes in chat, or a definition the agent writes itself. The write path SHALL validate the content with the same rules the loader uses, SHALL refuse the write when validation fails, SHALL write the file into the definitions folder under the file name `<name>.md` derived from the validated `name` only, SHALL write it so that a reader never sees a half written file, SHALL commit it to git, and SHALL answer only after the definition is loaded or the load failed. The write path SHALL refuse content larger than the configured maximum size (default 32 KiB), SHALL refuse a new definition when the configured maximum number of definitions (default 100) is already loaded, and SHALL refuse content that contains a token starting with a known provider API key prefix, because definitions are committed to git and returned by read endpoints. The write path SHALL refuse, from every source, a definition whose `tools` names a tool that the tenant's tool policy does not allow. Writes of one tenant SHALL run one at a time, also when several agent instances share one agent home root. The write path SHALL be the one write path that serves skills too, with the rules of each type.

#### Scenario: Content with an API key is refused

- **WHEN** a definition body contains a token starting with `sk-ant-`
- **THEN** the write is refused with a message that the content looks like it holds an API key
- **AND** the message does not repeat the token

#### Scenario: Invalid content never reaches the folder

- **WHEN** any source submits a definition that fails validation
- **THEN** the write is refused with every validation message
- **AND** the folder and its git history are unchanged

#### Scenario: Path in the name cannot escape the folder

- **WHEN** a definition with `name: ../../etc/passwd` is submitted
- **THEN** the write is refused because the name does not match the allowed pattern
- **AND** no file is written anywhere

#### Scenario: Write is visible when the call returns

- **WHEN** a valid definition is written through the REST API and the call returns success
- **THEN** the definition list already reports the new version as loaded

### Requirement: The owner manages definitions through REST

The agent SHALL expose:

- `GET /api/v1/subagents/definitions`: every definition with name, description, tools, disallowed tools, model, skills, origin, version, load state (`loaded`, `invalid`, `conflict`) and messages.
- `GET /api/v1/subagents/definitions/{name}`: the raw Markdown with an `ETag` of its version.
- `PUT /api/v1/subagents/definitions/{name}` with a `text/markdown` body: create or replace. The `name` in the body SHALL equal the path name, else HTTP 400. An `If-Match` header that does not match the current version SHALL give HTTP 412. Create answers 201, replace answers 200.
- `DELETE /api/v1/subagents/definitions/{name}`: delete, HTTP 204, or 404 when unknown.
- `GET /api/v1/subagents/definitions/{name}/history`: the commits that touched the file, newest first, with commit id, time, action, source and origin.
- `POST /api/v1/subagents/definitions/{name}/revert` with a commit id: write that commit's content back through the write path as a new commit. A commit that never touched the file SHALL give HTTP 404. A commit in which the file was deleted SHALL give HTTP 409.

Every endpoint SHALL act on the caller's tenant only. Every write endpoint and the reload endpoint SHALL require the `ADMIN` role of that tenant, through this change's own rows in the authorization matrix of `add-keycloak-login`. Every error SHALL be the RFC 7807 problem detail that `upgrade-spring-boot-4` defines for every agent error: content type `application/problem+json` with the fields `type` (`https://ascend.ai/errors/` followed by the code with every `_` replaced by `-`), `title`, `status`, `detail`, `instance` and a top-level `code`. Every validation refusal, including a body name that differs from the path name, content that is not UTF-8 and a revert whose content fails validation, SHALL answer HTTP 400 with `code` `validation` and every validation message in the extension field `errors` that `upgrade-spring-boot-4` defines, one object with `field` and `message` per message, sorted by `field`. The specific reason of each refusal SHALL appear only inside its `errors` message, never as the `code`, and no error code SHALL be added for it. A `PUT` or a revert whose definition names in `tools` a tool that the tenant's tool policy does not allow SHALL answer HTTP 403 with `code` `tool_not_allowed`, SHALL name the refused tools in `detail`, and SHALL write nothing. This is the one error code this change adds.

#### Scenario: Create, read and replace

- **WHEN** the owner sends `PUT /api/v1/subagents/definitions/researcher` with a valid body, then reads it, then sends a changed body with the `If-Match` value from the read
- **THEN** the first call answers 201, the read answers 200 with an `ETag`, and the replace answers 200

#### Scenario: Invalid definition answers the validation body

- **WHEN** the owner sends `PUT /api/v1/subagents/definitions/researcher` with front matter that has no `description` and declares `permissionMode: plan`
- **THEN** the call answers 400 with `code` `validation`
- **AND** `errors` holds one object for `description` and one for `permissionMode`, each with a `message` that names the broken rule
- **AND** the file is unchanged

#### Scenario: Stale replace is refused

- **WHEN** the owner sends a replace with an `If-Match` value from before another write
- **THEN** the call answers 412 with `code` `conflict` and the file is unchanged

#### Scenario: A tool the tenant policy does not allow is refused

- **WHEN** the tenant's tool policy does not allow `shell` and the owner sends `PUT /api/v1/subagents/definitions/researcher` with a valid body that declares `tools: shell, weather_current`
- **THEN** the response is 403 with `code` `tool_not_allowed` and `type` `https://ascend.ai/errors/tool-not-allowed`, and its `detail` names `shell`
- **AND** the file and its git history are unchanged

#### Scenario: Revert undoes a change

- **WHEN** the owner reverts `researcher` to the commit before its last update
- **THEN** the file content equals that commit's content
- **AND** the history shows a new commit with the action `revert`

#### Scenario: Non admin is refused

- **WHEN** a caller without the `ADMIN` role calls `PUT`, `DELETE`, the revert endpoint or the reload endpoint
- **THEN** the response is 403 with `code` `forbidden` and nothing is written

### Requirement: The owner can paste a definition in chat

The main chat SHALL offer a definition write tool that takes the content, an optional action (`upsert` or `delete`) and an optional reason of at most the configured maximum length (300 characters by default), which is recorded in the commit. A longer reason SHALL be refused as a message to the model with no commit. When the model calls it with content that appears in full in the user's own message of the same chat turn (after line endings are normalised), the write SHALL be recorded with source `chat` and origin `owner`. When the content does not appear in full in that message, the write SHALL be treated as written by the agent, with origin `agent` and every agent-written rule applied. This SHALL be the same paste rule that the skill write tool follows. The chat answer SHALL tell the user whether the definition was saved and list any validation messages.

#### Scenario: Pasted definition is saved as an owner definition

- **WHEN** the user pastes a valid definition in a chat prompt and asks the agent to add it
- **THEN** the definition is loaded with origin `owner`
- **AND** the git commit names the source `chat`

#### Scenario: Edited paste is treated as agent written

- **WHEN** the model calls the write tool with content that differs from what the user pasted
- **THEN** the definition is saved only if it passes the agent-written rules, and with origin `agent`

### Requirement: Agent-written definitions cannot widen the agent's own power

A definition with origin `agent` SHALL carry the `origin: agent` key, set by the agent and never taken from the submitted content. The write path SHALL refuse an agent-written definition that:

- has no `tools` key, because an agent-written definition SHALL name its tools,
- names a tool that the conversation writing it does not have at the time of the write, or that the tenant's tool policy does not allow,
- names the definition write tool,
- names a model that is not on the model allowlist,
- would replace or delete a definition whose origin is `owner`.

The agent MAY replace or delete a definition whose origin is `agent` or `guard`. In a run of kind `self_review`, which writes for a request it did not take part in, the tools of "the conversation writing it" SHALL be the tools that the reviewed request had, as recorded in the review's evidence.

An agent-written definition that passes these rules SHALL be live as soon as the write returns, with no approval step, and the owner SHALL be able to undo it through the history and revert endpoints. The one exception SHALL be a write made through the definition write tool in a chat request whose request provenance is not `clean` (it carried retrieved documents, an attachment, a peer bot turn or an outside tool result): once the self-improvement capability exists, such a write SHALL wait for one approval by the owner, as an approval request of kind `self_change`, unless the owner changed that capability's setting for such writes, and the approved content SHALL then go through this write path with a stale check. The definition write tool SHALL be turned off only through the tenant tool policy, for example by listing it in `app.tool-policy.denied-tools`, and no other setting SHALL turn agent writes off. The definition write tool SHALL be offered to the main chat and to a run of kind `self_review` whose fixed tool set holds it, and never to any other run. A submitted `origin` key from any source other than the agent's own stamp SHALL be replaced by the origin the write path decides.

#### Scenario: Agent cannot grant itself a tool it lacks

- **WHEN** the agent writes a definition naming a tool that is not in the current conversation's tool list
- **THEN** the write is refused with a message naming the tool

#### Scenario: Agent cannot overwrite an owner definition

- **WHEN** the agent writes a definition whose name belongs to an owner definition
- **THEN** the write is refused and the owner definition is unchanged

#### Scenario: Forged origin is ignored

- **WHEN** content submitted through the agent path contains `origin: owner`
- **THEN** the saved file carries `origin: agent`

#### Scenario: Agent may change a definition the guard reverted

- **WHEN** the newest version of `researcher` has origin `guard` and the agent writes a valid new version of it
- **THEN** the write is accepted and the definition has origin `agent`

#### Scenario: Chat write after outside content waits for the owner

- **WHEN** the self-improvement capability exists with its default setting, the model calls a web search tool and then the definition write tool in the same chat request
- **THEN** no definition file is written and an approval request of kind `self_change` waits for the owner
- **AND** the tool result tells the model that the change waits for the owner's approval

#### Scenario: Subagents have no write tool

- **WHEN** any run of kind `subagent` starts
- **THEN** its tool list does not contain the definition write tool

#### Scenario: Agent-written definition is live at once

- **WHEN** the agent writes a definition that passes every agent-written rule
- **THEN** the definition list reports it as loaded with origin `agent` when the write returns
- **AND** no approval step is needed before a `Task` call can start it

### Requirement: Definitions are registered in the shared capability index

Every loaded definition SHALL be an entry in the shared capability index that `add-agent-skills` keeps in the vector store, with the type `subagent`, its tenant, name and description, in the entry format of that change's `agent-capability-index` capability, so the main agent finds subagents through the `skill_search` tool with the type `subagent`. The definitions SHALL reach the index only through that capability's sync, with no second index component. After every reload of a tenant (startup, watcher, reload endpoint, write), the `subagent` entries of that tenant SHALL match the loaded definitions: a new or changed definition SHALL be added or updated, a definition that is no longer loaded SHALL be removed, and a definition that keeps its last good version SHALL keep the entry of that version. Entries of the type `skill` SHALL NOT be changed. An index update that fails SHALL be logged at WARN, SHALL NOT stop the definitions from loading, and SHALL leave the affected entries pending until the capability index retries them. A search by a caller of one tenant SHALL NOT return a subagent of another tenant.

#### Scenario: New definition can be found

- **WHEN** a valid definition `researcher` with the description "Researches companies and compares them" is loaded
- **THEN** a `skill_search` for "compare companies" with type `subagent` returns `researcher`

#### Scenario: Deleted definition leaves the index

- **WHEN** a loaded definition is deleted and the reload has run
- **THEN** `skill_search` with type `subagent` no longer returns it

#### Scenario: Index failure does not stop loading

- **WHEN** the vector store is not reachable during a reload
- **THEN** the definitions load as usual and a `Task` call naming a loaded definition starts a run
- **AND** one WARN line reports the failed index update
- **AND** after the vector store is back, the next retry of the capability index brings the index in step

### Requirement: Definition activity is measured and logged

The agent SHALL publish the number of loaded definitions by origin, the number of invalid files, a counter of reloads by trigger (`startup`, `watcher`, `rescan`, `notify`, `endpoint`, `write`) and outcome, and a counter of writes by source and outcome (`ok`, `rejected`). Capability index updates of definitions SHALL be measured by the capability index metrics of `add-agent-skills` with the type `subagent`, and this capability SHALL add no index metric of its own. Metric tags SHALL NOT include the definition name or any free text. Every write and every rejected file SHALL produce one log line naming the definition, the source, the origin and the outcome. The definition body SHALL NOT be logged at INFO level or above.

#### Scenario: Rejected write is counted

- **WHEN** a write through the REST source fails validation
- **THEN** the write counter with source `rest` and outcome `rejected` grows by one
- **AND** one WARN line names the definition and the first validation message

### Requirement: Definition changes are audited

Every accepted or refused create or update of a definition, from any write source, SHALL be published as one audit event through the audit event port of the deployment modules capability with the action `SUBAGENT_DEFINITION_WRITTEN`, every delete with `SUBAGENT_DEFINITION_DELETED`, every revert with `SUBAGENT_DEFINITION_REVERTED`, and every call of `POST /api/v1/subagents/definitions/reload` with `SUBAGENT_DEFINITION_RELOADED`. Each event SHALL carry the actor, the tenant, the outcome, the definition name, the origin, the commit id when one was made and the request id. No audit event SHALL contain a definition body. With no other implementation registered, the port's default SHALL write one structured log line per event.

#### Scenario: Agent write audited

- **WHEN** the model writes the definition `invoice-checker` for a user of tenant `acme` through `subagent_definition_write` and a capturing audit event port is registered
- **THEN** the port receives one `SUBAGENT_DEFINITION_WRITTEN` event for tenant `acme` with origin `agent`, outcome success, the commit id and the request id
- **AND** no field of the event holds the definition body

#### Scenario: Refused owner write audited

- **WHEN** an owner's `PUT` of a definition is refused by validation
- **THEN** the audit event port receives one `SUBAGENT_DEFINITION_WRITTEN` event with a refused outcome and no body text
