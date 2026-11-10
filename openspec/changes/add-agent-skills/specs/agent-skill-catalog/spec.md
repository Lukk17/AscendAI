## Purpose

Lets ascend-agent offer reusable skills in the agentskills.io format to the model: it loads them from configured folders, lets the model search for the skills that fit the task instead of listing every skill in every request, serves a skill's body and files on request, and keeps the list current while the agent runs without ever blocking startup or disturbing a request already in progress.

## ADDED Requirements

### Requirement: Skills load at startup from an ordered list of configured folders

The agent SHALL read an ordered list of skill folders from configuration, each with a short identifier, a path and a writable flag. At startup it SHALL load every skill found in those folders. A skill SHALL be a direct child folder of a configured folder that contains a file named exactly `SKILL.md`. A child folder without `SKILL.md` and a plain file SHALL NOT be skills. A `SKILL.md` found deeper inside a skill folder SHALL NOT be loaded as a separate skill. The repository folder `.agents/skills` SHALL load with no changes to its files. The whole feature SHALL be the module `skills` of the deployment module catalog, active only when `skills` is in the module list the agent reads from `ASCEND_MODULES`. There SHALL be no separate configuration flag that turns the whole feature on or off. When the module is not active, no skill folder is read, no skill tool is offered to the model, and `/api/v1/skills` does not exist. When the module is active but the request's tenant is not granted it, no skill tool is offered to that tenant's requests.

#### Scenario: The repository skills load

- **WHEN** the agent starts with the repository folder `.agents/skills` configured as a read-only folder
- **THEN** every skill in that folder whose `SKILL.md` follows the rules in this capability is loaded
- **AND** the skill `mongodb-search-and-ai`, whose description is a multi-line YAML block, is loaded with its full description text
- **AND** the plain file `.openspec-target` in that folder is not reported as a skill or as a skipped skill

#### Scenario: A nested SKILL.md is not a separate skill

- **WHEN** a skill folder `pdf` contains `pdf/SKILL.md` and `pdf/references/SKILL.md`
- **THEN** only the skill `pdf` is loaded
- **AND** the nested file is reachable only as a file of the `pdf` skill

#### Scenario: The skills module is not active

- **WHEN** the agent starts with `ASCEND_MODULES` not holding `skills`
- **THEN** no skill folder is read
- **AND** no chat request offers a skill tool to the model
- **AND** `GET /api/v1/skills` answers 404

### Requirement: A skill is valid only when its SKILL.md follows the agentskills.io rules and the configured limits

A `SKILL.md` SHALL be valid only when all of these hold: it is valid UTF-8 with no NUL byte, its size is within the configured maximum, it starts with a YAML front matter block that a safe YAML parser accepts, the front matter has a `name` of 1 to 64 characters made of lowercase letters `a-z`, digits and single hyphens that does not start or end with a hyphen, the `name` equals the folder name, the front matter has a non-empty `description` within the configured maximum length (1024 characters by default), and, when present, `compatibility` is 1 to 500 characters and `metadata` maps strings to strings. The YAML parser SHALL refuse type tags that build objects and SHALL bound aliases and input size. Front matter keys outside the agentskills.io set SHALL be ignored and SHALL NOT reach the model.

#### Scenario: A name that does not match its folder

- **WHEN** the folder `code-review` holds a `SKILL.md` whose `name` is `reviewer` and no earlier version of `code-review` was loaded
- **THEN** the skill is not loaded
- **AND** the skip reason is `name_mismatch`

#### Scenario: A YAML type tag is refused

- **WHEN** a `SKILL.md` front matter contains a value tagged `!!javax.script.ScriptEngineManager` and no earlier version of that skill was loaded
- **THEN** no object of that type is created
- **AND** the skill is not loaded with skip reason `invalid_front_matter`

#### Scenario: Unknown front matter keys stay hidden

- **WHEN** a valid `SKILL.md` also has the keys `model` and `argument-hint`
- **THEN** the skill is loaded
- **AND** the text the model sees for this skill holds only its name and description

### Requirement: A malformed skill or folder is skipped and logged and never blocks startup

The agent SHALL skip every skill that is not valid and has no last good version, log one WARN line per skipped skill naming the folder identifier, the path and a reason from a closed set (`invalid_front_matter`, `name_mismatch`, `too_large`, `not_utf8`, `unreadable`, `outside_folder`, `duplicate_name`, `limit_reached`), and continue with the remaining skills. A configured folder that is missing, is not a directory or cannot be read SHALL be logged at WARN and skipped. Any other failure while loading SHALL leave the agent running with the skills loaded so far, or with none, and SHALL be logged at ERROR. The agent SHALL never fail to start because of skills.

#### Scenario: One broken skill among good ones

- **WHEN** a folder holds three skills and one of them has front matter that is not valid YAML at startup
- **THEN** the other two skills are loaded
- **AND** one WARN line names the broken skill's path and the reason `invalid_front_matter`
- **AND** the agent reports healthy on `/actuator/health`

#### Scenario: A configured folder does not exist

- **WHEN** a configured read-only folder path does not exist
- **THEN** the agent starts
- **AND** a WARN line names the folder identifier and its path
- **AND** skills from the other folders are loaded

### Requirement: A skill that loaded and then becomes invalid keeps its last good version

When a reload finds that a skill in the current list still has its `SKILL.md` but the file now fails validation for a file level reason (`invalid_front_matter`, `name_mismatch`, `too_large`, `not_utf8`, `unreadable`, `outside_folder`), the agent SHALL keep the skill's previous name, description and body in the new list, SHALL log one WARN line naming the folder identifier, the path and the reason, and SHALL report the skill as held at its last good version with that reason in the reload response and the skill list. The skill SHALL stay offered, searchable and loadable with its last good content until its file is valid again, when the new content replaces it, or until its `SKILL.md` or its folder is removed, when the skill is removed. An agent instance SHALL keep last good versions in memory. For a skill of a tenant skills folder, an instance that holds no last good version (it started after the broken edit, or restarted) SHALL take it from the newest commit touching the skill whose `SKILL.md` is valid, so every agent instance serves the same version. A tenant skill with no valid commit in its history, and a skill of a read-only folder that is invalid when the agent starts, SHALL have no last good version and SHALL be skipped.

#### Scenario: Broken edit keeps the last good version

- **WHEN** the loaded skill `demo` has its `SKILL.md` overwritten with content that has no `description` and a reload runs
- **THEN** a new chat request calling `Skill` with `demo` receives the previous body
- **AND** one WARN line names the path of `demo/SKILL.md` and the reason `invalid_front_matter`
- **AND** the reload response lists `demo` as held at its last good version with reason `invalid_front_matter`

#### Scenario: A fixed file replaces the last good version

- **WHEN** `demo` is held at its last good version and its `SKILL.md` is then written with valid new content
- **THEN** after the next reload a new chat request receives the new body
- **AND** `demo` is no longer reported as held at its last good version

#### Scenario: A restarted instance serves the same last good version

- **WHEN** the tenant skill `demo` is held at its last good version and an agent instance starts while its `SKILL.md` is still invalid
- **THEN** a chat request on that instance calling `Skill` with `demo` receives the body of the newest valid commit of `demo`

#### Scenario: A removed skill is not kept

- **WHEN** `demo` is held at its last good version and its folder is deleted
- **THEN** a chat request that starts after the next reload is not offered `demo`

### Requirement: Read-only folders come first and the folder listed first wins

The writable folder SHALL be the last entry of the configured folder list, and a configuration where it is not SHALL be refused at startup with an error naming the property. When two configured folders each hold a valid skill with the same name, the agent SHALL keep the skill from the folder listed earlier in configuration and skip the other with reason `duplicate_name`. The WARN line SHALL name both paths. A shipped skill therefore always wins over a tenant skill with the same name. The number of loaded skills SHALL be bounded by a configured maximum, and skills beyond it SHALL be skipped with reason `limit_reached`, taking folders in their configured order and skills inside a folder in name order.

#### Scenario: Same name in two read-only folders

- **WHEN** the first configured folder and the second configured folder both hold a valid skill named `code-reviewer`
- **THEN** the model is offered the skill from the first folder
- **AND** one WARN line names both paths and the reason `duplicate_name`

#### Scenario: Writable folder not last

- **WHEN** configuration lists the writable folder before a read-only folder
- **THEN** startup fails with a message naming the skill sources property

### Requirement: Each tenant is offered the global skills its policy allows plus its own skills

The skill list a chat request receives SHALL be the global skills from the read-only folders plus the skills of the request's tenant from its tenant skills folder `tenants/<tenantId>/skills/` under the writable root, with the tenant skills folder taking the writable root's place in the folder order. A global skill SHALL be offered only when the global skill policy port allows that skill name for the tenant, the `Skill`, `skill_read_file` and skill write tools SHALL be offered only when the tenant tool policy port allows them, and `skill_search` SHALL be offered only when `Skill` or the subagent `Task` tool is offered. The default of each port SHALL read a deny list from configuration, `app.tool-policy.denied-global-skills` and `app.tool-policy.denied-tools`, both empty by default, so with no other implementation registered and empty lists every global skill and every skill tool is offered, and a registered implementation SHALL replace a default with no change to the skill capability. A tenant's own skills SHALL be offered whenever `Skill` is allowed. A policy change SHALL reach the next chat request without a reload. Every lookup in a chat request, by name or by search, SHALL see only the skills of that request's list.

#### Scenario: Policy limits global skills

- **WHEN** the global skill policy port allows the global skill `api-design` only for tenant `acme`
- **THEN** a chat request of tenant `acme` is offered `api-design` and every skill in `acme`'s own folder
- **AND** it is not offered any other global skill, by name or through `skill_search`

#### Scenario: Default ports offer everything

- **WHEN** no implementation of either policy port is registered, both deny lists are empty and a chat request of tenant `default` runs
- **THEN** the request is offered every global skill, `Skill`, `skill_read_file` and the skill write tool

#### Scenario: The owner denies a tool and a skill in configuration

- **WHEN** no implementation of either policy port is registered, `app.tool-policy.denied-tools` lists `skill_write` and `app.tool-policy.denied-global-skills` lists `api-design`
- **THEN** no chat request is offered the skill write tool or `api-design`, by name or through `skill_search`

#### Scenario: One tenant's skill stays in that tenant

- **WHEN** tenant `acme` has its own skill `invoice-checks`
- **THEN** a chat request of tenant `globex` is not offered `invoice-checks`
- **AND** a `skill_search` in a `globex` request for "invoice checks" does not return `invoice-checks`

### Requirement: A symbolic link never leads the loader outside a configured folder

The agent SHALL resolve the real path of every skill folder and `SKILL.md` it reads and SHALL skip, with reason `outside_folder`, any whose real path is not inside the real path of its configured folder.

#### Scenario: A link pointing outside

- **WHEN** a skill folder entry is a symbolic link to `/etc`
- **THEN** nothing under `/etc` is read
- **AND** the entry is skipped with reason `outside_folder`

### Requirement: The model loads skills through one Skill tool that lists only the always-listed set

When at least one skill is in a chat request's list, the request SHALL offer the model one tool named `Skill`. When search is turned on, its description SHALL list by name and description only the skills named in the configured always-listed set that are in the request's list, in name order, and SHALL tell the model to find other skills with `skill_search`. When search is turned off, its description SHALL list every skill of the request's list instead. In both cases characters that could close or open a markup element SHALL be escaped, so the same listed skills always produce the same description bytes. Calling the tool with any skill name in the request's list, listed or not, SHALL return the skill's base location and its full body. Calling it with any other name SHALL return a message that the skill was not found and SHALL NOT raise an error to the chat request. When no skill is in the request's list, the `Skill` tool SHALL NOT be offered. When an MCP tool has the same name as a skill tool, the skill tool SHALL be kept, the MCP tool SHALL be left out of that request, and a WARN line SHALL name the dropped tool.

#### Scenario: The model loads a skill body

- **WHEN** the model calls `Skill` with `command` set to `springboot-patterns`
- **THEN** the tool result holds the full body of `springboot-patterns/SKILL.md`
- **AND** the chat response metadata lists `Skill` among the tools used

#### Scenario: A skill that is not listed still loads by name

- **WHEN** the always-listed set is empty and the model calls `Skill` with `command` set to `api-design`, a skill in the request's list
- **THEN** the tool result holds the full body of `api-design/SKILL.md`

#### Scenario: The description does not grow with the skill list

- **WHEN** search is turned on, the always-listed set is empty, and a new skill is added and reloaded
- **THEN** the `Skill` and `skill_search` tool definitions of the next chat request are byte for byte the same as before the reload

#### Scenario: Unknown skill name

- **WHEN** the model calls `Skill` with `command` set to `does-not-exist`
- **THEN** the tool result says the skill was not found
- **AND** the chat request completes with HTTP 200

#### Scenario: A description that tries to close the skill list

- **WHEN** an always-listed skill's description contains `</available_skills>`
- **THEN** the `Skill` tool description holds that text escaped
- **AND** the list of available skills in the description still ends only once

#### Scenario: An always-listed name the tenant may not see

- **WHEN** the always-listed set names `api-design` and the policy of tenant `acme` does not allow `api-design`
- **THEN** the `Skill` description of an `acme` request does not list `api-design`

### Requirement: The model finds skills that fit the task with skill_search

When search is turned on and `Skill` is offered, or the `Task` tool of the subagent capabilities is offered, every chat request SHALL also offer a tool named `skill_search` that takes a query and a type, `skill` by default or `subagent`. The input schema SHALL hold both type values in every request, so the tool definition does not change with the tenant. With type `subagent` it SHALL search the subagent definitions the request may see in the same way as skills, and with a type whose tool is not offered in the request it SHALL answer that no capability of that type is available. With type `skill` it SHALL return at most the configured top N skills of the request's list whose match score is at or above the configured score threshold, best first, each with its name, its description as it is in the request's list, and its score. It SHALL never return a skill outside the request's list, and SHALL never return an entry of type `tool`, which is searched by the tool search of the MCP tool servers. Once that tool search exists, the `skill_search` description SHALL say that tools are found with it. It SHALL search the capability index with the request's embedding provider, and SHALL answer with a text match over the request's list when that provider is not indexed, its index is not ready, or the search fails. A skill of the request's list that the index does not hold yet SHALL be found by the text match. A search with no result SHALL say that no skill matches. A failure SHALL be returned to the model as a message and SHALL NOT fail the chat request.

#### Scenario: Search returns the fitting skill

- **WHEN** the model calls `skill_search` with the query "design a REST endpoint and pick status codes"
- **THEN** the result lists `api-design` among at most top N skills
- **AND** every listed score is at or above the configured threshold

#### Scenario: Embedding provider down

- **WHEN** the request's embedding provider cannot be reached and the model calls `skill_search` with the query "postgres index"
- **THEN** the result is produced by the text match and lists `postgres-patterns`
- **AND** the chat request completes with HTTP 200

#### Scenario: A just written skill is found

- **WHEN** a write of skill `invoice-checks` succeeds and a chat request starts before the index holds it
- **THEN** a `skill_search` for "invoice checks" in that request returns `invoice-checks`

#### Scenario: Nothing matches

- **WHEN** the model calls `skill_search` with a query no skill matches above the threshold and no word of which appears in any skill
- **THEN** the result says no skill matches

#### Scenario: Subagent search without the Task tool

- **WHEN** the `Task` tool is not offered in a chat request and the model calls `skill_search` with type `subagent`
- **THEN** the result says no subagent is available
- **AND** no search is made and the chat request completes with HTTP 200

### Requirement: The model can read a text file inside a loaded skill folder and nothing else

While at least one skill is loaded, every chat request SHALL also offer a tool that reads one file inside a loaded skill folder, given the skill name and a path relative to that folder. The tool SHALL refuse, with a message to the model rather than an error to the request, a path that is absolute, contains a `..` segment, resolves outside the skill folder after resolving links, names a directory, is larger than the configured maximum file size, or is not valid UTF-8 text. No file in a skill folder SHALL ever be executed.

#### Scenario: Reading a reference file

- **WHEN** the model asks for `references/REFERENCE.md` of a loaded skill
- **THEN** the tool result holds that file's text

#### Scenario: Escaping the skill folder

- **WHEN** the model asks for `../../application.yaml` of a loaded skill
- **THEN** the tool result says the path is refused
- **AND** no file outside the skill folder is read

### Requirement: The skill list follows changes to the folders while the agent runs

The agent SHALL watch every configured folder that exists and SHALL reload the skill list after a skill is added, changed or deleted, waiting a configured quiet period (500 milliseconds by default) so that a burst of file events causes one reload. It SHALL also rescan all folders on a configured interval, so a change is picked up on a file system that does not deliver change events. No setting SHALL turn the watcher off. The watcher, the rescan, the reload and the write path SHALL be one catalog shared with the subagent definitions, each type with its own validator. When several agent instances share one agent home root, a reload that one instance publishes because of a write, the reload endpoint or a file event SHALL reach every other instance through a shared notification, with the rescan as fallback, so every instance offers the new list without depending on its own folder watcher. `POST /api/v1/skills/reload` SHALL reload at once and answer with the new list version, the number of loaded skills per folder, every skipped skill with its path and reason, and every skill held at its last good version with its reason. A reload SHALL build a complete new list before replacing the old one, and a reload that fails SHALL keep the previous list and log at ERROR. A reload that finds the same skills with the same content SHALL keep the current list version. Every reload that publishes a new list SHALL hand it to the capability index.

#### Scenario: Reload with nothing changed

- **WHEN** `POST /api/v1/skills/reload` is called twice with no change to any folder in between
- **THEN** both responses report the same list version

#### Scenario: A skill is added while the agent runs

- **WHEN** a valid skill folder is copied into a watched folder
- **THEN** within the quiet period plus the rescan interval, a new chat request can load that skill by name and find it with `skill_search`

#### Scenario: A skill is deleted while the agent runs

- **WHEN** a loaded skill folder is removed
- **THEN** a chat request that starts after the next reload is not offered that skill, by name or through `skill_search`

#### Scenario: A write on one instance reaches another instance

- **WHEN** two agent instances share one agent home root and the owner writes skill `demo` through the first instance
- **THEN** within the quiet period plus a margin a chat request on the second instance can load `demo` with `Skill`, even when the second instance received no file event

#### Scenario: Reload endpoint

- **WHEN** the owner calls `POST /api/v1/skills/reload`
- **THEN** the response is HTTP 200 with the list version, loaded counts per folder, the skipped skills with reasons and the skills held at their last good version with reasons

### Requirement: A chat request keeps the skill list it started with

Each chat request SHALL take the current skill list once, before it builds the tools for the model, and SHALL use that same list for every model call and every tool call in that request, including a retry the request makes without prompt caching. Skill names, descriptions, bodies and search results SHALL come from that list. A reload during the request SHALL NOT change which skills that request is offered, finds or is served. Other files inside a skill folder are read from disk when the model asks for them, for skills in that request's list only.

#### Scenario: Reload in the middle of a request

- **WHEN** a chat request has taken skill list version 4 and a reload publishes version 5 that deletes skill `a` before the model calls `Skill` with `a`
- **THEN** the call returns the body of `a` as it was in version 4
- **AND** the next chat request is not offered `a`

### Requirement: Skill loading and use are visible in metrics and logs

The agent SHALL publish these metrics, each with low-cardinality tags only: a gauge of loaded skills tagged by folder identifier, a counter of skipped skills tagged by `reason`, a gauge of skills held at their last good version, a timer of reloads tagged by `trigger` (`startup`, `watcher`, `rescan`, `notify`, `endpoint`, `write`) and `outcome` (`ok`, `error`), a gauge of the current list version, a counter of `Skill` tool calls tagged by `skill` (bounded by the maximum skill count) and `outcome` (`found`, `not_found`), and a timer of `skill_search` calls tagged by `outcome` (`hit`, `no_match`, `text_match`, `error`). The startup banner SHALL print each configured folder with its path, whether it is writable and how many skills it loaded, the number of skipped skills, and the always-listed names. Every reload SHALL log one INFO line with trigger, list version, loaded count, skipped count, last good count and duration. Every search SHALL log one INFO line with the query length, the method, the result names and scores, never the query text. No log line SHALL contain a skill body.

#### Scenario: Startup banner

- **WHEN** the agent starts with two configured folders
- **THEN** the startup banner names both folders with their paths, writable flags and loaded counts

#### Scenario: Skipped skills are counted

- **WHEN** a reload skips one skill with reason `too_large`
- **THEN** the skipped-skills counter tagged `reason="too_large"` increases by 1

#### Scenario: Search log holds no query text

- **WHEN** the model calls `skill_search` with the query "my salary is 9000"
- **THEN** the search INFO line names the query length, the method and the results
- **AND** no log line contains `9000`

### Requirement: Skill behaviour is covered by end-to-end tests

The repository SHALL hold end-to-end tests for skills against the live stack in `apps/ascend-agent/e2e/`. Every behaviour that an HTTP status, a response body or persisted state can prove on the live stack, and that no unit or integration test already proves, SHALL be checked by a deterministic spec whose Bruno requests call no AI model. Writing a skill from chat and its `protected` and `shipped_name` refusals SHALL be checked by tests with a stub model, not by an end-to-end spec. No spec of skills SHALL need the scripted model or the fake MCP server of the shared e2e harness. Only the behaviour that needs a real model to judge, finding and loading the right skill, SHALL be checked by an AI-run spec. Pass criteria SHALL be HTTP status, response bodies and the skill history only, never log lines. Both specs SHALL be listed in the full-stack run scenarios and the ascend-agent service suite of `docs/E2E_RUN_SCENARIOS.md`, and the owner SHALL be asked which scenario to run before any run.

#### Scenario: Owner endpoints are checked without a model

- **WHEN** the deterministic skills spec runs against the live stack
- **THEN** every request of `docs/api/request/AscendAI/ascend-agent/testing/skills-api/` passes its status and body assertions
- **AND** no request of that folder names a provider or a model

#### Scenario: A broken hand edit keeps the last good version end to end

- **WHEN** the deterministic spec overwrites a written skill's `SKILL.md` inside the container with front matter that has no `description` and calls `POST /api/v1/skills/reload`
- **THEN** `GET /api/v1/skills` lists the skill as `last_good` and `GET /api/v1/skills/{name}` returns the earlier valid text

#### Scenario: The model finds and loads a written skill

- **WHEN** the AI-run spec writes a skill holding an invented rule and then asks a question only that rule answers
- **THEN** `metadata.toolsUsed` of the answer holds `skill_search` and `Skill`
- **AND** the answer holds the value the invented rule gives
