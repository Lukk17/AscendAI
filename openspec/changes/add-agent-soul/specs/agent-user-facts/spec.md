## Purpose

Gives each user one small file of stable facts and preferences that the agent sees in every request and may keep up to date itself, stored with git history in a folder of its own so that erasing one user removes it completely.

## ADDED Requirements

### Requirement: Each user has one user facts file in a repository of its own

Each user SHALL have at most one user facts file, `USER.md`, in the folder `<agent home>/tenants/<tenantId>/users/<userKey>/`, where `<agent home>` is the agent home root `app.agent-home` that also holds the personality file, and that folder SHALL be its own git repository. The `users/` folder itself SHALL NOT be a git repository. `userKey` SHALL be the first 32 hexadecimal characters of the SHA-256 digest of `<tenantId>:<userId>`, so no user id appears in any path or commit. The folder SHALL be created on the user's first write. A user without a folder SHALL have no user facts. Commits SHALL record the origin (`owner` for REST, `agent` for the tool, `external`, `revert`) and the chat request id when there is one. Changes by the agent SHALL need no approval.

#### Scenario: First fact creates the folder

- **WHEN** user `frosty` of tenant `default` has no user facts and the agent adds one entry
- **THEN** the folder `<agent home>/tenants/default/users/<first 32 hex of sha256("default:frosty")>/` exists with a repository and one commit
- **AND** no path or commit message contains `frosty`

### Requirement: User facts are validated and limited

A user facts file SHALL be accepted only when it is valid UTF-8, holds no NUL, is at most `app.soul.user-facts.max-chars` characters (default 4000), holds none of the invisible or direction control characters listed for the personality file, and does not contain the reserved markers of the prompt layout. An entry added or replaced by the agent SHALL be one line of at most `app.soul.user-facts.max-entry-chars` characters (default 500). A write that would pass the limit SHALL be refused with reason `too_large` and a message giving the current size and the limit, and the file SHALL never be truncated. A file on disk that fails a rule SHALL be replaced in the prompt by its newest valid committed version with one WARN line.

#### Scenario: Full file refuses a new entry

- **WHEN** the file holds 3950 characters and the agent adds an entry of 100 characters
- **THEN** the tool returns a refusal with reason `too_large`, the current size 3950 and the limit 4000
- **AND** the file is unchanged

### Requirement: User facts are placed in the dynamic system block

Every chat request SHALL put the user facts of the calling user, read once at the start of the request, at the start of the third system message under a fixed heading. When the user has no facts, the heading SHALL be followed by a fixed "none" line so the block is always present. The user facts SHALL never be part of the cached prefix and SHALL never be sent to another user's request, a subagent run, the compaction summariser or the semantic memory extractor.

#### Scenario: Facts reach the prompt

- **WHEN** user `frosty` has the entry "- Prefers answers in Polish"
- **THEN** the third system message of `frosty`'s next request contains that entry under the user facts heading
- **AND** no request of another user contains it

### Requirement: The agent keeps the user facts up to date with entry operations

The agent SHALL offer a `user_facts_update` tool with the actions `add` (append one entry as a line starting with `- `), `replace` (replace the one entry containing a given text with a new entry) and `remove` (remove the one entry containing a given text), offered when `app.soul.user-facts.agent-write.enabled` is true (default true). The tool SHALL also take an optional reason of at most `app.soul.reason-max-chars` characters (default 300), recorded in the commit. A `replace` or `remove` whose text matches no entry or more than one entry SHALL be refused with reason `not_found` or `ambiguous`. The tool SHALL act only on the calling user's file. It SHALL refuse with reason `unclean_request` when the request provenance of the chat request is `untrusted`, that is when a tool whose result can carry outside content ran earlier in the same request, when the request carries an attached document, or when it is a turn written by a peer bot. A request provenance of `retrieved` SHALL NOT make the request unclean for this tool, because retrieval runs on most requests and a user facts entry reaches only that one user. It SHALL never be offered to a run of `add-agent-subagents`, with one exception: a run of kind `self_review` of `add-self-improvement` may be offered it, and for that run the clean-request rule SHALL be evaluated on the review's recorded provenance (`clean` or `retrieved`) instead of on the run's own tool calls. Every accepted change SHALL be reported in the response metadata as the personality spec requires.

#### Scenario: Agent records a stated preference

- **WHEN** the user says "please always answer me in Polish" and the model calls `user_facts_update` with action `add`
- **THEN** the file ends with the new entry and one commit with origin `agent`
- **AND** the response metadata lists the change with file `user_facts`

#### Scenario: Only a self review run may update facts

- **WHEN** a run of kind `subagent` and a run of kind `self_review` start for the same user
- **THEN** the `subagent` run is not offered `user_facts_update`
- **AND** the `self_review` run is offered it

#### Scenario: Ambiguous remove is refused

- **WHEN** two entries contain the word "Polish" and the model asks to remove "Polish"
- **THEN** the tool returns a refusal with reason `ambiguous` and the file is unchanged

#### Scenario: Fact taken from a web page is refused

- **WHEN** the model calls a web page reading tool and then `user_facts_update` in the same request
- **THEN** the tool returns a refusal with reason `unclean_request` that says the user can confirm the fact in a new message
- **AND** the file is unchanged

### Requirement: REST endpoints for the user facts file

The agent SHALL expose, acting on the calling user of the caller's tenant (the user resolved the same way as for `POST /api/v1/ai/prompt`): `GET /api/v1/user-facts`, `PUT /api/v1/user-facts` (replace, optional `If-Match`), `DELETE /api/v1/user-facts` (empties the file with a commit), `GET /api/v1/user-facts/history` and `POST /api/v1/user-facts/revert`. Every error SHALL be the RFC 7807 problem detail that `upgrade-spring-boot-4` defines for every agent error: content type `application/problem+json` with the fields `type` (`https://ascend.ai/errors/` followed by the code with every `_` replaced by `-`), `title`, `status`, `detail`, `instance` and a top-level `code`. A validation refusal (`not_utf8`, `invisible_character`, `reserved_marker`, and a revert whose content fails validation) SHALL answer 400 with `code` `validation` and the extension field `errors` that `upgrade-spring-boot-4` defines, one object with `field` and `message` per failed rule, where each `message` starts with the specific reason, which SHALL never be the `code` of a body. A body over the limit SHALL answer 413 with `code` `content_too_large`. The `detail` and the `errors` messages SHALL never contain file content. A user SHALL never read or write another user's file through these endpoints.

#### Scenario: Oversized user facts refused through REST

- **WHEN** a user sends `PUT /api/v1/user-facts` with 4001 characters and the default limit
- **THEN** the response is 413 with `Content-Type: application/problem+json`
- **AND** the body has `code` `content_too_large`, `type` `https://ascend.ai/errors/content-too-large`, `status` 413 and a `detail` naming the size and the limit
- **AND** the file is unchanged

#### Scenario: Invisible character refused through REST

- **WHEN** a user sends `PUT /api/v1/user-facts` with content that holds the character U+202E
- **THEN** the response is 400 with `Content-Type: application/problem+json` and `code` `validation`
- **AND** `errors` holds one object with `field` `content` and a `message` that starts with `invisible_character`
- **AND** the file is unchanged

#### Scenario: User clears their facts

- **WHEN** a user sends `DELETE /api/v1/user-facts`
- **THEN** the response is 204, the file is empty and history shows the delete commit
- **AND** the next chat request shows the "none" line under the user facts heading

### Requirement: User instructions are removed without a copy

The agent SHALL no longer read user instructions for the prompt and SHALL no longer use the Redis key `user:{userId}:instructions`. A versioned Flyway migration of this change SHALL drop the `user_instructions` table in the same release, with no copy of its rows into user facts, because the owner decided on 2026-10-02 (confirmed by owner answer 73.1 of 2026-10-06) that there is no existing data to keep. This SHALL hold only until the first real customer deployment.

#### Scenario: Table is gone after the migration

- **WHEN** the agent starts on a database that holds `user_instructions`
- **THEN** after startup the table no longer exists and no user facts folder was created for its rows
- **AND** no prompt contains a "User Instructions:" block
