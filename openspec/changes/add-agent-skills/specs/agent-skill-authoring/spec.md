## Purpose

Gives ascend-agent one safe way to create, change, delete and restore the skills each tenant owns, used both by the agent's own tool and by the owner's REST endpoints, so every change is validated, recorded with where it came from, and can be undone from git history.

## ADDED Requirements

### Requirement: Exactly one configured folder is the writable root, holding one git repository per tenant

At most one configured skill folder SHALL be marked writable, and it SHALL be the last entry of the folder list. A configuration with more than one writable folder SHALL be refused at startup with an error naming them. The writable folder is the agent home root. It holds the tenant folder `tenants/<tenantId>/` of each tenant, and the tenant's skills SHALL live in the tenant skills folder `tenants/<tenantId>/skills/`, which SHALL be its own git repository. Neither the root nor a tenant folder SHALL be a git repository. The tenant folder SHALL be shared with the subagent definitions, which live in its `.claude/agents/` folder as a separate repository, and the skill write path SHALL never read or write that folder. Before a tenant id is used to build a path it SHALL match `[a-z0-9-]{1,64}`. At startup the agent SHALL create the writable root and the skills folder of tenant `default` if they are missing, and SHALL initialise a git repository in a tenant skills folder that has none, committing any files already present with origin `external`. A tenant skills folder SHALL be created the same way the first time its tenant writes. When no folder is writable, or a tenant skills folder or its repository cannot be created or written, the agent SHALL still start and load skills, every write for that tenant SHALL be refused with HTTP 503 on REST and a refusal message to the model on the tool, and one ERROR line SHALL name the folder and the cause.

#### Scenario: First start with an empty writable root

- **WHEN** the agent starts and the configured writable root does not exist
- **THEN** the folder `<writable root>/tenants/default/skills` exists afterwards and holds a git repository
- **AND** neither `<writable root>` nor `<writable root>/tenants/default` holds a git repository
- **AND** that repository has one initial commit

#### Scenario: Writable folder cannot be written

- **WHEN** the writable root is on a read-only mount
- **THEN** the agent starts and loads skills from every readable folder
- **AND** `PUT /api/v1/skills/demo` answers HTTP 503

#### Scenario: Two writable folders

- **WHEN** configuration marks two folders writable
- **THEN** startup fails with a message naming both folder identifiers

### Requirement: Every change to a tenant skills folder goes through one validated write path

Creating, replacing, deleting and reverting a skill SHALL all go through one write path, whoever asks for it, and SHALL act only on the skills folder of the caller's tenant. Before touching the disk the write path SHALL check the skill name against the agentskills.io name rules, refuse Windows device names (`con`, `prn`, `aux`, `nul`, `com1` to `com9`, `lpt1` to `lpt9`), check that the `name` in the front matter equals the requested name, and apply every rule a skill must pass to be loaded, including the configured size limit. A refused write SHALL leave the tenant skills folder and its git repository unchanged and SHALL report a reason from a closed set (`invalid_name`, `invalid_front_matter`, `name_mismatch`, `too_large`, `not_utf8`, `shipped_name`, `protected`, `not_found`, `conflict`). An accepted write SHALL replace `SKILL.md` atomically so no reader ever sees a partly written file, SHALL keep any other files in the skill folder, SHALL be committed to git, and SHALL trigger a reload before it reports success. An accepted write SHALL go live at once, with no approval step, whoever made it. The write SHALL NOT wait for the capability index. Writes for one tenant SHALL run one at a time, also when several agent instances share one agent home root, and two instances SHALL never commit in one repository at once.

#### Scenario: Invalid content is refused before anything is written

- **WHEN** a write for skill `demo` carries a `SKILL.md` with no `description`
- **THEN** the write is refused with reason `invalid_front_matter`
- **AND** the folder `demo` does not exist
- **AND** git has no new commit

#### Scenario: Accepted write is live before success is reported

- **WHEN** a valid write for a new skill `demo` succeeds
- **THEN** git has one new commit touching `demo/SKILL.md`
- **AND** a chat request that starts after the success response can load `demo` with `Skill` and find it with `skill_search`

### Requirement: No write may use the name of a shipped skill

The write path SHALL refuse to create, update or revert a skill whose name is the name of a direct child folder holding a `SKILL.md` in any read-only folder, whether that shipped skill is valid or not and whether or not the caller's tenant policy offers it. The refusal SHALL use reason `shipped_name` and a message that names the read-only folder holding the name and says to choose another name. The rule SHALL apply to the agent and to the owner alike, and the folder order SHALL NOT change it.

#### Scenario: Agent tries to write a shipped name

- **WHEN** the repository folder holds `code-reviewer` and the model calls the skill write tool for `code-reviewer`
- **THEN** the tool result says the name belongs to a shipped skill in folder `repo` and to choose another name
- **AND** nothing is written and git has no new commit

#### Scenario: Owner tries to write a shipped name

- **WHEN** the owner sends `PUT /api/v1/skills/springboot-patterns` with valid content and `springboot-patterns` is a shipped skill
- **THEN** the response is 409 with reason `shipped_name` and a message naming folder `repo`
- **AND** the body is `application/problem+json` with `status` 409, `code` `shipped_name`, `type` `https://ascend.ai/errors/shipped-name` and a `detail` naming folder `repo`
- **AND** nothing is written

#### Scenario: Shipped name hidden by policy is still refused

- **WHEN** the policy of tenant `acme` does not offer the global skill `api-design` and an `acme` owner sends `PUT /api/v1/skills/api-design`
- **THEN** the response is 409 with reason `shipped_name`

### Requirement: Path traversal through a skill name is impossible

The write path SHALL build a file path only from a tenant id and a skill name that already passed their rules, SHALL check that the resolved real path is a direct child of the real path of the caller's tenant skills folder, and SHALL refuse a write whose skill folder or `SKILL.md` is a symbolic link. No write SHALL create, change or delete a file outside the caller's tenant skills folder.

#### Scenario: Traversal in the name

- **WHEN** a write asks for the skill name `../../etc/passwd`
- **THEN** the write is refused with reason `invalid_name`
- **AND** no file is created or changed anywhere

#### Scenario: Device name on Windows

- **WHEN** a write asks for the skill name `con`
- **THEN** the write is refused with reason `invalid_name`

### Requirement: Every commit records where the change came from

Every commit in the writable repository SHALL carry the configured git author and a message whose trailer lines record `Skill-Name`, `Skill-Operation` (`create`, `update`, `delete`, `revert`) and `Skill-Origin`, where origin is one of `agent`, `owner`, `external`, or `guard` for a revert made by the self-improvement guard. No tool SHALL ever write origin `guard`. A commit with origin `agent` SHALL also record `Skill-Request-Id` with the id of the chat request and `Skill-Tools-Seen` with the tool names the model called earlier in the same chat request. The write path SHALL also write the trailers `Skill-Reason`, `Skill-Patch`, `Skill-Self-Change-Id` and `Self-Provenance` when its caller gives them, each as one line, so a trailer value can never add a trailer of its own. No commit SHALL contain a user id, because git history is not edited when a user asks for erasure. The INFO log line of each agent write SHALL name the request id together with the user id, so the request can be traced to its user. On every reload the agent SHALL commit any change in a tenant skills folder that did not come through the write path, with origin `external`, so that edits made by hand can also be undone.

#### Scenario: Agent write is recorded with its context

- **WHEN** in one chat request for user `user1` the model calls `web_search` and then the skill write tool for `demo`
- **THEN** the new commit has `Skill-Origin: agent`, a `Skill-Request-Id` equal to that request's id and `Skill-Tools-Seen: web_search`
- **AND** the commit text does not contain `user1`
- **AND** the INFO log line of the write names both the request id and `user1`

#### Scenario: Edit made by hand

- **WHEN** someone edits `tenants/default/skills/demo/SKILL.md` in the writable root with a text editor
- **THEN** after the next reload git has a commit for that change with `Skill-Origin: external`

#### Scenario: Invalid edit made by hand

- **WHEN** someone edits the loaded skill `tenants/default/skills/demo/SKILL.md` by hand so that it has no `description`
- **THEN** after the next reload git has a commit for that change with `Skill-Origin: external`
- **AND** `demo` stays offered with its last good version and a WARN line names the file and the reason

### Requirement: The agent can create skills and update only the skills it wrote

Every chat request whose tenant skills folder is available and for which the tenant tool policy port allows the skill write tool SHALL offer the model a skill write tool that takes a skill name, the full `SKILL.md` text and an optional reason of at most the configured maximum length (300 characters by default), which is recorded in the `Skill-Reason` trailer. The tool SHALL create the skill when the name is new and update it when the newest commit touching that skill has origin `agent` or `guard`. It SHALL refuse with reason `protected` when the newest commit touching that skill has origin `owner` or `external`, and with reason `shipped_name` when a read-only folder holds a skill with that name. A skill the agent writes SHALL go live at once without an approval step, except that once the self-improvement capability exists, a chat write made in a chat request whose request provenance is not `clean` (it carried retrieved documents, an attachment, a peer bot turn or an outside tool result) SHALL wait for one approval by the owner, as an approval request of kind `self_change`, unless the owner changed that capability's setting for such writes. The approved content SHALL then go through the write path with a stale check. The agent SHALL NOT be offered any tool that deletes or reverts a skill. A refused or failed write SHALL be returned to the model as a message and SHALL NOT fail the chat request. When the content passed to the tool appears in full in the user's own message of the same chat turn (after line endings are normalised and outer blank lines are trimmed), the owner pasted it, and the write SHALL be recorded with origin `owner` and the chat request id. Otherwise it SHALL be an agent write. When the tenant tool policy does not allow the skill write tool, for example when `app.tool-policy.denied-tools` lists it, the tool SHALL NOT be offered, and no other setting SHALL turn it off.

#### Scenario: Agent creates a new skill

- **WHEN** the model calls the skill write tool with name `invoice-checks` and valid content
- **THEN** the tool result names the new commit
- **AND** the skill `invoice-checks` exists in the skills folder of the request's tenant

#### Scenario: Agent tries to change an owner skill

- **WHEN** the owner created `release-notes` through REST and the model calls the skill write tool for `release-notes`
- **THEN** the tool result says the skill is protected
- **AND** `release-notes/SKILL.md` is unchanged and git has no new commit

#### Scenario: Agent updates a skill after a guard revert

- **WHEN** the newest commit touching `invoice-checks` has origin `guard` and the model calls the skill write tool for `invoice-checks` with valid content and the reason "fix the total check"
- **THEN** the skill is updated with a commit of origin `agent`
- **AND** that commit records `Skill-Reason: fix the total check`

#### Scenario: Chat write after outside content waits for the owner

- **WHEN** the self-improvement capability exists with its default setting, and the model calls a web search tool and then the skill write tool for a new skill `invoice-checks` in the same chat request
- **THEN** no skill folder is written and git has no new commit
- **AND** one approval request of kind `self_change` waits for the owner, and the tool result tells the model that the change waits for the owner's approval

#### Scenario: Owner pastes a skill in chat

- **WHEN** the owner pastes a `SKILL.md` in chat and asks the agent to save it, and the model calls the skill write tool with it
- **THEN** the write goes through the same validation as any other write
- **AND** the commit has `Skill-Origin: owner` and `Skill-Request-Id` set to that chat request's id

#### Scenario: Edited paste is an agent write

- **WHEN** the owner pastes a `SKILL.md` in chat and the model calls the skill write tool with content that differs from it
- **THEN** the write is an agent write with `Skill-Origin: agent` and every agent rule applies

#### Scenario: The deny list turns the write tool off

- **WHEN** `app.tool-policy.denied-tools` lists `skill_write`
- **THEN** no chat request is offered the skill write tool

### Requirement: The owner manages skills through REST endpoints

The agent SHALL expose these endpoints, all acting on the caller's tenant only, and all answering every error with the RFC 7807 problem detail that `upgrade-spring-boot-4` defines for every agent error: content type `application/problem+json` with the fields `type` (`https://ascend.ai/errors/` followed by the code with every `_` replaced by `-`), `title`, `status`, `detail`, `instance` and a top-level `code`, plus, on a validation failure only, the extension field `errors` that `upgrade-spring-boot-4` defines, with one object holding `field` and `message` for every failed rule:

- `GET /api/v1/skills` lists every skill offered to the caller's tenant with name, description, folder identifier, whether it is writable, and for writable skills the newest commit id and origin, plus the current list version.
- `GET /api/v1/skills/{name}` returns one loaded skill with its full `SKILL.md` text, or 404.
- `PUT /api/v1/skills/{name}` takes the `SKILL.md` text as `text/markdown`, writes it with origin `owner`, answers 201 when the skill was created and 200 when it was replaced, and returns the commit id. When the request has an `If-Match` header holding a commit id that is not the newest commit touching the skill, it answers 412 and writes nothing.
- `DELETE /api/v1/skills/{name}` removes the whole skill folder from the caller's tenant skills folder with origin `owner` and answers 204, answers 404 when the tenant has no such skill, and 409 when the skill exists only in a read-only folder.
- `GET /api/v1/skills/{name}/history` lists the commits touching the skill, newest first, with id, time, operation and origin, even after the skill was deleted.
- `POST /api/v1/skills/{name}/revert` takes a commit id and restores the skill to its state at that commit as a new commit with operation `revert` and origin `owner`. Restoring to a commit where the skill did not exist deletes it. The restored content SHALL pass validation, or the revert is refused with 400.

Validation refusals (`invalid_name`, `invalid_front_matter`, `name_mismatch`, `not_utf8`, and a revert whose content fails validation) SHALL answer 400 with `code` `validation` and the `errors` field, sorted by `field`, whose every `message` starts with the specific reason. The specific reason SHALL appear only inside the `errors` messages and in the text returned to the model, and SHALL never be the `code` of a body. A body larger than the configured maximum SHALL answer 413 with `code` `content_too_large`, a stale `If-Match` SHALL answer 412 with `code` `conflict`, `shipped_name` SHALL answer 409 with a message naming the read-only folder that holds the name, a missing skill SHALL answer 404 with `code` `not_found`, a caller without a required role SHALL answer 403 with `code` `forbidden`, and an unavailable tenant skills folder SHALL answer 503 with `code` `unavailable`. An owner write SHALL be accepted for a skill whose newest commit has any origin. Every endpoint under `/api/v1/skills` SHALL require an authenticated caller, and `PUT` and `DELETE` on `/api/v1/skills/{name}`, `POST /api/v1/skills/{name}/revert` and `POST /api/v1/skills/reload` SHALL require the `ADMIN` role, as this change's own rows in the authorization matrix of `add-keycloak-login`.

#### Scenario: Owner write endpoints need the ADMIN role

- **WHEN** an authenticated caller without the `ADMIN` role calls `PUT /api/v1/skills/demo`, `DELETE /api/v1/skills/demo`, `POST /api/v1/skills/demo/revert` or `POST /api/v1/skills/reload`
- **THEN** each response is 403 with `code` `forbidden` and nothing is written
- **AND** the same caller gets 200 on `GET /api/v1/skills`

#### Scenario: An owner with the ADMIN role can write

- **WHEN** a caller with a token holding the `ADMIN` role sends `PUT /api/v1/skills/demo` with valid content
- **THEN** the response is 201

#### Scenario: Owner creates and then replaces a skill

- **WHEN** the owner sends `PUT /api/v1/skills/demo` with valid content, then sends it again with changed content
- **THEN** the first response is 201 and the second is 200
- **AND** `GET /api/v1/skills/demo/history` lists two commits with origin `owner`

#### Scenario: Undo an agent change

- **WHEN** the model updated `invoice-checks` and the owner calls `POST /api/v1/skills/invoice-checks/revert` with the commit id before that update
- **THEN** `invoice-checks/SKILL.md` holds the earlier content
- **AND** history shows a new `revert` commit and still shows the agent's commit

#### Scenario: Invalid content answers the validation body

- **WHEN** the owner sends `PUT /api/v1/skills/demo` with a `SKILL.md` whose front matter has no `description`
- **THEN** the response is 400 with `Content-Type: application/problem+json`, `code` `validation` and `type` `https://ascend.ai/errors/validation`
- **AND** `errors` holds one object with `field` `description` and a `message` that starts with `invalid_front_matter`
- **AND** nothing is written and git has no new commit

#### Scenario: Stale If-Match

- **WHEN** the owner sends `PUT /api/v1/skills/demo` with `If-Match` holding a commit id older than the newest commit touching `demo`
- **THEN** the response is 412
- **AND** git has no new commit

#### Scenario: Body too large

- **WHEN** the owner sends `PUT /api/v1/skills/demo` with a body one byte over the configured maximum
- **THEN** the response is 413 with `code` `content_too_large` and nothing is written

#### Scenario: Deleting a read-only skill

- **WHEN** the owner sends `DELETE /api/v1/skills/springboot-patterns` and that skill exists only in the read-only repository folder
- **THEN** the response is 409 and the repository folder is unchanged

### Requirement: Skills written by the agent or an owner belong to one tenant

A skill written through the write path SHALL belong to the tenant of the caller and SHALL be offered, listed, read, replaced, deleted, reverted and shown in history only for that tenant. Skills in the read-only folders SHALL be global. The tenant SHALL be the one that `TenantContext.currentTenantId()` of `add-keycloak-login` answers, which is `default` in a personal deployment. A skill operation without a resolved tenant SHALL fail and SHALL NOT fall back to tenant `default`.

#### Scenario: Another tenant's skill is invisible

- **WHEN** tenant `acme` has written skill `invoice-checks` and a caller of tenant `globex` sends `GET /api/v1/skills/invoice-checks`
- **THEN** the response is 404
- **AND** no chat request of tenant `globex` is offered `invoice-checks`

#### Scenario: Personal deployment

- **WHEN** the owner writes skill `demo` on a personal deployment
- **THEN** the skill is stored under `<writable root>/tenants/default/skills/demo/`

### Requirement: Skill writes are audited

Every accepted or refused create, update, delete and revert, from the agent or an owner, and every call of `POST /api/v1/skills/reload`, SHALL be published as one audit event through the audit event port of the deployment modules capability, with actor, tenant, action (`SKILL_CREATED`, `SKILL_UPDATED`, `SKILL_DELETED`, `SKILL_REVERTED`, `SKILL_RELOADED`), skill name, outcome, origin, commit id when one was made, and request id. No audit event SHALL contain a skill body. With no other implementation registered, the port's default SHALL write one structured log line per event.

#### Scenario: Agent write audited

- **WHEN** the model creates skill `invoice-checks` for a user of tenant `acme` and a capturing audit event port is registered
- **THEN** the port receives one `SKILL_CREATED` event for tenant `acme` with origin `agent`, outcome success, the commit id and the request id

#### Scenario: Refused owner write audited

- **WHEN** an owner's `PUT /api/v1/skills/demo` is refused as `invalid_front_matter`
- **THEN** the audit event port receives one `SKILL_UPDATED` or `SKILL_CREATED` event with a refused outcome and no body text

### Requirement: Limits, paths and switches come from configuration

The maximum `SKILL.md` size, the maximum description length, the maximum number of loaded skills, the maximum size of a skill file the read tool returns, the list of folders with their paths and writable flags, the watcher quiet period, the rescan interval, the search switch, the search top N, the search score threshold, the always-listed skill names, the embedding providers the capability index is built for, the maximum length of a write reason, and the git author name and email SHALL all be read from configuration under `app.skills`, with defaults in `application.yaml` and container paths in the `docker` profile. Each of them that has a default SHALL also be read from its environment variable with the same default in code, and the agent's compose service SHALL pass it as `${VAR:-default}`, except the container paths, which stay beside their mounts. The path of the writable folder SHALL default to the agent home root `app.agent-home`, the one setting that the subagent definitions use for their root too, so skills and subagent definitions always share one root. A limit that is zero or negative, a description limit above 1024, a top N below 1, a score threshold outside 0 to 1, an index provider that is not a configured embedding provider, or a writable folder that is not the last folder SHALL be refused at startup with an error naming the property.

#### Scenario: Limit changed by configuration

- **WHEN** the agent starts with the maximum `SKILL.md` size set to 1024 bytes
- **THEN** a write of a 2048-byte `SKILL.md` is refused with reason `too_large`

#### Scenario: Limit changed by an environment variable

- **WHEN** the agent starts with the environment variable `APP_SKILLS_LIMITS_MAXSKILLS` set to 7 and the configured folders hold 9 valid skills
- **THEN** 7 skills are loaded and 2 are skipped with reason `limit_reached`

### Requirement: Writes are visible in metrics and logs

The agent SHALL count every write attempt in a counter tagged `origin` (`agent`, `owner`, `guard`), `operation` (`create`, `update`, `delete`, `revert`) and `outcome` (`ok`, `refused`, `error`), and SHALL log one INFO line per accepted write naming the tenant, skill, operation, origin, commit id, and for agent writes the request id, the requesting user and the tools seen, and one WARN line per refused write naming the skill, origin and reason. No log line SHALL contain the skill body.

#### Scenario: Refused agent write is counted and logged

- **WHEN** the model's write of `release-notes` is refused as `protected`
- **THEN** the write counter tagged `origin="agent"`, `operation="update"`, `outcome="refused"` increases by 1
- **AND** one WARN line names `release-notes`, origin `agent` and reason `protected`
