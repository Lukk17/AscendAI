## Purpose

Gives each tenant one personality file that defines how the agent must always behave, keeps it first and fully present in every prompt however full the context is, repeats a short fixed reminder at the end of every prompt, lets the owner change it safely with full git history, and lets the agent only propose changes that the owner approves.

## ADDED Requirements

### Requirement: Each tenant has one personality file with git history

Each tenant SHALL have exactly one personality file, `SOUL.md`, in the folder `<agent home>/tenants/<tenantId>/soul/`, where `<agent home>` is the agent home root `app.agent-home` shared with skills and subagent definitions (default `${user.home}/.ascend-agent` for `bootRun`, `/app/agent-home` in the `docker` profile). That folder SHALL be its own git repository, and neither the agent home root nor the tenant folder SHALL be a git repository. The agent SHALL NOT read or write the tenant's `skills/` or `.claude/agents/` folders for the personality file. Before a tenant id is used to build a path it SHALL match `[a-z0-9-]{1,64}`. At startup the agent SHALL create the folder `tenants/default/soul/` when it is missing, initialise a git repository in it, and seed `SOUL.md` from the shipped default with a commit of origin `seed`. The folder of any other tenant SHALL be created the same way on that tenant's first chat request or first personality request. An existing `SOUL.md` SHALL never be overwritten by the seed. The shipped default SHALL be a minimal placeholder with no rules of its own, because the owner writes the real content. When the personality folder cannot be created or written, the agent SHALL still start, every chat request SHALL use the shipped default as the personality file, every personality write SHALL be refused with HTTP 503 on REST and a refusal message on the tool, and one ERROR line SHALL name the folder and the cause.

#### Scenario: First start seeds the default personality

- **WHEN** the agent starts with an empty agent home root
- **THEN** `<agent home>/tenants/default/soul/SOUL.md` exists with the shipped placeholder text
- **AND** its repository has one commit with origin `seed`
- **AND** neither `<agent home>` nor `<agent home>/tenants/default/` holds a `.git` folder

#### Scenario: Existing personality survives a restart

- **WHEN** the owner replaced the personality file and the agent restarts
- **THEN** the file still holds the owner's text and no new commit was made

#### Scenario: Personality folder on a read-only mount

- **WHEN** the personality folder of the tenant cannot be written
- **THEN** the agent starts and chat requests carry the shipped default as the first system message
- **AND** `PUT /api/v1/personality` answers HTTP 503

### Requirement: A personality file is validated before it is accepted or used

A personality file SHALL be accepted only when it is valid UTF-8, holds no NUL character, is not blank, is at most `app.soul.personality.max-chars` characters long (Unicode code points, default 8000, never above `app.soul.hard-cap-chars`, default 20000), holds none of the invisible or direction control characters U+200B to U+200F, U+202A to U+202E, U+2066 to U+2069 and U+FEFF, and does not contain the reserved markers the prompt layout uses (the reminder tag and the conversation summary marker). The same rules SHALL apply to every write and to every file read from disk. The file SHALL never be truncated. When the file on disk fails a rule, the agent SHALL use the newest committed version of the file that passes every rule, log one WARN line naming the tenant, the path and the reason, and keep doing so until the file is valid again. When no committed version is valid, the agent SHALL use the shipped default and log one ERROR line.

#### Scenario: Oversized personality is refused

- **WHEN** the owner sends a personality file of 8001 characters with the default limit
- **THEN** the write is refused with reason `too_large` and a message naming the limit
- **AND** the file and its repository are unchanged

#### Scenario: Hand edit breaks the file on disk

- **WHEN** someone edits `SOUL.md` on the volume and adds a U+202E character
- **THEN** the next chat request carries the newest valid committed version as its first system message
- **AND** one WARN line names the tenant, the path and the reason `invisible_character`

#### Scenario: Reserved marker is refused

- **WHEN** a personality write contains the reminder tag text
- **THEN** the write is refused with reason `reserved_marker`

### Requirement: The personality file is always the first system message and is never trimmed

Every chat request SHALL send the prompt with exactly three system messages in this order: first the personality file of the request's tenant under a fixed heading, second the global `app.system-prompt`, third one dynamic block holding every per-request system content. No other system message SHALL be sent, wherever it comes from. The personality file SHALL be read once at the start of the request, and a write that lands during the request SHALL apply from the next request. Its text SHALL be sent in full in every request, whatever the length of history, memory, retrieved documents or attachments, and SHALL never be truncated, summarised, moved or dropped to make room. The personality file and its heading SHALL never be written into chat history.

#### Scenario: Long conversation keeps the personality first

- **WHEN** a conversation's history fills the context budget of the request's provider
- **THEN** the first system message of the request is the fixed heading followed by the full personality file, byte for byte
- **AND** the request carries exactly three system messages

#### Scenario: Write during a request

- **WHEN** the owner replaces the personality file while a chat request is running
- **THEN** that request keeps the version it started with
- **AND** the next request carries the new version

#### Scenario: Personality is not stored in history

- **WHEN** a chat request completes
- **THEN** no chat history row in Redis or Postgres contains the personality file text or its heading

### Requirement: A fixed reminder ends every prompt

Every chat request SHALL build its final user message in this order: the attached document text when a document is attached, the retrieved document context when there is any, then a fixed reminder, then the user's own typed text, so the reminder and the user's text are the last part of the prompt. The reminder SHALL only tell the model to read and follow the personality file again and SHALL carry no rules of its own. It SHALL be the same bytes in every request, at most 400 characters, wrapped in a reserved tag, and fixed in code with no setting, because this change writes it, not the owner. It SHALL be part of the user message and SHALL NOT be sent as a system message. It SHALL NOT be written into chat history, which keeps storing the user message without it. When the user message carries an image, the reminder SHALL be in the text part of that message.

#### Scenario: Reminder sits right before the user's text

- **WHEN** a user sends the prompt "what is the weather in Krakow"
- **THEN** the final user message sent to the provider ends with the reminder followed by "what is the weather in Krakow"
- **AND** no system message holds the reminder

#### Scenario: Retrieved context comes before the reminder

- **WHEN** a request carries retrieved document context and an attached document
- **THEN** the final user message holds the attached document text, then the retrieved context, then the reminder, then the user's typed text

#### Scenario: Reminder is not saved

- **WHEN** the turn is saved to chat history
- **THEN** the saved user message does not contain the reminder

### Requirement: One validated write path changes the personality file

Replacing and reverting the personality file and applying an approved proposal SHALL go through one write path and SHALL act only on the caller's tenant. Writes for one tenant SHALL run one at a time, also when several agent instances share the agent home, through a lock held in the shared database. An accepted write SHALL validate the content first, replace `SOUL.md` atomically, commit it to the tenant's soul repository with the origin (`owner` for a REST replace, `agent` for an approved proposal, `external` for an uncommitted hand edit found before a write, `seed`, `revert`), the chat request id and proposal id when there are any, and never a user id, and SHALL report the new commit id. A refused write SHALL leave the file and the repository unchanged and SHALL report a reason from a closed set (`too_large`, `blank`, `not_utf8`, `invisible_character`, `reserved_marker`, `conflict`, `not_found`, `forbidden`, `unclean_request`, `stale_proposal`, `unavailable`). The personality file SHALL NOT be deletable.

#### Scenario: Owner replaces the personality through REST

- **WHEN** an owner sends `PUT /api/v1/personality` with valid content
- **THEN** the response is 200 with the new commit id as `ETag`
- **AND** the repository has one new commit with origin `owner`

#### Scenario: Stale If-Match is refused

- **WHEN** `PUT /api/v1/personality` carries an `If-Match` commit id that is not the newest
- **THEN** the response is 412 and nothing is written

#### Scenario: Two instances write one after the other

- **WHEN** two agent instances replace the personality of one tenant at the same moment with the same `If-Match`
- **THEN** one write commits and the other is refused with 412, and the repository holds no interleaved commit

#### Scenario: Revert writes a new commit

- **WHEN** the owner sends `POST /api/v1/personality/revert` with an older commit id
- **THEN** `SOUL.md` holds the content of that commit
- **AND** history shows a new commit with origin `revert` and keeps every older commit

### Requirement: REST endpoints for the personality file

The agent SHALL expose, acting on the caller's tenant: `GET /api/v1/personality` (content, size, limit, newest commit id as `ETag`, and whether the file on disk is valid or the last valid version is in use), `PUT /api/v1/personality` (replace, with optional `If-Match`), `GET /api/v1/personality/history` (commits newest first with id, time, origin, request id and size), `POST /api/v1/personality/revert` (body holding a commit id), `GET /api/v1/personality/proposals` (proposals newest first, filtered by status, pending by default), `GET /api/v1/personality/proposals/{id}` (status, approval id, the before text, the after text and a unified diff). Both proposal endpoints SHALL read through the proposal port, so once `add-action-approvals` is applied they are a view of its approval requests of kind `personality_change`, and before that they answer an empty list and 404. The agent SHALL NOT expose an endpoint of its own that approves or rejects a proposal, because every proposal is decided through `/api/v1/approvals` of `add-action-approvals`. A body larger than the limit plus one character SHALL be answered with 413 and `code` `content_too_large` without being held in memory. Outside the `dev` profile of `add-keycloak-login` the write endpoints and every proposal endpoint SHALL require the `ADMIN` role. Every error SHALL be the RFC 7807 problem detail that `upgrade-spring-boot-4` defines for every agent error: content type `application/problem+json` with the fields `type` (`https://ascend.ai/errors/` followed by the code with every `_` replaced by `-`), `title`, `status`, `detail`, `instance` and a top-level `code`. A validation refusal (`blank`, `not_utf8`, `invisible_character`, `reserved_marker`, and a revert whose content fails validation) SHALL answer 400 with `code` `validation` and the extension field `errors` that `upgrade-spring-boot-4` defines, one object with `field` and `message` per failed rule, where each `message` starts with the specific reason. The specific reason SHALL appear only inside the `errors` messages and in the tool text, and SHALL never be the `code` of a body. Every other refusal SHALL carry its own code (`conflict`, `not_found`, `forbidden`, `unavailable`, `content_too_large`). The `detail` and the `errors` messages SHALL never contain file content.

#### Scenario: Reserved marker refused through REST

- **WHEN** an owner sends `PUT /api/v1/personality` with content that holds the reminder tag text
- **THEN** the response is 400 with `Content-Type: application/problem+json`
- **AND** the body has `code` `validation`, `type` `https://ascend.ai/errors/validation`, `status` 400 and `instance` `/api/v1/personality`
- **AND** `errors` holds one object with `field` `content` and a `message` that starts with `reserved_marker`
- **AND** the file and its repository are unchanged

#### Scenario: Non-admin cannot replace the personality

- **WHEN** a caller without `ADMIN` sends `PUT /api/v1/personality`
- **THEN** the response is 403 and nothing is written

#### Scenario: History lists every change

- **WHEN** the personality was seeded, replaced by the owner and then reverted
- **THEN** `GET /api/v1/personality/history` lists three commits with origins `revert`, `owner` and `seed` in that order

### Requirement: The agent only proposes personality changes and the owner approves each one once

The agent SHALL never change the personality file alone. It SHALL offer a `personality_propose` tool taking the full new content only when `app.soul.personality.proposals.enabled` is true (default true), a proposal port implementation that stores proposals exists (the one of `add-action-approvals`), the soul folder of the tenant is writable, and the caller holds the `ADMIN` role outside the `dev` profile of `add-keycloak-login`. An accepted call SHALL validate the content, hand a proposal with the newest commit id as its base, the content and the optional reason to the proposal port, which stores it only as one approval request of kind `personality_change` of `add-action-approvals`, change nothing on disk, and return the proposal id, which is the approval id, the size before and after and a short diff, telling the model to tell the user that the change waits for the owner's approval. The tool SHALL refuse with reason `unclean_request` when the request provenance of the chat request is not `clean`, that is when the request carries retrieved document context or an attached document, when it is a turn written by a peer bot, or when a tool whose result can carry outside content ran earlier in the same request, because then the content may come from a page or a file rather than from the owner. The tool SHALL never be offered to a run of `add-agent-subagents`, with one documented exception: a run of kind `self_review` of `add-self-improvement` may be offered it, there it SHALL only store a proposal that waits for the owner's approval like any other, the clean-request rule SHALL be evaluated on the review's recorded provenance (`clean` only), and the `ADMIN` caller check SHALL be replaced by the tenant's grant of the `self-improvement` module, because a review has no caller. No other kind of run SHALL be offered it. The tool SHALL also take an optional reason of at most `app.soul.reason-max-chars` characters (default 300), stored in the proposal and in the commit an approval makes. This capability SHALL keep no proposal table of its own. A refusal SHALL be returned to the model as text and SHALL never fail the chat request.

A proposal SHALL be decided once, only by the decision operations of the proposal service, which only the approval service of `add-action-approvals` calls, and the approval service SHALL run the approve operation at most once. The approve operation SHALL apply the proposed content through the write path with origin `agent` only when its base commit is still the newest commit. A proposal whose base commit is no longer the newest SHALL be refused with `stale_proposal`, returned to the caller of the operation as the reason of a failed execution, and the proposal SHALL then read `stale`. The proposal status SHALL be read from its approval request: `pending`, `approved`, `stale`, `rejected` after a denial, `expired` after a timeout, or `cancelled`. Neither a denial nor a timeout SHALL change anything on disk, and an `expired` or `rejected` proposal SHALL never be applied. No REST endpoint of this capability SHALL decide a proposal. Until `add-action-approvals` is applied, the tool SHALL NOT be offered and the personality file SHALL stay unchanged. User facts SHALL need no approval.

#### Scenario: Owner asks for a new personality in chat

- **WHEN** an owner asks the agent in chat to set a new personality and the model calls `personality_propose` as the first tool of the request
- **THEN** one approval request of kind `personality_change` holds the proposal with status `pending`, and `SOUL.md` and its repository are unchanged
- **AND** the tool result holds the proposal id and tells the model the change waits for approval

#### Scenario: A proposal is approved once

- **WHEN** the approve operation runs for a pending proposal whose base commit is the newest
- **THEN** `SOUL.md` holds the proposed content and the repository has one new commit with origin `agent`, the chat request id and the proposal id
- **AND** the proposal is `approved`, and a second approve of the same proposal changes nothing

#### Scenario: Proposal made before another change is stale

- **WHEN** the owner replaces the personality through REST and then the approve operation runs for a proposal made before that replace
- **THEN** the operation fails with reason `stale_proposal`, the proposal reads `stale` and the file keeps the owner's text

#### Scenario: Rejected proposal changes nothing

- **WHEN** the owner denies the approval of a pending proposal
- **THEN** the proposal reads `rejected` and `SOUL.md` and its repository are unchanged

#### Scenario: Expired proposal changes nothing

- **WHEN** the approval of a pending proposal times out
- **THEN** the proposal reads `expired` and `SOUL.md` and its repository are unchanged
- **AND** the proposal is never applied afterwards

#### Scenario: No proposal before the approval service exists

- **WHEN** the agent runs without `add-action-approvals` applied
- **THEN** `personality_propose` is not offered to the model and `GET /api/v1/personality/proposals` answers an empty list
- **AND** `POST /api/v1/personality/proposals/{id}/approve` answers 404 and changes nothing

#### Scenario: Owner sees the before and after view

- **WHEN** the owner sends `GET /api/v1/personality/proposals/{id}`
- **THEN** the response holds the file text at the proposal's base commit, the proposed text and a unified diff between them

#### Scenario: Web content cannot propose a personality

- **WHEN** the model calls a web search tool and then `personality_propose` in the same request
- **THEN** the tool returns a refusal with reason `unclean_request`
- **AND** no proposal and no approval request is stored

### Requirement: Every chat request carries one request provenance value

Every chat request SHALL have one request provenance value, computed in code and never taken from the model, with exactly three values ordered from most to least trusted: `clean`, `retrieved` and `untrusted`. The agent SHALL compute it once at the start of the request: `retrieved` when retrieved document context was added to the request, `untrusted` when a document was attached, when the turn was written by a peer bot of the plugin host, or when the finished runs block added the result of a finished run of any kind or the outcome of a main chat approval (for example a subagent or a coding run) to the request, else `clean`. During the request the value SHALL only move towards `untrusted`, and SHALL move to `untrusted` when a tool is called whose result can carry outside content, before that tool runs. Every tool SHALL count as such a tool except the agent's own tools whose result holds only its stored text or a status (`Skill`, `skill_search`, `skill_read_file`, `skill_write`, the definition write tool, `personality_propose`, `user_facts_update`, and the self-improvement tools `skill_patch`, `subagent_definition_patch` and `request_self_review`). This closed list SHALL be the only list of such tools, kept in code, with no setting that adds names. The value SHALL record which of the sources `retrieved_document`, `attachment`, `peer_bot_turn`, `finished_run_result` and `outside_tool_result` lowered it. The personality proposal tool, the user facts tool and the self-improvement capability SHALL all read this one value and SHALL NOT compute a provenance of their own. A run started by the `Task` tool SHALL start at its caller's current value, and a run of kind `self_review` SHALL use the provenance its review recorded, which its own tool calls SHALL NOT change.

#### Scenario: A clean request

- **WHEN** a user sends a prompt with no attachment, no retrieved context is added, and the model calls only `skill_search`
- **THEN** the request provenance is `clean`

#### Scenario: Retrieved context alone

- **WHEN** retrieved document context is added to a request and the model calls no tool
- **THEN** the request provenance is `retrieved` with the source `retrieved_document`

#### Scenario: An outside tool lowers the value for the rest of the request

- **WHEN** the model calls a web search tool and later in the same request calls `personality_propose`
- **THEN** the request provenance is `untrusted` with the source `outside_tool_result` when `personality_propose` runs
- **AND** the value never moves back to `retrieved` or `clean` in that request

#### Scenario: A peer bot turn is untrusted

- **WHEN** the plugin host forwards a turn written by a peer bot
- **THEN** the request provenance is `untrusted` with the source `peer_bot_turn` from the start of the request

#### Scenario: A finished run result is untrusted

- **WHEN** the finished runs block adds the result of a finished subagent or coding run, or of a main chat approval, to a request with no attachment and no retrieved context
- **THEN** the request provenance is `untrusted` with the source `finished_run_result` from the start of the request

#### Scenario: Self-improvement tools keep the request clean

- **WHEN** a user sends a prompt with no attachment, no retrieved context is added, and the model calls only `skill_patch`, `subagent_definition_patch` and `request_self_review`
- **THEN** the request provenance is `clean`

### Requirement: Every change made during a chat request is reported in the response

When a chat request proposes a personality change or changes the user facts file, the response metadata SHALL list each entry with the file (`personality` or `user_facts`), the operation, the commit id of a change or the proposal id of a proposal, and the size before and after, whether or not the model's answer mentions it. The tool result of an accepted call SHALL tell the model to tell the user what changed or what waits for approval.

#### Scenario: Proposal appears in metadata

- **WHEN** the model proposes a personality change during a request
- **THEN** the response metadata `fileChanges` holds one entry with file `personality`, operation `propose` and the proposal id

### Requirement: Runs receive the personality file but no user facts

Every run of `add-agent-subagents` that calls a model, of every kind (`subagent`, `coding`, `scheduled`, `self_review`, `integration`), SHALL send the personality file of its tenant as its first system message, before the definition body or the instructions its kind provides, and SHALL begin its first user message with the same reminder. A run SHALL NOT receive the user facts file. A run SHALL NOT be offered `personality_propose` or `user_facts_update`, except a run of kind `self_review`, which may be offered both, where `personality_propose` only proposes. Sending the personality file to runs SHALL be switchable with `app.soul.personality.subagents.enabled` (default true). The compaction summariser and the semantic memory extractor SHALL NOT receive the personality file.

#### Scenario: Subagent run starts with the personality

- **WHEN** a subagent run starts for tenant `default`
- **THEN** its first system message is the personality file of tenant `default`
- **AND** none of its system messages contain the user facts of the calling user
- **AND** it is not offered `personality_propose` or `user_facts_update`

#### Scenario: A scheduled run gets the personality and no soul tools

- **WHEN** a run of kind `scheduled` starts for tenant `default`
- **THEN** its first system message is the personality file of tenant `default` and its first user message starts with the reminder
- **AND** it is not offered `personality_propose` or `user_facts_update`

#### Scenario: A self review run may only propose

- **WHEN** a run of kind `self_review` calls `personality_propose` with valid content and the review's provenance is `clean`
- **THEN** one approval request of kind `personality_change` holds the proposal with status `pending`, and `SOUL.md` and its repository are unchanged

### Requirement: Personality metrics and log lines

The agent SHALL record the counter `soul.write` with tags `file`, `origin`, `operation` and `outcome`, the counter `soul.personality.proposal` with tag `outcome` (`proposed`, `approved`, `rejected`, `stale`, `expired`, `refused`), and the gauge `soul.personality.fallback` (number of tenants whose file on disk is invalid). No metric SHALL carry a tenant or user tag. Every write SHALL log one INFO line with tenant, file, origin, operation, outcome, commit id and size, and never the content. The startup banner SHALL show the agent home root that holds the personality and user facts folders, whether the folder of tenant `default` is writable, the personality limit, the user facts limits, and whether subagents get the personality file.

#### Scenario: Write is counted

- **WHEN** an owner write is refused as `too_large`
- **THEN** `soul.write{file=personality,origin=owner,operation=replace,outcome=too_large}` grows by one
- **AND** the INFO line holds the size and not the content

### Requirement: Personality, user facts and the context budget are covered by end-to-end tests

The repository SHALL hold end-to-end tests for the personality file, the user facts file and the context budget against the live stack in `apps/ascend-agent/e2e/`. Every behaviour that an HTTP status, a response body or persisted state can prove SHALL be checked by a deterministic spec whose Bruno requests reach no AI model, including the refusal of a prompt too large for its context window, which happens before any model call. The refusals after an outside tool result and the prompt layout SHALL be proved by unit and integration tests and SHALL NOT be repeated end to end, because an end-to-end spec would prove nothing those tests do not (owner answer 91.3 of 2026-10-08). Only the behaviours that need a real model to judge, the personality rule followed under a near-full context, the agent recording a stated fact and the agent proposing a personality change, SHALL be checked by AI-run specs. Pass criteria SHALL be HTTP status, response bodies, the approval requests, the `chat_history` rows and the file histories only, never log lines of the agent. Every spec SHALL be listed in the run scenarios and the ascend-agent service suite of `docs/E2E_RUN_SCENARIOS.md`, every AI-run spec SHALL run on the hosted provider and model of the other AI-run agent specs and SHALL NOT need LM Studio, and the owner SHALL be asked which scenario to run before any run.

#### Scenario: Owner endpoints and the budget refusal are checked without a model

- **WHEN** the deterministic soul spec runs against the live stack with LM Studio stopped
- **THEN** every request of `docs/api/request/AscendAI/ascend-agent/testing/soul-api/` passes its status and body assertions
- **AND** the 40,000 character prompt on provider `lmstudio` answers 413 with `code` `context_too_large` and leaves no `chat_history` row

#### Scenario: The personality survives a near-full context end to end

- **WHEN** the AI-run spec sets a personality whose rule ends every reply with a fixed word and sends a prompt on provider `minimax` with model `MiniMax-M2.7` with a history past its 200,000 token window
- **THEN** the reply ends with that word
- **AND** `metadata.contextTrimmed` reports at least one dropped history turn

#### Scenario: A personality proposal changes nothing before approval end to end

- **WHEN** the AI-run spec asks the agent to change its personality
- **THEN** `metadata.fileChanges` names a proposal, the proposal reads `pending`, and `GET /api/v1/personality` is unchanged
