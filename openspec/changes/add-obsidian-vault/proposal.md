## Build order

Build order (owner build order of 2026-10-04, which supersedes the earlier orders): build group 4 (personal), position 9. It needs `close-agent-test-gaps` (the shared scripted e2e harness), `upgrade-spring-boot-4` (Flyway, Spring AI 2 and the RFC 7807 problem detail of its D19), `add-keycloak-login` (the authorization matrix, the e2e users and `TenantContext.currentTenantId()`), `add-deployment-modules` (the module `obsidian`, `ASCEND_MODULES`, `@ConditionalOnModule` and `AuditEventPort` of its company extension ports), `add-shared-scheduler` (the system task that runs the full rescan), `add-document-management-api` (the document registry, `IngestionRunService` and the single-document deletion path), `add-agent-skills` (`ChatToolset`, `AgentNativeTool` and `app.agent-home`), `add-action-approvals` (the approval service and the kind `obsidian_note_write`), `add-mcp-tool-servers` (the e2e overlay entries its specs run with) and `add-connector-framework` (the connector framework, split out of `add-document-connectors` on 2026-10-04), which all land earlier. Nothing here needs an edit of `add-mcp-tool-servers`, because the note tools are agent native tools. It depends on no company change: `add-tenant-isolation`, `add-tenant-policy` and `add-audit-and-gdpr-compliance` (company, build group 5) register their parts later, and this change does not wait for them.

This change does not edit any other change. The edits it needs are listed in design.md under "Required edits to other changes". Every one of them is made in its target change (checked on 2026-10-03), including the catalog entry `obsidian` of `add-deployment-modules` with no `requires` entry, because `rag` is always on (owner decision of 2026-10-03). A task that uses an edit of a change that lands earlier uses it as it is.

## Why

The owner keeps his notes in Obsidian and pays for Obsidian Sync (owner, 2026-10-02). He wants the assistant to read and write that vault in real time: find what he wrote, read a note, add a note, and append to a note or to today's daily note, with every change showing up on his phone and desktop through Obsidian Sync. Today the agent has no way to reach the vault. The only alternative found, AnythingLLM's Obsidian import, copies the vault once and never again, so it goes stale the next day.

Obsidian now publishes an official headless client, the npm package `obsidian-headless` (command `ob`), which keeps a vault synced on Linux without the desktop app. That makes a live, two-way vault copy inside the stack possible for the first time.

## What Changes

- A new container, `obsidian-sync`, built from our own image with a pinned `obsidian-headless` version, runs `ob sync --continuous` into a named volume. Secrets come only from the environment (`OBSIDIAN_AUTH_TOKEN`). The one-time login, the one-time vault setup (including the end-to-end encryption password) and the token renewal are documented with exact commands. A health check reports whether the client is really connected, and a status file on the shared volume tells the agent when sync is down, for example after the token expired.
- Obsidian becomes a new connector type, `OBSIDIAN`, on the `add-connector-framework` framework. A file watcher on the vault folder turns every added, changed and deleted note into a connector run that lands the note's bytes in object storage and starts the existing ingestion path, and a deleted note has its stored object and its chunks removed through the single-document deletion path. There is no parallel parse path and no write to Qdrant from the connector. A full rescan every 15 minutes, run as the system task `obsidian-vault-rescan` of `add-shared-scheduler`, catches anything the watcher missed. The file watcher stays local to the agent instance.
- Fixed exclusions: the Obsidian config folder (`.obsidian` or the configured name), `.trash`, every file or folder whose name starts with a dot, Obsidian Sync conflict copies, and every file that is not a Markdown note unless attachments are switched on per vault. Each vault can add its own excluded folders.
- The markdown parser learns two things every Markdown document benefits from: YAML front matter is read as metadata (title, aliases, tags) and is no longer indexed as text, and wiki links (`[[Note]]`, `[[Note|alias]]`, `[[Note#Heading]]`, embeds `![[...]]`) are rendered as readable text instead of raw brackets.
- Five agent tools, each an `AgentNativeTool` bean: `obsidian_search_notes` (RAG search narrowed to one vault), `obsidian_read_note`, `obsidian_create_note`, `obsidian_append_note` and `obsidian_daily_note`. The agent never deletes, renames or replaces a note.
- Writes go into a configurable agent folder (default `AscendAI/`) by default. A write outside it is submitted to the approval service of `add-action-approvals` as the kind `obsidian_note_write` and runs only after the owner approves it. Appending to today's daily note skips approval (owner decision of 2026-10-02, a per vault setting that can switch it off, see design D14).
- The note tools are offered to every user of the tenant, limited to the tools that `TenantToolPolicy` of `add-agent-skills` (its D16) allows, like every other tool. Its default denies only the tools listed in `app.tool-policy.denied-tools` (empty by default). `add-tenant-policy` (company, build group 5) registers its implementation later. The tools are not limited to administrators for now (owner decision of 2026-10-02).
- The sync container runs only on the server host, never on the owner's development PC, where Obsidian desktop with Sync already runs. Development and tests use a separate test vault (owner decision of 2026-10-02).
- Conflict avoidance: the sync client runs with the `merge` conflict strategy, the agent writes through a temporary file and an atomic rename with a check that the note did not change since it was read, and it refuses to write a note the owner edited in the last few seconds. So the agent's writes do not produce Obsidian conflict copies in normal use.
- Limits on note size for indexing, for reading and for writing, on the number of files per vault and on writes per chat request.
- Tenant scoping: each vault folder sits under its tenant's folder, a connector can only point at a vault of its own tenant, and every tool acts only on the vaults of the caller's tenant.
- Metrics, logs and audit events for sync health, watcher activity, tool calls and writes, with note paths and contents kept out of INFO logs and metric tags. Audit events go through `AuditEventPort` of `add-deployment-modules`, whose default writes one structured INFO log line, and `add-audit-and-gdpr-compliance` (company, build group 5) registers its implementation later.
- Tests with a fake vault folder for the watcher, the connector, the parser and the tools, Testcontainers tests of the whole path, a container test of the sync image that also proves the sync container's refusals, and four new e2e specs (design D21): two deterministic Bruno specs with no AI model (the connector against a fake vault, and the note tools through the scripted model of the shared harness of `close-agent-test-gaps`, which starts only for deterministic tests and never for AI-run specs (owner answer 70.4 of 2026-10-04)), one AI-run spec of a chat over the fake vault, and one account-gated spec of real sync with the owner's separate test vault on the server host.
- The licence risk is stated and contained: `obsidian-headless` is proprietary (`UNLICENSED`) and in open beta, so the image is built locally and never pushed to any registry, the feature is the deployment module `obsidian`, off unless `obsidian` is in `COMPOSE_PROFILES` in `.env`, and the rest of the platform never depends on it.

The project is under development, so there is no data migration or backfill. Owner answer 73.1 of 2026-10-06 confirms that the data in today's development stores is disposable.

## Capabilities

### New Capabilities

- `obsidian-vault-sync`: the `obsidian-sync` container: image, pinned client version, secrets from the environment, one-time login and setup, sync settings, volumes and file ownership, health check, sync status file, token expiry and renewal, and the rule that the image is never published.
- `obsidian-vault-connector`: the `OBSIDIAN` connector type: vault location and tenant jail, configuration, the file watcher and the full rescan, exclusions, landing notes through the existing pipeline, deletion propagation, document registry and chunk metadata used by the vault filter, sync health surfaced on the connector, metrics and logs.
- `obsidian-note-tools`: the five agent tools: when they are offered, path rules, search with a vault filter, reading, creating and appending, the daily note, the agent folder, approval for writes outside it, conflict avoidance, size limits, tenant scoping, audit, metrics and logs.
- `markdown-front-matter-and-wiki-links`: how the Markdown ingestion path treats YAML front matter and Obsidian wiki links for every Markdown document, whatever its source.

### Modified Capabilities

(none. No archived spec describes how the Markdown parser renders text, so the front matter and wiki link rules are a new capability. The connector framework, the document registry, the tool policy, the approval service, the RAG filter and the audit store are capabilities of changes that are not archived yet, so what this change needs from them is listed as required edits in design.md and not as delta specs here.)

## Impact

- New container: `infra/obsidian-sync/` (Dockerfile, entrypoint script, health check script, `package.json` and `package-lock.json` pinning `obsidian-headless` 0.0.14 with its integrity hash), a new `obsidian-sync` service in `compose.yaml` under the profile `obsidian`, which is the module `obsidian` of `add-deployment-modules` and is switched on only through `COMPOSE_PROFILES` in `.env`, two named volumes (`obsidian-vaults` for the vault files, `obsidian-sync-state` for the client's own state and the derived encryption key), and `OBSIDIAN_AUTH_TOKEN` in `.env.example`.
- New code in ascend-agent: `service/connector/obsidian/` (the connector, the vault watcher, the rescan system task, the vault path jail, the sync status reader, the daily note resolver), `service/obsidian/` (the note tools, the note writer, the approval handler for `obsidian_note_write`), `config/properties/ObsidianProperties`, a front matter and wiki link extension in the Markdown path of `service/ingestion/IngestionService.java`, and one Flyway migration `V<n>__obsidian_vault.sql` for the per-vault file manifest.
- Changed files in ascend-agent: `build.gradle.kts` and `gradle/libs.versions.toml` gain `org.commonmark:commonmark-ext-yaml-front-matter` at the same version as `commonmark` (0.28.0), the `Dockerfile` gives the `app` user the shared group of the vault volume, `application.yaml` gains the `app.obsidian` block, `StartupLogConfig` reports the vaults, and `service/rag/RagRetrievalService.java` gains an optional narrowing filter for one search (design D10).
- Dependencies: `obsidian-headless` 0.0.14 (proprietary, open beta, Node.js 22 or later) inside the sync image only, `commonmark-ext-yaml-front-matter` 0.28.0 (BSD 2-Clause, the same licence as `commonmark`) in the agent.
- External: outbound HTTPS from the sync container to Obsidian Sync. An Obsidian account with an active Sync subscription.
- Docs: new `docs/OBSIDIAN.md` (setup, login, renewal, privacy, licence), sections in `docs/CONNECTORS.md` and `docs/OBSERVABILITY.md`, root `AGENTS.md` and `apps/ascend-agent/AGENTS.md`, `apps/ascend-agent/docs/CONFIGURATION.md`, a decision record in `apps/ascend-agent/docs/architecture/decisions/`, Bruno requests and five new e2e specs in `apps/ascend-agent/e2e/`, listed in `docs/E2E_RUN_SCENARIOS.md`.
- Module switch: the agent reads `ASCEND_MODULES` of `add-deployment-modules`. The five tools, the watcher, the rescan system task, the sync status reader and the `OBSIDIAN` connector type carry `@ConditionalOnModule("obsidian")`. The module requires no other module, because the document search it builds on is part of the always on core (owner decision of 2026-10-03). This change adds no `app.obsidian.enabled` flag of its own.
- Backwards compatibility: with the module `obsidian` off, or with no Obsidian connector configured, the agent behaves as before, except that Markdown documents with front matter or wiki links are indexed with cleaner text.

## Relevant Skills

Load these from `.agents/skills/` before implementing this change:

- `springboot-patterns` and `java-coding-standards` for the connector, the watcher, the tools, configuration properties and the tests
- `docker-patterns` for the sync image, its non-root user, the pinned base image, the volumes and the health check
- `bash` for the entrypoint and health check scripts
- `security-review` for the vault path jail, symlinks, the approval path, prompt injection through note content and token handling
- `backend-patterns` for debouncing, the rescan, at most once writes and the compare-and-swap write
- `database-migrations` and `postgres-patterns` for the Flyway migration of the file manifest
- `observability-and-logging` for the metrics, the log lines and the startup banner
- `tdd-workflow` for writing each rule's test first
- `api-design` for the connector configuration fields exposed through `/api/v1/connectors`
- `architecture-decision-records` for the decision record
- `e2e-runbooks` for the new e2e spec
- `markdown-writer` for `docs/OBSIDIAN.md` and the other documentation
- `obsidian` for how Obsidian lays out a vault, daily notes and links
