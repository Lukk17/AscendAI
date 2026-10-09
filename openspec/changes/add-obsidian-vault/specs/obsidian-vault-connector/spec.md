## Purpose

Indexes the notes of a synced Obsidian vault into the tenant's knowledge base through the existing connector framework and ingestion path, within seconds of a change, and removes deleted notes.

## ADDED Requirements

### Requirement: Obsidian is a connector type with a jailed vault location

The connector framework SHALL offer the connector type `OBSIDIAN`. Its configuration SHALL name the vault by a vault name (`[a-z0-9-]{1,64}`), never by a path, and SHALL hold the agent folder (default `AscendAI`), extra excluded folders, whether attachments are indexed (default off), and whether appending to today's daily note needs approval. The server SHALL resolve the vault folder as `<vaults root>/tenants/<tenantId>/<vaultName>/vault` for the connector's own tenant. A create or update SHALL be refused with HTTP 400 when that folder does not exist, when its real path is outside the tenant's folder, or when another connector already uses that vault. The connector SHALL need no stored credential.

#### Scenario: Connector for an existing vault is created

- **WHEN** an ADMIN of tenant `default` creates an `OBSIDIAN` connector with vault name `main` and the folder `tenants/default/main/vault` exists
- **THEN** the connector is stored with an empty credentials reference

#### Scenario: Another tenant's vault cannot be reached

- **WHEN** an ADMIN of tenant `acme` creates an `OBSIDIAN` connector naming a vault that exists only under tenant `default`
- **THEN** the request is refused with HTTP 400
- **AND** no connector row is created

#### Scenario: Symbolic link escaping the tenant folder is refused

- **WHEN** the vault folder of a tenant is a symbolic link to a folder outside that tenant's folder
- **THEN** creating a connector for it is refused with HTTP 400

### Requirement: Changes in the vault start indexing within seconds

The agent SHALL watch every folder of each enabled Obsidian vault for added, changed and deleted files. After a burst of changes it SHALL start one connector run once no change arrived for the quiet period (default 3 seconds), and at the latest after the maximum delay (default 30 seconds) from the first change. A change that arrives while a run of that connector is in progress SHALL cause exactly one further run after the current one ends, and runs of one connector SHALL never overlap. A watcher overflow, a watcher error and the start of the agent SHALL each start a full rescan on the instance that saw them. The system task `obsidian-vault-rescan` of the shared scheduler of `add-shared-scheduler`, on the five-field cron `app.scheduler.system-tasks.obsidian-vault-rescan.cron` (default `*/15 * * * *` in `Europe/Warsaw`), SHALL start one full rescan for every enabled `OBSIDIAN` connector per firing, run by exactly one agent instance, and SHALL be registered only while the module `obsidian` is active. An `OBSIDIAN` connector SHALL have no cron of its own, and a create or update that sets one SHALL be refused with HTTP 400.

#### Scenario: Edited note is re-indexed

- **WHEN** the owner edits the note `Projects/Plan.md` on his phone and the sync client writes it into the vault folder
- **THEN** within the quiet period plus the time of one run, retrieval returns the new text of the note
- **AND** retrieval no longer returns text that was removed from it

#### Scenario: Typing burst starts one run

- **WHEN** a note is written ten times within two seconds and then not touched
- **THEN** exactly one run is started for those writes

#### Scenario: Change during a run is not lost

- **WHEN** a note changes while a run of the same connector is in progress
- **THEN** exactly one more run starts after that run ends
- **AND** it indexes the change

#### Scenario: Missed event is caught by the rescan

- **WHEN** a note changed while the agent was stopped and the agent starts
- **THEN** the startup rescan indexes the change

#### Scenario: Scheduled rescan catches a missed change

- **WHEN** a note changes without any watcher event reaching the agent and the system task `obsidian-vault-rescan` fires
- **THEN** one rescan run with trigger `SCHEDULED` starts for that connector and indexes the change

#### Scenario: Module off registers no rescan

- **WHEN** the agent starts without `obsidian` in `ASCEND_MODULES`
- **THEN** the system task `obsidian-vault-rescan` is not registered and no vault is watched

### Requirement: Every run compares the vault with its file manifest

Every run SHALL compute what changed by comparing the eligible files of the vault with the connector's stored file manifest, whatever started the run: a file not in the manifest is added, a file whose content hash differs is changed, a manifest entry whose file is gone is deleted, and a renamed file is a deletion plus an addition. A file whose size and modification time are unchanged SHALL NOT be read.

#### Scenario: Renamed note moves in the index

- **WHEN** the owner renames `Ideas.md` to `Archive/Ideas.md`
- **THEN** after the next run, the note's chunks are found under the new path
- **AND** no chunk of the old path remains

#### Scenario: Unchanged vault produces no work

- **WHEN** a rescan runs and no file changed since the previous run
- **THEN** no object is written to object storage and no ingestion of a note takes place

### Requirement: Only eligible notes are indexed

A file SHALL be indexed only when it is a Markdown note (`.md`), or an allowlisted PDF or image when attachments are enabled for the vault, and is at most the maximum note size (default 2 MiB). These SHALL never be indexed, whatever the configuration: the vault's config folder, `.trash`, any path with a segment starting with a dot, any file whose name contains ` (Conflicted copy`, and `.canvas` and `.base` files. The templates folder named in the vault's Templates settings and every folder in the connector's excluded folders SHALL NOT be indexed. At most the configured number of files per vault (default 20,000) SHALL be indexed, in path order. A file left out for size or for the file limit SHALL be recorded in the run history as `SKIPPED` with the reason `too_large` or `vault_file_limit`.

#### Scenario: Config folder and trash are ignored

- **WHEN** files change under `.obsidian/` and `.trash/`
- **THEN** no run indexes them and retrieval never returns their text

#### Scenario: Conflict copy is not indexed

- **WHEN** the file `Plan (Conflicted copy laptop 202610021200).md` appears in the vault
- **THEN** it is not indexed

#### Scenario: Oversized note is skipped with a reason

- **WHEN** a note of 3 MiB is in the vault and the limit is 2 MiB
- **THEN** the run history records it `SKIPPED` with reason `too_large`

### Requirement: Notes go through the existing pipeline only

The connector SHALL land each added or changed note's bytes in object storage under the tenant prefix and let the framework start the existing ingestion run, which parses it through the existing Markdown path. The connector SHALL NOT parse, chunk or embed a note, and SHALL NOT write to the vector store. Each object key SHALL be unique per vault path, also when two paths differ only in characters the file name sanitizer replaces. Each landed note SHALL be registered with source type `connector:obsidian`, an origin URI `obsidian://<vaultName>/<encoded path>` and its connector id, and every chunk of it SHALL carry its source type and connector id.

#### Scenario: Notes with similar names do not collide

- **WHEN** the vault holds `Zażółć.md` and `Za_.md`
- **THEN** both are stored under different object keys and both are retrievable

#### Scenario: Registry shows the vault origin

- **WHEN** a note was indexed and an ADMIN lists documents filtered by source type `connector:obsidian`
- **THEN** the note is listed with its origin URI naming the vault and the note path

### Requirement: Deleted notes leave the knowledge base

When a note is gone from the vault, the next run SHALL remove its stored object and its chunks through the single-document deletion path and remove its manifest entry, and the run history SHALL record it `DELETED`. Neither a run, nor deleting the connector, nor erasing the tenant SHALL ever delete or change a file in the vault folder.

#### Scenario: Deleted note disappears from retrieval

- **WHEN** the owner deletes `Old idea.md` on his desktop and the sync client removes it from the vault folder
- **THEN** after the next run retrieval no longer returns its text
- **AND** the run history records it `DELETED`

#### Scenario: Deleting the connector keeps the vault

- **WHEN** an ADMIN deletes the Obsidian connector
- **THEN** every file in the vault folder is unchanged

### Requirement: Sync health is visible in the agent

The agent SHALL read each enabled vault's sync status file at the configured status read interval (30 seconds by default) and treat the vault as not syncing when the file is missing, older than the configured maximum status age (2 minutes by default), or says `down`. It SHALL expose per vault whether sync is up and the seconds since the client was last connected, SHALL log one WARN line when a vault stops syncing and one INFO line when it syncs again, and SHALL keep indexing the local copy while sync is down.

#### Scenario: Expired token becomes visible in the agent

- **WHEN** the sync status file says `down`
- **THEN** the metric for that vault reports sync as not up
- **AND** one WARN line names the vault and the time it stopped syncing

### Requirement: Indexing is measured and logged without note content

The agent SHALL count watcher events by kind, rescans by reason, and conflict copies present per vault. No metric tag and no INFO log line SHALL contain a note path, title or content. Run logs SHALL carry counts, and the startup banner SHALL list each vault with its tenant, connector id, sync state and file count.

#### Scenario: Metrics carry no note names

- **WHEN** the metrics endpoint is read after notes were indexed
- **THEN** no metric tag value equals a note path or title

### Requirement: Indexing and sync health are proven end to end against a fake vault

The repository SHALL hold a deterministic end-to-end spec in `apps/ascend-agent/e2e/testing/` that needs no chat model and no Obsidian account. It SHALL seed a fake vault and a sync status file into the `obsidian-vaults` volume and prove, through the connector API, the document registry, Qdrant points and Prometheus samples, the connector refusals, indexing with the front matter and wiki link rules, the excluded files, a watcher run after an edit without a sync call, rename and delete, the `obsidian.sync.up` gauge for `connected` and `down`, and that deleting the connector leaves every vault file byte-identical. Real sync with the Obsidian service SHALL be proven only by an account-gated spec that runs on the server host with the owner's separate test vault, whose names are owner facts.

#### Scenario: Edit reaches the index without a sync call

- **WHEN** the spec changes the canary sentence of `Home/Boiler.md` in the volume and calls no sync endpoint
- **THEN** a Qdrant scroll filtered by the connector id finds the new sentence and not the old one within the watcher's maximum delay plus one run

#### Scenario: Connector delete proven harmless to the vault

- **WHEN** the spec deletes the connector
- **THEN** every fixture file has the SHA-256 recorded in Reset and no chunk of the connector is left
