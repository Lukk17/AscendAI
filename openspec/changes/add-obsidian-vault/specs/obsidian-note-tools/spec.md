## Purpose

Lets the agent find, read, create and append to notes in the tenant's Obsidian vault, writing freely only into its own folder and never losing or overwriting the owner's edits.

## ADDED Requirements

### Requirement: Note tools are offered only where a vault exists and the tool policy allows them

The agent SHALL offer the model the tools `obsidian_search_notes`, `obsidian_read_note`, `obsidian_create_note`, `obsidian_append_note` and `obsidian_daily_note` in a chat request or run only when the request's tenant has at least one enabled Obsidian connector whose vault folder exists, and only those of the five that the shared tool policy port `TenantToolPolicy` allows for the tenant. With no other implementation registered, every one of the five that is not listed in `app.tool-policy.denied-tools` (empty by default) SHALL be offered. The tools SHALL exist only while the deployment module `obsidian` is in `ASCEND_MODULES`. The tools SHALL NOT be limited to users with the `ADMIN` role: every user of the tenant SHALL get the tools the policy allows. Each tool SHALL take an optional vault argument, required only when the tenant has more than one vault. A vault of another tenant SHALL be answered as not found. The agent SHALL NOT offer any tool that deletes, renames, moves or replaces a note.

#### Scenario: No vault, no tools

- **WHEN** a chat request runs for a tenant without an enabled Obsidian connector
- **THEN** none of the five tools is in the tool list given to the model

#### Scenario: A user without ADMIN gets the tools

- **WHEN** a signed-in user without the `ADMIN` role chats in a tenant with a vault and none of the five listed in `app.tool-policy.denied-tools`
- **THEN** all five tools are in the tool list given to the model

#### Scenario: The tool policy removes a write tool

- **WHEN** `app.tool-policy.denied-tools` contains `obsidian_create_note` and no other `TenantToolPolicy` is registered
- **THEN** the model is offered `obsidian_read_note` and not `obsidian_create_note`

#### Scenario: Other tenant's vault is not found

- **WHEN** a request of tenant `acme` names a vault that belongs to tenant `default`
- **THEN** the tool answers that the vault was not found and reads nothing

### Requirement: Search finds notes of one vault through RAG

`obsidian_search_notes` SHALL search the knowledge base with the request's query through the same retrieval path as every other retrieval, with every filter that path applies, narrowed to the chunks of the chosen vault by its connector id. It SHALL return at most the requested number of hits (default 5, at most 20), each with the note path, title, score and a snippet of at most 500 characters. A hit whose note no longer exists SHALL be left out.

#### Scenario: Search returns only vault notes

- **WHEN** the tenant has an uploaded document and a vault note both about "solar panels" and the model searches the vault for "solar panels"
- **THEN** the result holds the vault note and not the uploaded document

#### Scenario: Deleted note is not returned

- **WHEN** a note was deleted from the vault after it was indexed and before the next run
- **THEN** search does not return it

### Requirement: Reading returns the live note

`obsidian_read_note` SHALL accept a path relative to the vault (`.md` added when missing) or a note name, resolved like an Obsidian link: the exact path first, then a unique file name match ignoring case. An ambiguous name SHALL return up to 10 candidate paths and no content. The result SHALL be the note as it is on disk at that moment, with its size, modification time and a version (the SHA-256 of its bytes). A note longer than the read limit (default 40,000 characters) SHALL be cut at the limit and the result SHALL say so and give the full size.

#### Scenario: Read by name

- **WHEN** the model reads `Shopping` and the only matching file is `Lists/Shopping.md`
- **THEN** the content of `Lists/Shopping.md` is returned with its version

#### Scenario: Ambiguous name lists candidates

- **WHEN** the model reads `Plan` and both `Work/Plan.md` and `Home/Plan.md` exist
- **THEN** both paths are returned and no content

#### Scenario: Read sees changes not yet indexed

- **WHEN** a note changed one second ago and no run has indexed it yet
- **THEN** read returns the new content

### Requirement: Paths are checked before any file access

Every tool SHALL refuse, with a message naming the broken rule and without touching any file, a path that is absolute, contains a `..` segment, has a segment starting with a dot, lies in the config folder, `.trash` or an excluded folder, contains a character Obsidian forbids in file names or that breaks a link (`* " \ / < > : | ? # ^ [ ]` inside a segment), has a segment longer than 255 bytes or a total length over 1,024 bytes, or whose real path after resolving links is outside the vault folder. Write tools SHALL write only `.md` files. A refusal SHALL be returned to the model as a tool result and SHALL NOT fail the chat request.

#### Scenario: Traversal is refused

- **WHEN** the model asks to read `../../agent-home/tenants/default/skills/x/SKILL.md`
- **THEN** the tool refuses with the path rule named
- **AND** no file outside the vault is read

#### Scenario: Excluded folder cannot be read

- **WHEN** the connector excludes `Private` and the model reads `Private/Diary.md`
- **THEN** the tool refuses with the path rule named

#### Scenario: Link escaping the vault is refused

- **WHEN** a note path is a symbolic link pointing outside the vault folder
- **THEN** reading or writing it is refused

### Requirement: The agent writes freely only into its agent folder

`obsidian_create_note` and `obsidian_append_note` SHALL write directly only when the target is inside the vault's agent folder (default `AscendAI`), creating the folder when needed. A create with a bare name and no folder SHALL go into the agent folder. A create SHALL be refused with `note_exists` when the note exists. An append SHALL add the text after a line break at the end of the note, keeping the note's line ending style. A write whose target is outside the agent folder SHALL NOT be written. It SHALL be submitted for the owner's approval as an action of kind `obsidian_note_write` whose preview shows the vault, path, operation and the exact text, and the tool SHALL return that the write waits for approval with its approval id. After approval the server SHALL perform exactly the stored write once at most: a create still refuses when the note exists by then, and an append appends the approved text to the note as it is at that time. After denial or expiry nothing SHALL be written. A remembered allow SHALL be possible only for appends, scoped to one vault and one path.

#### Scenario: Create in the agent folder

- **WHEN** the model creates `Shopping` with some content
- **THEN** the file `AscendAI/Shopping.md` exists with exactly that content
- **AND** the sync client uploads it so it appears on the owner's devices

#### Scenario: Append outside the agent folder waits for approval

- **WHEN** the model appends a line to `Projects/Plan.md`
- **THEN** the file is unchanged
- **AND** a pending approval of kind `obsidian_note_write` shows the path and the exact line
- **AND** the tool result tells the model the write waits for approval

#### Scenario: Approved append is written once

- **WHEN** the owner approves that pending append
- **THEN** the line is appended to `Projects/Plan.md` exactly once

#### Scenario: Denied write never happens

- **WHEN** the owner denies a pending create of `Projects/New.md`
- **THEN** no file `Projects/New.md` exists

#### Scenario: Create never remembered

- **WHEN** the owner approves a pending create with "remember this choice"
- **THEN** the decision is refused as not rememberable and no rule is stored

### Requirement: Writes never overwrite the owner's concurrent edits

A write SHALL replace the note in one atomic step from a temporary file outside the synced folder, after checking that the note's bytes still match what the write read. When they changed, an append SHALL be rebuilt once on the new content and a create SHALL be refused with `note_changed`. A write to a note modified less than the recent edit guard ago (default 10 seconds) by anything other than the agent's own last write SHALL be refused with `note_busy`. A note that is not valid UTF-8 SHALL NOT be written (`not_utf8`). Writes to one vault SHALL run one at a time, also across agent instances. In normal use the agent's writes SHALL NOT create Obsidian conflict copies.

#### Scenario: Owner typing blocks the write

- **WHEN** the owner changed `AscendAI/Log.md` five seconds ago and the model appends to it
- **THEN** the tool refuses with `note_busy` and the file is unchanged

#### Scenario: Concurrent change is kept

- **WHEN** the note changes between the agent's read and its write
- **THEN** the note afterwards holds both the concurrent change and the appended text

#### Scenario: No partial note on failure

- **WHEN** a write fails after the temporary file was written
- **THEN** the note holds its previous content exactly
- **AND** no temporary file is left in the vault folder

#### Scenario: Agent write does not produce a conflict copy

- **WHEN** the agent appends to a note while the same note is edited on another device and both changes sync
- **THEN** no file whose name contains `(Conflicted copy` is created by the sync client on this vault

### Requirement: The daily note follows the vault's Daily notes settings

`obsidian_daily_note` SHALL read or append to the daily note of a given date (default today in the configured time zone, default `Europe/Warsaw`). It SHALL take the folder, the date format and the template from the vault's Daily notes settings, and the vault root and `YYYY-MM-DD` when those settings are absent. A date format with a token outside the supported set SHALL be refused, naming the token. Appending to a daily note that does not exist SHALL create it first from the template with `{{title}}`, `{{date}}` and `{{time}}` filled in, or empty when there is no template. Appending to today's daily note SHALL NOT need approval while the vault's daily note setting allows it (the default). Every other write to a daily note outside the agent folder SHALL follow the approval rule.

#### Scenario: Append to today's daily note

- **WHEN** the settings say folder `Daily` and format `YYYY-MM-DD`, today is 2026-10-02, and the model appends "Called the bank"
- **THEN** `Daily/2026-10-02.md` ends with "Called the bank"
- **AND** no approval was requested

#### Scenario: Missing daily note is created from the template

- **WHEN** `Daily/2026-10-02.md` does not exist and the template holds `# {{title}}`
- **THEN** the note is created starting with `# 2026-10-02` before the text is appended

#### Scenario: Unknown format token is refused

- **WHEN** the daily note format contains a token the agent does not support
- **THEN** the tool refuses and names the token
- **AND** no file is written

#### Scenario: Yesterday's daily note needs approval

- **WHEN** the model appends to the daily note of yesterday, which is outside the agent folder
- **THEN** the write waits for the owner's approval

### Requirement: Size and count limits

The agent SHALL refuse with `too_large`, without writing anything, a create or append whose content exceeds the write content limit (default 64 KiB) or that would make the note larger than the maximum note size (default 2 MiB). It SHALL refuse with `write_limit` a write beyond the per-request write limit (default 20 per chat request or run). A refused write SHALL never be cut and written in part. Every limit SHALL be configurable, and a zero or negative value SHALL stop the agent at startup with an error naming the property.

#### Scenario: Oversized append is refused whole

- **WHEN** the model appends 100 KiB of text with the default limit
- **THEN** the tool refuses with `too_large`
- **AND** the note is unchanged

#### Scenario: Write limit per request

- **WHEN** the model makes a 21st write in one chat request with the default limit
- **THEN** that write is refused with `write_limit`

### Requirement: Tools warn while the vault is not syncing

While a vault's sync status is not up, every note tool SHALL still work on the local copy, and its result SHALL begin with one line saying since when the vault is not syncing, that notes may be out of date, and that writes will reach the owner's devices only when sync is back.

#### Scenario: Read while sync is down

- **WHEN** the vault's sync status is `down` and the model reads a note
- **THEN** the result starts with the not syncing line and then holds the note

### Requirement: Tool use is audited, measured and logged without note content

Every write attempt SHALL be recorded as one audit event through `AuditEventPort` with the event name `OBSIDIAN_NOTE_WRITTEN`, actor, tenant, the target made of the connector id, the operation, the outcome (`written`, `approval_pending` or `refused`), the content's length and SHA-256, and the full note path in the `details` entry `path`, never the content. The default `LogAuditEventPort` SHALL NOT print the path, and only a registered company audit store SHALL save it. The agent SHALL count tool calls by tool and outcome and write refusals by reason. No metric tag and no INFO log line SHALL contain a note path, title or content. An INFO line per write SHALL carry the request id, vault, operation and a short hash of the path.

#### Scenario: Write leaves an audit event without content

- **WHEN** the model appends to `AscendAI/Log.md`
- **THEN** one event with the name `OBSIDIAN_NOTE_WRITTEN`, outcome `written`, the connector id as target, `AscendAI/Log.md` in the `details` entry `path` and the content's SHA-256 reaches `AuditEventPort`
- **AND** the appended text appears in no event field
- **AND** with the default `LogAuditEventPort` neither the appended text nor the path appears in any INFO log line

#### Scenario: Write INFO line carries the short path hash

- **WHEN** the model appends to `AscendAI/Log.md`
- **THEN** one INFO line for the write carries the request id, the vault, the operation and the first 12 hex digits of the SHA-256 of `AscendAI/Log.md` (owner answer 73.3 of 2026-10-06)
- **AND** that line does not contain `AscendAI/Log.md`

### Requirement: The note tools are proven end to end without an AI model and with one

The repository SHALL hold a deterministic end-to-end spec in `apps/ascend-agent/e2e/testing/` that calls the five note tools through the scripted model of the shared harness of `close-agent-test-gaps`, so that no chat model runs, against a fake vault seeded into the `obsidian-vaults` volume, with its Bruno requests in `docs/api/request/AscendAI/ascend-agent/testing/obsidian/`. It SHALL prove the read, the path refusal, the free write in the agent folder, the approval wait with approve and deny for a write outside the agent folder, the daily note created from the template, the write limit and the not syncing line. The repository SHALL also hold an AI-run spec where a real model answers from a note and asks before writing outside the agent folder. Both SHALL pass only on HTTP responses, file contents and persisted rows, never on a log line, and SHALL need no Obsidian account.

#### Scenario: Approved append proven once on disk

- **WHEN** the scripted model appends to `Home/Boiler.md`, the spec approves the pending request with its `argumentsDigest`, and reads the file
- **THEN** the file is unchanged before the approval and holds the appended text exactly once after it

#### Scenario: Traversal proven refused on disk

- **WHEN** the scripted model asks `obsidian_create_note` for `../outside.md`
- **THEN** the tool result is a refusal and no file named `outside.md` exists anywhere on the volume
