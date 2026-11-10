## Context

See proposal.md for why. This section holds only the facts the decisions rest on.

### The headless client, checked on 2026-10-02

Sources: https://obsidian.md/help/sync/headless, the npm registry entry https://registry.npmjs.org/obsidian-headless, and the published package `obsidian-headless-0.0.14.tgz` (its `README.md` and `cli.js`), read in full where a decision depends on it.

- Package `obsidian-headless`, command `ob` (`"bin": {"ob": "cli.js"}`), latest and only dist-tag `0.0.14`, published 2026-07-30T15:23:42Z. Fourteen versions since 2026-02-27. `"license": "UNLICENSED"`. `"engines": {"node": ">=22.0.0"}`. Two dependencies: `better-sqlite3` 12.11.1 (a native module) and `commander` 14.0.3. The help page calls it open beta.
- Commands in 0.0.14: `login`, `logout`, `sync-list-remote`, `sync-list-local`, `sync-create-remote`, `sync-setup`, `sync-config`, `sync-status`, `sync-unlink`, `sync`, and the `publish*` family.
- `ob login [--email] [--password] [--mfa]` prompts for what is missing and asks for the two-factor code when the account has it. The token is written to `auth_token` in the client's config folder with mode 0600 (folder mode 0700). The config folder is `$XDG_CONFIG_HOME/obsidian-headless` on Linux, `~/.config/obsidian-headless` when that variable is unset. The client reads `OBSIDIAN_AUTH_TOKEN` from the environment before the file (`cli.js`, function that returns `process.env.OBSIDIAN_AUTH_TOKEN` first). The README and the help page do not mention the variable.
- `ob sync-setup --vault <id or name> [--path] [--password <e2e password>] [--device-name] [--config-dir]` prompts for the end-to-end encryption password when it is omitted. It stores the vault settings and the derived key in `<config folder>/sync/<vaultId>/config.json` (mode 0600), with `state.db` and `sync.log` beside it.
- `ob sync-config` options: `--mode bidirectional|pull-only|mirror-remote` (default `bidirectional`), `--conflict-strategy merge|conflict`, `--file-types` (image, audio, video, pdf, unsupported, empty to clear), `--configs` (app, appearance, appearance-data, hotkey, core-plugin, core-plugin-data, community-plugin, community-plugin-data, empty to disable), `--excluded-folders`, `--device-name`, `--config-dir`.
- `ob sync --path <p> --continuous` takes a lock file `<vault>/<config dir>/.sync.lock` and refuses to start when another instance holds it ("Another sync instance is already running for this vault.").
- Files the client syncs: `.md`, `.canvas` and `.base` always, attachments by `--file-types`, files in the config folder by `--configs`. Any path with a segment that starts with a dot is skipped.
- Conflicts on a Markdown file: with `merge` the client merges the remote change into the local file ("Merging conflicted file", "Merge successful", "Merge failed."). With `conflict` it writes a copy named `<name> (Conflicted copy <device> <time>).md`. A clash between a file and a folder of the same name renames the file to `<name> (Conflicted copy).md` in both modes.
- Connection failures: the client logs the error, backs off and retries, and the process keeps running. Only two server answers stop it: "Your subscription to Obsidian Sync has expired" and "Vault not found". An invalid or expired token therefore shows as a client that is running and never connects. The token lifetime is not documented anywhere we could find.
- The help page warns: "Do not use both the desktop app Sync and Headless Sync on the same device." It does not say why.
- No official Docker image exists. The account page offers no API key, so the login session token is the only credential.

### The agent today and after its planned changes

- Markdown is parsed in `service/ingestion/IngestionService.processMarkdown`: CommonMark 0.28.0 renders plain text and `TitleExtractionVisitor` takes the first heading as the title, otherwise the file name. YAML front matter is not recognised: its closing `---` turns the last property line into a setext heading, so a note with front matter gets a property line as its title and its YAML indexed as text. Wiki links are indexed with their brackets.
- `add-connector-framework` D1 (the framework split out of `add-document-connectors` on 2026-10-04): a connector lands bytes in object storage under the tenant prefix, starts a bucket-scan run through `IngestionRunService`, waits for it, and records per-file outcomes. It never parses and never writes to the vector store. Deletions go through the single-document deletion path of `add-document-management-api`. The framework has a scheduler, a manual trigger that answers 409 while a run is in progress, a freshness check, and run triggers `SCHEDULED`, `MANUAL`, `EVENT` (a connector that notices a change itself, its D22) and `FRESHNESS_CHECK`.
- `add-document-management-api` keeps a `documents` registry with an open string `source_type` (`upload`, `bucket-scan`, later `connector:<name>`) and a nullable `origin_uri`, and routes every scanned object through `DocumentRouter`.
- `RagRetrievalService` (`service/rag/RagRetrievalService.java`) is today the one retrieval path: `retrieve(query, embeddingProvider)` builds a `SearchRequest` with no filter expression and calls `similaritySearch` (checked in the source on 2026-10-05). This change adds an optional narrowing filter to it (D10). `add-tenant-isolation` (company, build group 5) later stamps `tenant_id` and the access list on every chunk, moves the search into `TenantFilteredVectorSearch.search` with the mandatory tenant and access list filter, and keeps the narrowing filter joined with AND (its decision 4). This change does not wait for it.
- `add-agent-skills` D3: every agent tool is an `AgentNativeTool` bean, collected with the MCP tools once per request by `ChatToolset`. The tool context carries `user_id`, `request_id`, `tenant_id` and `embedding_provider`. `TenantContext.currentTenantId()` of `add-keycloak-login` (its D3) returns the tenant, `default` in the personal deployment. `add-tenant-policy` (company, build group 5) adds a tenant tool allow-list filter in `ChatToolset` later.
- `add-action-approvals` D3: any component can submit an `ApprovalAction` of a kind that has an `ApprovalActionHandler` bean, and gets back a decision by rule or a pending approval id. The handler declares category, whether an allow may be remembered, the scope, the preview, and what execute, deny and expire do.
- The agent image runs as the `app` user created with `adduser -S`, so its user id is not fixed.
- `add-deployment-modules`: the operator lists modules once, in `COMPOSE_PROFILES` in the root `.env`. Compose starts the services of those profiles, and the agent reads the same list as `ASCEND_MODULES`. Agent beans carry `@ConditionalOnModule`. Its catalog reserves the module `obsidian` for this change, with the service `obsidian-sync`. The module entry `obsidian` joins the `personal` preset. By the owner decision of 2026-10-03, core chat, monitoring, `rag`, memory, the sandbox and the prerequisites are always on and are never switchable modules, so the document search the connector needs is always present and `obsidian` requires no other module. Nobody passes `--profile` on the command line.
- `add-shared-scheduler`: every periodic job of the agent is a system task on db-scheduler, with a name in `SchedulerTaskName`, a five-field cron and zone from `app.scheduler.system-tasks.<name>.cron` and `.time-zone`, run by exactly one agent instance per firing. A system task that belongs to a module is registered only when its module is active.

## Goals / Non-Goals

Goals:

- A live, two-way copy of the owner's vault inside the stack, kept current by the official client, with a visible signal when it stops being current.
- Notes indexed through the existing pipeline within seconds of a change, and removed when deleted.
- Five note tools that let the agent find, read, create and append, writing into its own folder freely and outside it only with the owner's approval.
- No Obsidian conflict copies caused by the agent in normal use, and no silent loss of the owner's edits.

Non-Goals:

- Deleting, renaming, moving or replacing a note from the agent. Not asked for, and each is a way to lose the owner's work.
- Writing to `.canvas` or `.base` files, attachments, or the config folder.
- Obsidian Publish, and any use of the `publish*` commands.
- Following links: the tools do not expand embeds or walk the link graph. The model can call `obsidian_read_note` on a linked note itself.
- Running community plugins or Templater syntax. Only the core Templates placeholders are filled in.
- Per-note access control inside a tenant (see D16).
- A REST API of its own. Configuration goes through `/api/v1/connectors` of `add-connector-framework`, decisions through `/api/v1/approvals` of `add-action-approvals`.

## Decisions

### D1: Our own sync image, one container per vault

`infra/obsidian-sync/Dockerfile`:

- Base `node:22-bookworm-slim`, pinned by digest. Debian, not Alpine, because `better-sqlite3` ships prebuilt glibc binaries and an Alpine build would need a compiler toolchain in the image.
- `package.json` and `package-lock.json` pin `obsidian-headless` to exactly `0.0.14`, and the build runs `npm ci --omit=dev`, so the lock file's integrity hash is checked. The version is raised only by a deliberate change that reruns the container test (task 2.6).
- A fixed user and group, `obsidian` with uid and gid 10001, created before `USER obsidian`. The vault and state folders are created owned by that user so a new named volume takes that ownership.
- `XDG_CONFIG_HOME=/state`, so the client keeps its folder at `/state/obsidian-headless` on the state volume.
- `umask 0002` and the setgid bit on the vault folder, so files the client creates are writable by the group 10001, which the agent's `app` user joins (D6).
- The entrypoint script `obsidian-sync` (POSIX shell, `set -eu`) takes one subcommand:
  - `run` (default): refuses to start without `OBSIDIAN_AUTH_TOKEN` or without a vault set up at the configured path (exit 3 with a message naming the missing piece and `docs/OBSIDIAN.md`), applies the settings of D2 with `ob sync-config`, then `exec ob sync --path <vault path> --continuous`.
  - `login`: runs `ob login` with `XDG_CONFIG_HOME` pointed at a folder inside the container that is not a volume, prints the token once with the instruction to put it in `.env`, and exits. Nothing is written to a volume, and the container is removed by `--rm`.
  - `list-remote`: `ob sync-list-remote`.
  - `setup <vault name or id>`: creates the vault folder and runs `ob sync-setup --vault <...> --path <vault path> --device-name <device name>`, which prompts for the end-to-end encryption password when the vault has one.
  - `status`: `ob sync-status --path <vault path>`.
- The health check script of D3.
- No secret in the image, the build arguments or the compose file. The token comes from `.env` through `OBSIDIAN_AUTH_TOKEN`. The non-secret settings (tenant, vault name, device name, excluded folders, connect grace) are written `${VAR:-default}` in `compose.yaml` with the same default in the entrypoint and health check scripts (owner rule 98 of 2026-10-08), and are not `.env.example` entries.

One container syncs exactly one vault, because `ob sync` takes one `--path`. A second vault is a second service entry with its own tenant and vault name. The owner has one vault today.

Alternatives considered: running `ob` inside the agent image (rejected: it would put Node.js and a proprietary package into the agent image, and a crash of either would take the other down), a third-party image (rejected: none is official, and the owner's credentials would pass through someone else's code), and the desktop app under a virtual display (rejected: heavier and still a second device).

### D2: Sync settings enforced on every start

`run` applies these with `ob sync-config` before syncing, so a hand edit inside the state volume cannot drift:

| Setting | Value | Why |
| :--- | :--- | :--- |
| `--mode` | `bidirectional` | The agent writes notes |
| `--conflict-strategy` | `merge` | A concurrent edit becomes a merged note, not a conflict copy (D12) |
| `--file-types` | empty, or `image,pdf` when attachments are on for the vault | Notes only by default. Nothing downloaded that the agent does not use |
| `--configs` | `core-plugin,core-plugin-data` | Brings `daily-notes.json` and `templates.json` (D13) and nothing that holds plugin code |
| `--excluded-folders` | `OBSIDIAN_EXCLUDED_FOLDERS` from `compose.yaml`, default empty | A folder excluded here is never downloaded, which is the strongest privacy control the owner has |
| `--device-name` | `OBSIDIAN_DEVICE_NAME`, default `ascend-agent` | The owner sees the agent's edits under this name in Obsidian's version history |

### D3: Health check and the sync status file

The client prints no machine-readable state, so the health check reads the newest connection line of `sync.log` in the vault's state folder. The client's messages are known from `cli.js` ("Connecting...", "Connection successful. Detecting changes...", "Fully synced", "Waiting to connect to server", "Disconnected from server"). The exact line format of `sync.log` is measured on the real client before the parser is written (task 2.3), and a recorded log excerpt becomes the test fixture.

The check is healthy when the `ob` process is running and the newest connection line says connected, or it says not connected and is younger than `OBSIDIAN_CONNECT_GRACE_SECONDS` (default 300, so a short network drop or a restart is not a failure). It writes the result atomically (temporary file, then rename) to `status/sync-status.json` on the vault volume: `{ "state": "connected" | "connecting" | "down", "since": <ISO time>, "lastConnectedAt": <ISO time or null>, "checkedAt": <ISO time>, "clientVersion": "0.0.14" }`. Compose runs it every `OBSIDIAN_SYNC_HEALTHCHECK_INTERVAL` (default 30 seconds, owner rule 98 of 2026-10-08).

The agent reads that file (D15). An expired token, a revoked session or an expired subscription all end as `down` after the grace period, because the client either keeps retrying without connecting or exits.

### D4: Login once, renew when the token stops working

Every command runs from the repository root against the main compose file. The commands are the same in PowerShell and in a Unix shell.

One-time login. Prompts for e-mail, password and the two-factor code, and prints the token:

```bash
docker compose run --rm --no-deps obsidian-sync login
```

Put the printed token into `.env` as `OBSIDIAN_AUTH_TOKEN`. Then list the vaults the account can reach:

```bash
docker compose run --rm --no-deps obsidian-sync list-remote
```

Set the vault up once. It prompts for the end-to-end encryption password when the vault has one, and stores only the derived key, in the state volume:

```bash
docker compose run --rm --no-deps obsidian-sync setup "My Vault"
```

Switch the module on by adding `obsidian` to the list in `COMPOSE_PROFILES` in the root `.env` (for example `COMPOSE_PROFILES=web-search,obsidian`), the one switch `add-deployment-modules` defines. Compose then starts the service and the agent receives the same list as `ASCEND_MODULES`. Then start it, together with the agent so the agent picks up the new module list:

```bash
docker compose up -d
```

When the token stops working (the status turns `down` and `docker compose logs obsidian-sync` shows the client retrying), run the login command again, replace `OBSIDIAN_AUTH_TOKEN` in `.env`, and recreate the container so it reads the new value:

```bash
docker compose up -d --force-recreate obsidian-sync
```

`docker compose run` of a service under a profile starts it even while the profile is off, so the login, listing and setup commands above work before the module is switched on.

The vault setup and its encryption key stay in the state volume, so renewal never asks for the encryption password again. Never run `ob logout` with the token in use: whether logout revokes the session on the server is not documented, so it is treated as if it does.

Why a token in `.env` and not the `auth_token` file: the owner's rule is that secrets come from the environment, and the client reads the variable first, so the file is never needed. Why the derived key in a volume is still acceptable: it is not a secret the owner types into configuration but state the client creates, the client writes it with mode 0600, and the volume is reachable only by the sync container and the host's Docker administrator. The agent container never mounts the state volume.

### D5: Licence and beta risk are contained, not ignored

`obsidian-headless` is proprietary (`UNLICENSED`) and in open beta. Obsidian publishes it for exactly this use, so using it on the owner's machine with his own subscription is what it is for. Redistributing it is not covered by anything we have, so:

- The image is built locally from `infra/obsidian-sync/` and tagged `ascend-ai-obsidian-sync:local`. It is never pushed to any registry, never built by a CI workflow, and never included in a release or in `add-customer-stack-installer`'s published artifacts. A customer who wants it builds it on their machine with their own Obsidian account.
- The service is under the profile `obsidian`, which is the module `obsidian` of `add-deployment-modules`. While `obsidian` is not in `COMPOSE_PROFILES` in `.env`, `docker compose up` never builds or starts it, and the agent registers none of this change's beans.
- It runs only on the server host (owner decision of 2026-10-02), never on the owner's development PC, where Obsidian desktop with Sync already runs, because Obsidian warns against both on one device. Development and tests never use the owner's real vault: the automated tests and the e2e spec use a fake vault folder, and a live sync check during development uses a separate test vault in the owner's account, synced by a sync container on the server host with its own tenant folder and device name.
- The version is pinned (D1). A new beta release is adopted only after the container test passes on it, because a beta can change its log lines, its options or its protocol.
- Nothing else in the platform depends on the sync container. If Obsidian withdraws or breaks the client, the vault copy stops updating, the connector reports the sync as down (D15), and every other feature keeps working.

The decision record for this change records the licence position and the trigger to revisit it: a licence change of the package, an official Docker image, or Obsidian publishing terms for headless use.

### D6: One named volume shared by two containers, laid out per tenant

The volume `obsidian-vaults` is mounted at `/vaults` in `obsidian-sync` and at `/app/vaults` in `ascend-agent` (read and write in both). Layout:

```text
tenants/<tenantId>/<vaultName>/vault/     the notes, the folder ob syncs
tenants/<tenantId>/<vaultName>/tmp/       the agent's temporary files for atomic writes (D11)
tenants/<tenantId>/<vaultName>/status/    sync-status.json written by the health check (D3)
```

`tmp/` sits on the same file system as `vault/`, so a rename from one to the other is atomic, and it is outside the folder the client syncs, so a temporary file is never uploaded. The agent's `Dockerfile` adds `app` to a group with gid 10001, so the agent can write the files the client creates, and the client can write the files the agent creates.

The vault must be a named volume, never a bind mount of a folder on the host. On Docker Desktop for Windows a bind-mounted Windows folder does not deliver file change events to Linux containers reliably, and a bind mount of the owner's own desktop vault would put two Sync clients on one folder, which is what Obsidian warns against.

### D7: `OBSIDIAN` connector type on the framework

`ObsidianConnector` implements `DocumentConnector` of `add-connector-framework` (the enum value and the points of D7 to D9 are made there, its D3, D21 and D22). Its source scope (the framework's JSONB column), validated by the connector at write time:

| Field | Default | Rule |
| :--- | :--- | :--- |
| `vaultName` | required | `[a-z0-9-]{1,64}`. The vault folder is resolved by the server (below), never given as a path |
| `agentFolder` | `AscendAI` | A relative folder path, validated by the path rules of D10 |
| `excludedFolders` | `[]` | Relative folder paths, added to the fixed exclusions |
| `includeAttachments` | `false` | When true, `pdf` and image files in the upload allowlist are indexed too |
| `dailyNoteAppendWithoutApproval` | `true` | See D14 |

Vault location jail. The vault folder is `<app.obsidian.vaults-root>/tenants/<tenantId>/<vaultName>/vault`, where the tenant is the connector's own tenant. A create or update is refused with HTTP 400 when that folder does not exist, when its real path (symbolic links resolved) is not under the tenant's folder, or when another connector already uses the same vault. So a tenant administrator can never point a connector at another tenant's vault, at the agent home, or at any other folder of the container. The same real path check runs before every file read and write (D10).

The connector needs no credential. The Obsidian token belongs to the sync container, so the connector row's credentials reference is empty, which the framework allows for a type that declares it needs none (made there, its D21).

The full rescan of D8 is not a per connector cron. It is the system task `obsidian-vault-rescan` of `add-shared-scheduler`, registered by this change under that change's contract: its name in `SchedulerTaskName`, the five-field cron `app.scheduler.system-tasks.obsidian-vault-rescan.cron` (default `*/15 * * * *`) and the zone `.time-zone` (default `Europe/Warsaw`, the same as `app.obsidian.zone`). It carries `@ConditionalOnModule("obsidian")`, so it is registered only when the module is active. Each firing, run by exactly one agent instance, starts one rescan run with trigger `SCHEDULED` for every enabled `OBSIDIAN` connector, through the framework's run path, so the dirty follow-up rule of D8 keeps runs of one connector from overlapping. A tenant without the module grant is skipped with the reason `module_denied`, the rule `add-deployment-modules` sets for work that starts without a request. Running a firing twice is harmless, because a rescan with no change lands nothing.

An `OBSIDIAN` connector therefore has no cron of its own. The connector type declares that its schedule comes from a system task, so the framework creates no per connector sync execution for it and refuses a cron in its create or update (made in `add-connector-framework`, its D21). Its maximum sync age follows the framework's rule, measured against the shortest gap of the system task's cron.

### D8: The watcher starts runs, the rescan makes them complete

`ObsidianVaultWatcher` watches every folder of each enabled vault with Java's `WatchService` (inotify on Linux), registering new folders as they appear, and skipping excluded and dot folders.

- Events are debounced per vault: a run starts when no event arrived for `app.obsidian.watcher.quiet-period` (default 3 seconds), or at the latest `app.obsidian.watcher.max-delay` (default 30 seconds) after the first event of a burst. Obsidian saves while the owner types, and Sync writes a file in steps, so a run per event would index half-written notes and waste embeddings.
- A run started by the watcher has the trigger `EVENT` (made in the framework, its D22). While a run of the connector is in progress, a further `EVENT` trigger does not answer 409 as the manual trigger does. It marks the connector dirty, and one more run starts when the current one ends, so no change is lost and runs never overlap (made there, its D22).
- An inotify overflow, a watcher error, and the start of the agent all start a full rescan run, on the instance that saw them. The watcher and these rescans stay local, because inotify events reach only the instance that watches the folder. With several agent instances every instance watches the shared volume and may start an `EVENT` run for the same change, and the framework's one run per connector rule, a Postgres session advisory lock that every instance sees (`add-connector-framework` D2 and D22, answer 87), turns those starts into one run plus at most one follow-up run, so two instances never index one connector at once. The rescan every 15 minutes is the system task of D7 and runs the same full rescan.
- Every run, whatever started it, computes the change set the same way: it walks the vault and compares each eligible file with the connector's file manifest (D9). A file whose size and modification time are unchanged is not read. A file whose bytes hash differently is changed. A manifest entry with no file is deleted. A rename is a delete and an add. The watcher's events say when to look, never what changed, so a missed event can delay a change until the next rescan but cannot lose it.

Eligible file: ends in `.md` (or is an allowlisted attachment when `includeAttachments` is on), is at most `app.obsidian.max-note-bytes` (default 2 MiB, larger files are recorded `SKIPPED` with reason `too_large`), and is not excluded. Fixed exclusions, which configuration cannot turn off: the vault's config folder (`.obsidian` or the name in the sync settings), `.trash`, every path with a segment that starts with a dot, every file whose name contains ` (Conflicted copy`, and every `.canvas` and `.base` file. Also excluded by default: the folder named in `.obsidian/templates.json`, because template text with placeholders is noise in search. At most `app.obsidian.max-files` (default 20,000) eligible files per vault are indexed, in path order, and the rest are recorded `SKIPPED` with reason `vault_file_limit`.

Alternatives considered: indexing straight from the watcher event (rejected: events are lossy, duplicated and out of order, and it would be a second ingestion path), polling only (rejected: the owner asked for real time), and a watcher inside the sync container posting to the agent (rejected: a second component to secure for no gain, since both containers share the volume).

### D9: Landing, registry and chunk metadata

- The manifest table `obsidian_vault_file` (Flyway `V<n>__obsidian_vault.sql`): tenant id (`tenant_id VARCHAR(64) NOT NULL`, the connector's tenant, written from `TenantContext.currentTenantId()` inside the run's `TenantContext.runAs`, no foreign key), connector id (FK, cascade delete), relative path (the real one, Unicode, case kept), content SHA-256, size, modification time, object key, landed at. Unique on (connector id, relative path). Every query filters on the tenant id as well as on the connector id.
- Foreign keys: this change's own migration adds the foreign key from the connector id to the `connector` table of `add-connector-framework` with `ON DELETE CASCADE`, every constraint named. The `tenant_id` column carries no foreign key here. `add-tenant-isolation` (company, build group 5) creates the `tenants` table later and adds the foreign key from `obsidian_vault_file.tenant_id` to `tenants(id)` in its own migration. This change does not wait for it.
- Object key: `<tenant prefix>markdown/obsidian/<connectorId>/<first 16 hex digits of SHA-256 of the relative path>-<sanitized file name>` (attachments under `documents/` instead of `markdown/`). The tenant prefix comes from `TenantPrefixResolver` of `add-connector-framework` (its D25), empty in the personal deployment, and `tenant/<tenantId>/` once `add-tenant-isolation` (company) registers its implementation. The connector supplies only the part below the folder. The existing sanitizer keeps only `[A-Za-z0-9._-]`, so `Zażółć.md` and `Za_.md` would collide. The hash of the real path makes every key unique, and the sanitized name keeps the key readable. This needs the framework to accept a key segment chosen by the connector (made there, its D1 and D21).
- The connector hands the framework, per landed file: `source_type` `connector:obsidian`, `origin_uri` `obsidian://<vaultName>/<URL-encoded relative path>` and its connector id, which the framework writes to the document registry (made in `add-connector-framework`, its D21, which since owner answer 93 of 2026-10-08 also owns the column `documents.connector_id`, and in `add-document-management-api`, its D12, for `source_type` and `origin_uri`).
- The ingestion run copies `source_type` and `connector_id` from the registry row onto every chunk, and both get a keyword payload index (`source_type` made in `add-document-management-api`, its D12, and `connector_id` with its chunk field and payload index made in `add-connector-framework`, its D21, moved there by owner answer 93 of 2026-10-08). `connector_id` is what the vault filter of D10 matches.
- Deleted notes go through the framework's deletion propagation and so through the single-document deletion path, then the manifest row is removed.

### D10: The note tools

Five `AgentNativeTool` beans in `service/obsidian/`, each with `@ConditionalOnModule("obsidian")`, so they do not exist while the module is off. The bean returns its tool callbacks for a request only when the tenant has at least one enabled `OBSIDIAN` connector whose vault folder exists. `ChatToolset` then leaves out every tool that `TenantToolPolicy` of `add-agent-skills` (its D16) does not allow for the tenant, as for every other tool (D16). Each tool takes an optional `vault` argument (a connector display name or vault name), required only when the tenant has more than one vault.

| Tool | Arguments | Result |
| :--- | :--- | :--- |
| `obsidian_search_notes` | `query`, `vault`, `limit` (default 5, at most 20) | For each hit: note path, title, score and a snippet of at most 500 characters |
| `obsidian_read_note` | `note`, `vault` | The note as it is on disk now, its size, modification time and a `version` (SHA-256 of the bytes). Front matter included |
| `obsidian_create_note` | `path`, `content`, `vault` | Created path and `version`, or a pending approval id |
| `obsidian_append_note` | `note`, `text`, `vault` | Path and new `version`, or a pending approval id |
| `obsidian_daily_note` | `action` (`read` or `append`), `text` (for append), `date` (ISO date, default today), `vault` | As read or append, for the daily note of that date |

Search goes through `RagRetrievalService`, the one retrieval path, with one narrowing filter `connector_id == <vault's connector id>`, built through `FilterExpressionBuilder`. This change adds that optional narrowing filter to `RagRetrievalService`: a new overload takes the filter expression and sets it on the `SearchRequest`, and `retrieve(query, embeddingProvider)` keeps its behaviour. The connector id belongs to the request's tenant (the connector row is read for that tenant), so the filter keeps search inside the tenant. `add-tenant-isolation` (company, build group 5) later joins its mandatory tenant and access list filter with AND to the narrowing filter, never replacing it (its decision 4 and `rag-retrieval` spec). This change does not wait for it. The hit's object key is mapped back to the note path through the manifest. A hit whose note was deleted since indexing is left out.

Read takes a path relative to the vault (`.md` added when missing) or a note name resolved the way Obsidian resolves a link: exact path first, then a unique file name match ignoring case. An ambiguous name returns up to 10 candidate paths and no content. A note longer than `app.obsidian.read-max-chars` (default 40,000) is cut there, and the result says it was cut and gives the full size. Read always reads the live file, not the index, so it sees changes the index has not caught up with.

Path rules, for every tool: relative, normalized, no `..` segment, no segment starting with a dot, not under an excluded folder, no character Obsidian forbids in a file name (`* " \ / < > : | ?`) or that breaks a link (`# ^ [ ]`), each segment at most 255 bytes and the whole path at most 1,024 bytes, and the real path after resolving links must stay inside the vault folder. Writes only to `.md` files. A rule break is returned to the model as a refusal naming the rule, never as a failed chat request.

A bare name given to create (no folder) goes into the agent folder, so "make a note called Shopping" does what the owner expects without approval.

### D11: Writing a note without losing the owner's edits

One writer, `NoteWriter`, used by the tools and by the approval handler:

1. Resolve and check the path (D10). Check the size limits (D17).
2. Read the current bytes and their hash. For create, refuse with `note_exists` when the file exists.
3. Recent edit guard: when the file was modified less than `app.obsidian.write.recent-edit-guard` ago (default 10 seconds) and the modification was not the agent's own last write, refuse with `note_busy`, which tells the model the owner is editing it and to try later. A note being typed on another device is the one most likely to receive a remote change while the agent writes.
4. Build the new content. Append adds the text after one line break (two when the note does not end with an empty line), keeping the note's existing line ending style. A note that is not valid UTF-8 is refused with `not_utf8`.
5. Write it to a new file in `tmp/`, flush it to disk.
6. Hash the target again. If it changed since step 2, start over once (append) or refuse with `note_changed` (create, or a second change).
7. Move the temporary file onto the target with an atomic move. Delete the temporary file on any failure.

Writes to one vault are serialised: one in-process lock per vault plus a PostgreSQL advisory lock in the two-key form, whose class key is the value `OBSIDIAN_NOTE_WRITE` that this change adds to the enum `AdvisoryLockClass` of `add-connector-framework` (with the next free class key of that enum at implementation time, never 1, which is `CONNECTOR_RUN`, owner answer 98.10 of 2026-10-08) and whose second key is derived from the connector id, so a second agent instance cannot interleave and a note write never waits on the connector's run lock. The window between step 6 and step 7 is a few milliseconds. A remote change landing exactly in it would be overwritten locally, and Obsidian Sync keeps the overwritten version in the note's version history, where the owner can restore it. That residual risk is stated in `docs/OBSIDIAN.md`.

### D12: Conflict copies

With the `merge` strategy (D2), a change that arrives from another device while the agent's change is waiting to upload is merged by the client, so the agent's own writes do not create conflict copies. Conflict copies can still arrive from the owner's other devices (one of them may use the `conflict` strategy). They are excluded from indexing (D8), counted by the gauge `obsidian.vault.conflict_copies`, and logged at WARN when the count grows, so the owner can clean them up. The agent never touches them.

Alternative considered: `conflict` strategy on the sync container (rejected: every overlap would leave a copy for the owner to merge by hand).

### D13: The daily note

The daily note settings come from `<config folder>/daily-notes.json` (the core Daily notes plugin, synced by D2): `folder`, `format` (a Moment.js date format, default `YYYY-MM-DD`) and `template`. With no file, the defaults apply: the vault root and `YYYY-MM-DD`. The date is taken in the zone `app.obsidian.zone` (default `Europe/Warsaw`).

The format is translated to Java's `DateTimeFormatter` by a small table of the Moment.js tokens (`YYYY`, `YY`, `MM`, `M`, `MMM`, `MMMM`, `DD`, `D`, `ddd`, `dddd`, `Do`, `ww`, `W`, `Q` and bracketed literal text). A format with any other token is refused with `unsupported_daily_note_format` naming the token, rather than writing to a guessed file name. A `/` in the format makes folders, as it does in Obsidian.

Append to a daily note that does not exist creates it first. The content is the template file (the `template` setting) with the core Templates placeholders `{{title}}`, `{{date}}` and `{{time}}` filled in, using the formats in `templates.json` when present, or an empty note.

### D14: Approval for writes outside the agent folder

A create or append whose target is outside the agent folder is not written. It is submitted to `ApprovalService` as the kind `obsidian_note_write`, which `add-action-approvals` registers in its D3 kind table with category `other` and a remembered allow only for `append`. This change provides its handler, `ObsidianNoteWriteApprovalHandler`.

- Payload: connector id, relative path, operation (`create` or `append`), the content or text, and the note's `version` when submitted.
- Preview, built by the server: vault, path, operation, and the text that will be written, cut at the approvals preview limit with the full size stated.
- Execute: `NoteWriter` with the stored values. Create still refuses when the note exists by then. Append appends the approved text to the note as it is at execution time, because appended text stays exactly what the owner approved even if the note changed meanwhile.
- Category `other`. A remembered allow is possible only for `append`, scoped to (connector, path), so the owner can let the agent keep appending to one note. A create is never rememberable, because each create is a new file with new content.
- The tool returns to the model the fixed text of `add-action-approvals`: the write waits for the owner's approval, it has not happened, its approval id, do not repeat it.

Appending to today's daily note skips approval (owner decision of 2026-10-02) while the vault's `dailyNoteAppendWithoutApproval` is true, which is the default. A daily log is the main reason the owner wants write access, an append only adds text at the end, and Obsidian's version history keeps every earlier state. Every other date's daily note follows the normal rule. The owner can switch the exemption off per vault.

### D15: Sync health reaches the agent

`ObsidianSyncStatusReader` reads `status/sync-status.json` of every enabled vault every `app.obsidian.status.read-interval` (default 30 seconds), on a Spring `@Scheduled` method of Spring Boot's auto-configured `TaskScheduler`, never a thread pool of its own. Every agent instance reads the file for itself, because the file is on the shared volume, each instance's gauges and tool result line describe the same file, and a second instance reading it changes nothing (answer 87, CANON 26.1). A missing file, a file older than `app.obsidian.status.max-age` (default 2 minutes), or state `down` mean the vault copy is not being kept current.

- Gauges `obsidian.sync.up` (1 or 0) and `obsidian.sync.last_connected_age_seconds`, tagged with the vault name.
- One WARN line when a vault goes down and one INFO line when it comes back, not one per check.
- While a vault is down, every note tool still works on the local copy, and its result starts with one line saying the vault is not syncing since the given time, so notes may be out of date and writes will not reach the owner's devices until sync is back.
- The framework's freshness check of the connector stays what it is: it measures the agent's own runs. The two signals are different outages (the client cannot reach Obsidian, or the agent stopped indexing), and both are visible.

### D16: Tenant scoping and who can read the vault

- Each vault belongs to one tenant through its folder (D6) and its connector row. Tools act only on the vaults of the request's tenant (`tenant_id` from the tool context, set from `TenantContext.currentTenantId()` of `add-keycloak-login`). A vault of another tenant is answered as not found.
- Search narrows to the connector id of a vault of the request's tenant (D10), so retrieval of a note never crosses tenants. `add-tenant-isolation` (company, build group 5) later stamps the tenant and the access list on every chunk as well.
- Named limitation, the same as `add-document-connectors` D18: a vault's notes are readable by every user of the tenant when `TenantToolPolicy` allows the read tools, and they appear in every user's automatic RAG context in that tenant. A personal vault belongs in a tenant whose members may all read it. The owner's deployment runs as tenant `default` with one user, where this is exactly right. `docs/OBSIDIAN.md` says so in plain words.
- Tool access: this change adds no port of its own (ruling 13.2 of 2026-10-05, one policy port for every tool). The five tools are ordinary agent native tools, so `TenantToolPolicy` of `add-agent-skills` (its D16) decides whether each is offered, applied by `ChatToolset` in its step 2. Its default `ConfiguredTenantToolPolicy` denies only the tools listed in `app.tool-policy.denied-tools` (empty by default), so all five are offered until the owner lists one there. `add-tenant-policy` (company, build group 5) registers its `TenantToolPolicy` implementation later, which reads the tenant's tool allow-list (made there, its D2: a new tenant starts with all five off, and the seed of tenant `default` turns all five on). This change does not wait for it.
- The note tools are not limited to users with the `ADMIN` role (owner decision of 2026-10-02). Every user of the tenant gets the tools `TenantToolPolicy` allows. A role check per user would need a per user filter that `ChatToolset` does not have, and the owner's tenant has one user.

### D17: Limits

| Limit | Property | Default | When exceeded |
| :--- | :--- | :--- | :--- |
| Note size for indexing | `app.obsidian.max-note-bytes` | 2 MiB | `SKIPPED`, reason `too_large` |
| Files indexed per vault | `app.obsidian.max-files` | 20,000 | Rest `SKIPPED`, reason `vault_file_limit` |
| Characters returned by read | `app.obsidian.read-max-chars` | 40,000 | Cut, with the full size stated |
| Content of one create or append | `app.obsidian.write.max-content-bytes` | 64 KiB | Refused, `too_large` |
| Note size after a write | `app.obsidian.max-note-bytes` | 2 MiB | Refused, `too_large`, so the agent never writes a note it would not index |
| Writes per chat request or run | `app.obsidian.write.max-per-request` | 20 | Refused, `write_limit` |
| Search hits | tool argument | 5, at most 20 | Capped |

A refused write is never cut and written in part, because a partial note is not what was asked for. `ObsidianProperties` refuses zero or negative values at startup with an error naming the property.

### D18: Metrics, logs and audit

Metrics (Micrometer, no note path, title or content in any tag):

- `obsidian.sync.up`, `obsidian.sync.last_connected_age_seconds` (D15), tag `vault`.
- `obsidian.watcher.events`, tags `vault`, `kind` (`create`, `modify`, `delete`, `overflow`).
- `obsidian.vault.rescans`, tags `vault`, `reason` (`startup`, `schedule`, `overflow`, `watcher_error`).
- `obsidian.vault.conflict_copies`, tag `vault`.
- `obsidian.tool.calls`, tags `tool`, `outcome` (`ok`, `refused`, `approval_pending`, `error`).
- `obsidian.write.refusals`, tag `reason` (`note_busy`, `note_changed`, `note_exists`, `too_large`, `write_limit`, `path_rule`, `not_utf8`).

Indexing outcomes are the framework's per-file outcomes and connector metrics, not repeated here.

Logs: INFO for a run's counts, a write (request id, vault, operation, and the first 12 hex digits of the SHA-256 of the path, not the path, kept by owner answer 73.3 of 2026-10-06), and sync state changes. The path is logged only at DEBUG, and note content never, because a note title is often personal. Refusals at INFO with their reason.

Audit: every note write, whether into the agent folder, approved, or refused by a path rule, is one event recorded through `AuditEventPort` of `add-deployment-modules`, with the event name `OBSIDIAN_NOTE_WRITTEN` (the name in the one naming style of `add-audit-and-gdpr-compliance` D3, made there in its audit action table), outcome `written`, `approval_pending` or `refused`, actor, tenant, the target with kind `obsidian_vault` and the connector id as its id, the operation, the content's length and SHA-256, and the full note path relative to the vault root in the `details` entry `path`, never the content (owner answer 72.7 of 2026-10-06). The default `LogAuditEventPort` of `add-deployment-modules` writes only the event name, tenant, actor, target and outcome and never prints `details`, so the path never reaches a log line. Only the company audit store of `add-audit-and-gdpr-compliance` saves it. The earlier short hash of the path as the target is removed. `add-audit-and-gdpr-compliance` (company, build group 5) registers its implementation later, which stores the event as an audit row. This change does not wait for it. Connector create, update and delete are already audited by the framework.

The startup banner (`StartupLogConfig`) lists each vault with its tenant, connector id, sync state and file count.

### D19: Erasure never touches the vault

Connector delete removes what the agent made: the manifest rows, the landed objects, the chunks and the registry rows. It never deletes a file in the vault folder or the volume, because a deletion there is a deletion on every one of the owner's devices once the client syncs it. Taking the local copy away is an operator step documented in `docs/OBSIDIAN.md`: stop the sync container, then remove the two volumes, which leaves the remote vault untouched. Tenant erasure is company work of `add-audit-and-gdpr-compliance` (build group 5), which lists `obsidian_vault_file` in its erasure inventory and keeps this rule (made there, its erasure table, and its task moved from this change's task 7.2 in the dependency fix of 2026-10-05). This change does not wait for it.

### D20: Markdown front matter and wiki links, for every Markdown document

These rules live in the one Markdown path (`IngestionService.processMarkdown`), so they apply to uploads, bucket scans and every connector alike. Doing them only for Obsidian would be the parallel parse path the framework forbids.

- Front matter is recognised with `commonmark-ext-yaml-front-matter` 0.28.0, the same version as `commonmark`. It is removed from the body. Its scalar properties and lists of scalars are rendered as one leading block of `name: value` lines, so properties such as `tags` and `aliases` stay searchable without YAML syntax. Nested values are skipped. A front matter block that is not valid YAML is indexed as ordinary text, as today, and logged at WARN.
- Title: the front matter `title`, else the first heading, else the file name without extension. The existing rule with one step added before it.
- Wiki links, rendered as text: `[[Note]]` becomes `Note`, `[[Note|alias]]` becomes `alias`, `[[Note#Heading]]` becomes `Note > Heading`, `[[#Heading]]` becomes `Heading`, `[[Note#^block]]` becomes `Note`. An embed `![[Note]]` becomes `Note`, an embed of a non-Markdown file (`![[image.png]]`) is removed.
- Obsidian comments `%% ... %%` are removed, because Obsidian hides them when reading. The callout marker `[!type]` at the start of a block quote is removed and its text kept.
- Implemented as a CommonMark inline parser extension and a small text pass for comments, with tests per rule. Markdown with none of these constructs renders exactly as today.

### D21: End-to-end tests

Owner request of 2026-10-04: every planned change carries end-to-end tests, deterministic Bruno tests wherever no AI model is needed. Four specs in `apps/ascend-agent/e2e/`, each with the next free number at implementation time and its tasks template:

- `<N>-obsidian-vault-connector`, deterministic: a fake vault fixture seeded into the e2e tenant's folder of the `obsidian-vaults` volume and a seeded `status/sync-status.json` prove the connector API refusals, indexing with the front matter and wiki link rules, the excluded files, the watcher without a sync call, rename and delete, the `obsidian_sync_up` gauge, and that deleting the connector leaves every vault file byte-identical. It reads HTTP answers, Qdrant points, Postgres rows, Prometheus samples and file contents.
- `<N>-obsidian-note-tools`, deterministic: the scripted model and e2e overlay of the shared harness of `close-agent-test-gaps` call the five note tools by name with fixed arguments, so no AI model runs. The harness starts only for deterministic tests, never for AI-run specs (owner answer 70.4 of 2026-10-04). It proves the read, the path refusal, the free write in the agent folder, the approval wait with approve and deny for a write outside it, the daily note from the template, the write limit and the not syncing line, by file contents and approval rows.
- The former deterministic spec `<N>-obsidian-sync-container` is dropped by answer 91.3 of 2026-10-08: its three checks (exit code 3 without the token, exit code 3 without a set-up vault, and no state volume on the agent service) move into the container test of the sync image (task 2.6), which already runs the locally built image, so no e2e spec repeats them.
- `<N>-obsidian-notes-chat`, AI-run: a real model answers from a note, follows an edit and a delete, creates a note in its folder and asks before appending outside it.
- `<N>-obsidian-live-sync`, account-gated: on the server host only, with the owner at the keyboard and the separate test vault of D5, whose vault and device names are owner facts. It proves real sync both ways, the daily note on the phone, no conflict copy, and the `down` state after the container stops.

Not provable end to end, and proven by the container test of the sync image and the unit and Testcontainers tests instead: the one-time login and token renewal, because they need the owner's password and two-factor code, the drifted setting restored on start, the typing burst and the overflow rescan of the watcher, which need a fake clock, and the scheduled rescan of `obsidian-vault-rescan`, which runs every 15 minutes.

### Required edits to other changes

None of these are made by this change. Each was listed so the owner of that change could make it. Every edit below is now made in its target change, checked on 2026-10-03 and noted under its heading, the edit to `add-deployment-modules` at the end included, which follows the owner decision of 2026-10-03 that `rag` is always on. A task here that uses an edit of a change that lands earlier uses it as it is. The three company changes below (`add-tenant-isolation`, `add-tenant-policy`, `add-audit-and-gdpr-compliance`, build group 5) register their parts later, and no task here waits for them.

`add-connector-framework`, made there (checked 2026-10-03 in `add-document-connectors`, which held the framework until it was split out on 2026-10-04 under the owner rule of that day, and carried over to `add-connector-framework` with the same decision numbers, its D3, D21 and D22 and its task 6.1 that creates `docs/CONNECTORS.md` with one section per connector type):

1. Connector type enum: add `OBSIDIAN`, admitted by the named check constraint of the framework's migration (`add-connector-framework` task 1.1).
2. A connector type declares whether it needs a credential. For a type that needs none, the credentials reference is empty and the framework does not resolve one.
3. Run trigger: add `EVENT`. An `EVENT` trigger while a run is in progress marks the connector dirty and starts exactly one follow-up run when the current one ends, instead of answering 409. The manual trigger keeps its 409.
4. A connector may supply the object key segment for a landed file, inside the tenant prefix and the markdown or documents folder the framework chooses.
5. When landing a file, the framework registers it in the document registry with the `source_type`, `origin_uri` and connector id the connector supplies.
6. `docs/CONNECTORS.md` links the Obsidian section of `docs/OBSIDIAN.md`.
7. A connector type may declare that its schedule comes from a system task of `add-shared-scheduler`. For such a type the framework creates no per connector sync execution, refuses a cron in a create or update with its `validation` code, and measures the maximum sync age against the shortest gap of that system task's cron. `OBSIDIAN` is such a type (D7).

`add-document-management-api`, made there (checked 2026-10-03, its D6, D7 and D12):

1. The registry keeps the `source_type` and `origin_uri` given at registration. A later bucket-scan upsert of the same object key does not overwrite them with `bucket-scan`.
2. `documents` gains a nullable `connector_id` column (moved to `add-connector-framework`, its D21, by owner answer 93 of 2026-10-08, which adds it in its own migration).
3. The ingestion run copies `source_type` and `connector_id` from the registry row onto every chunk (new constants in `IngestionMetadataKeys`), and both get a keyword payload index created at startup with the others (`connector_id` with its chunk field and index moved to `add-connector-framework` by owner answer 93 of 2026-10-08, through a `ChunkPayloadContributor` of `add-document-management-api`).
4. `GET /api/v1/documents` accepts a `sourceType` filter, the obvious companion of a listing that now holds several sources.

`add-tenant-isolation` (company, build group 5, registers its part later), made there (checked 2026-10-03, its decision 4 and its `rag-retrieval` spec):

1. The one search method, `TenantFilteredVectorSearch.search` in `com.lukk.ascend.ai.agent.service.search`, which `RagRetrievalService` calls, accepts an optional narrowing conjunct, built with `FilterExpressionBuilder` and always joined with AND to the mandatory tenant and access list filter. The architecture test that pins the single call site stays unchanged. Since the dependency fix of 2026-10-05 this change adds the narrowing filter to `RagRetrievalService` itself (D10), and `add-tenant-isolation` keeps it when it moves the search behind its mandatory filter. It also adds the foreign key from `obsidian_vault_file.tenant_id` to `tenants(id)` in its own migration (D9).

`add-tenant-policy` (company, build group 5, registers its part later), made there (checked 2026-10-03, its D2 tool table):

1. The tool allow-list knows the five tool names. A new tenant starts with them off, and the seed of tenant `default` turns them on. Its `TenantToolPolicy` implementation, which replaces the default of `add-agent-skills`, covers the five tools (D16, task moved from this change's task 6.9 in the dependency fix of 2026-10-05).

`add-action-approvals` (made there on 2026-10-02):

1. Design D2 and D3: kind `obsidian_note_write`, category `other`, rememberable allow only for `append` scoped to connector and path, handler provided by this change.

`add-audit-and-gdpr-compliance` (company, build group 5, registers its part later), made there (checked 2026-10-03, its audit action table, its erasure table and `specs/audit-logging/spec.md`). The event reaches it through `AuditEventPort`, and the tasks that store it and erase the manifest are that change's own (moved from this change's tasks 7.1 and 7.2 in the dependency fix of 2026-10-05):

1. Audit vocabulary: `OBSIDIAN_NOTE_WRITTEN` with outcome `written`, `approval_pending` or `refused`, in its one naming style of upper case words in the past tense (its D3).
2. Erasure and export inventory: `obsidian_vault_file` is erased with its connector, and the rule of D19 that erasure never deletes a file in a vault folder.

Checked, no edit needed: `add-keycloak-login` (`TenantContext.currentTenantId()` and `TenantContext.runAs` are used as they are), `add-agent-skills` (the five tools are ordinary `AgentNativeTool` beans, `ChatToolset` is used as it is, and the vault root `app.obsidian.vaults-root` is separate from `app.agent-home` because the vaults belong to the sync volume, not to the agent's own files), `upgrade-spring-boot-4` (the migration is an ordinary Flyway versioned SQL file, connector validation errors use its existing `validation` code, and the tools add no REST error), `add-agent-subagents` (a tool call inside a run returns a pending approval id like any other result and does not pause the run, because the approval is submitted as a kind, not through a gated tool), `add-mcp-tool-servers` (the five note tools are agent native tools in the always part of the tool list, so its server prefixes, exposure rules and deferred tool search leave them as they are), `add-shared-scheduler` (this change registers `obsidian-vault-rescan` under its registration contract, which needs no edit there).

`add-deployment-modules`:

Its edits to this change are made here: the service keeps the profile `obsidian`, the catalog entry `obsidian` lists no agent secret because the token lives in the sync container, and joins the `personal` preset, every agent bean of this change carries `@ConditionalOnModule("obsidian")`, and the migration plan names the module instead of a compose profile. One edit there follows the owner decision of 2026-10-03, made in that change (checked 2026-10-03, its D3 table row `obsidian` and its section for this change, owner answer 52):

1. Always on are core chat, monitoring, `rag`, memory, the sandbox and the prerequisites, and `obsidian` is one of the switchable modules. The document search that the `OBSIDIAN` connector type and `obsidian_search_notes` need is therefore always present, so the catalog entry `obsidian` lists no `requires` entry.

## Risks / Trade-offs

- [The client is a proprietary beta and can change or disappear] → pinned version, container test before any upgrade, nothing else depends on it, and the connector keeps working on the last local copy and reports sync as down (D5, D15).
- [Redistributing the client would need a licence we do not have] → the image is built locally only and never published (D5).
- [The token expires or is revoked and the client keeps running without syncing] → measured behaviour, so the health check and status file report `down` after the grace period, the agent warns in every tool result, and renewal is one documented command sequence (D3, D4, D15).
- [The token lifetime is unknown] → nothing in the design depends on it. It is measured in operation and written into `docs/OBSIDIAN.md` once known.
- [Obsidian warns against desktop Sync and headless Sync on the same device, without saying why] → the sync container runs only on the server host, never on the owner's development PC (owner decision of 2026-10-02), it uses its own folder and device name, and the vault is never a bind mount of a desktop vault (D5, D6).
- [The agent overwrites a remote edit that lands in the milliseconds between its check and its rename] → recent edit guard, compare before rename, merge strategy, and the overwritten version stays in Obsidian's version history (D11).
- [Prompt injection through a note or a fetched page makes the agent write junk] → writes outside the agent folder need approval, no delete or replace tool exists, limits per request, and every write is audited.
- [A personal vault in a multi-user tenant is readable by every user] → named limitation and documentation (D16).
- [inotify misses events or overflows] → events only trigger runs, every run compares against the manifest, and the system task `obsidian-vault-rescan` runs a full rescan every 15 minutes (D7, D8).
- [Front matter and wiki link rendering changes the indexed text of existing Markdown documents] → only documents with those constructs change, the change is cleaner text, and the project has no data to keep (owner answer 73.1 of 2026-10-06). A reindex picks it up.
- [The file and folder group setup is wrong and one container cannot write the other's files] → fixed gid 10001 in both images, setgid folders, umask 0002, and a container test that writes from each side (task 2.6).
- [Moment.js formats outside the table] → refused with the token named, never a guessed file (D13).

## Migration Plan

There is no data to migrate. The owner decided on 2026-10-02 (confirmed by owner answer 73.1 of 2026-10-06) that the project keeps no existing data until the first real customer deployment.

1. The Flyway migration creates `obsidian_vault_file` with its foreign key to `connector` and changes no existing table (the registry column is `add-document-management-api`'s). The foreign key to `tenants(id)` comes later with `add-tenant-isolation`.
2. Without the `obsidian` module in `COMPOSE_PROFILES`, nothing of this change runs: the sync container is not started and the agent registers none of its beans. With the module on and no `OBSIDIAN` connector, the watcher watches no folder and the tools are not offered.
3. The owner follows D4 once, then creates the connector with `POST /api/v1/connectors`. The first run indexes the whole vault.
4. Rollback: disable or delete the connector and stop the container. Landed documents stay until deleted through document management, as for every connector. Reverting the code leaves the table inert.

## Owner decisions of 2026-10-02

The three questions of the first draft are answered, and the design follows the answers:

1. Appending to today's daily note skips approval. `dailyNoteAppendWithoutApproval` stays `true` by default and can be switched off per vault (D14).
2. The sync container runs only on the server host. Development uses a separate test vault, never the owner's real vault (D5).
3. The note tools are not limited to administrators for now. The tenant's tool allow-list decides (D16). Since the dependency fix of 2026-10-05 the allow-list is reached through `TenantToolPolicy` of `add-agent-skills`, whose default denies only `app.tool-policy.denied-tools` (empty by default), and `add-tenant-policy` registers the tenant allow-list implementation later.

## Owner decisions of 2026-10-06

1. Answer 72.7: the audit event `OBSIDIAN_NOTE_WRITTEN` carries the full note path in the `details` entry `path` of `AuditEvent`, which the default `LogAuditEventPort` never prints. Only the company audit store saves it. The short hash of the path as the audit target is removed (D18, task 7.3). The INFO log line of a write keeps its short path hash, because it is a log line and not an audit event (D18, Logs).
2. Answer 73.3: the INFO log line of a write keeps the short hash of the note path, the first 12 hex digits of the SHA-256 of the path relative to the vault root, and never the path itself (D18, Logs, spec scenario "Write INFO line carries the short path hash", task 7.3).
3. Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores. This change needs none of it: the first run of a new `OBSIDIAN` connector indexes the vault into empty stores, and Markdown documents indexed before this change are not re-rendered.

## Owner decisions of 2026-10-07

Answer 75.1 (review of the group 3, 4 and 5 changes of 2026-10-07, fix of all 75 items approved): items 29, 34, 60 and 61 are fixed here. Item 29: task 4.3 takes the object key prefix from `TenantPrefixResolver` (D9) instead of a fixed `tenant/<tenantId>/`. Item 34, answer 75.4: the scenario lists of task 9.10 are written from this change's requirements. Item 60: the `obsidian-note-tools` spec no longer says "security is enabled". Item 61: the context lists the run trigger `EVENT` of `add-connector-framework`.

## Owner decisions of 2026-10-08

Answer 76.2: the scripted model of the shared harness of `close-agent-test-gaps` is Mockoon (the `mockoon/cli` image, pinned by version and digest). This change adds its script rules to the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json`, which holds every rule of every change, and keeps its reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/obsidian/` (task 9.5).

Approved fix of 2026-10-08: every deterministic spec of this change that runs a scripted chat turn wipes in AscendMemory the memories of its users in its Reset state and Post-run cleanup (`POST /api/v1/memory/wipe` with the provider `openai` and the service token), because the memory extraction of a scripted turn embeds through the scripted model into `ascend_memory_1536` (task 9.5). Superseded by answer 91.1 below.

Answer 87 (rule R1, several agent instances): checked every mechanism. Kept as written: the PostgreSQL advisory lock beside the in-process lock that serialises note writes to one vault (D11), the system task `obsidian-vault-rescan` on db-scheduler, once per firing in the cluster (D7), and the per instance watcher, which must stay local because inotify events reach only the instance that watches the shared volume (D8). Made explicit: every instance may start an `EVENT` run for one change, and the framework's one run per connector rule, now a Postgres lock every instance sees (`add-connector-framework` D22), turns those starts into one run plus at most one follow-up run (D8). `ObsidianSyncStatusReader` runs on Spring's `@Scheduled` with the auto-configured `TaskScheduler`, every instance reading the same status file for itself (D15).

Answer 88 (rule R2): no company plug-in point of this change changes. Answer 85.1: the token reaches the sync container only from `OBSIDIAN_AUTH_TOKEN` in the repository `.env` (D4), and no plan text exports it in a shell.

Answer 91.1: in the deterministic phase AscendMemory is faked in the one Mockoon container `e2e-scripted-model` under the route prefix `/ascend-memory/`, the agent's `app.memory.semantic.base-url` points there in the deterministic overlay, and AscendMemory is never restarted. The deterministic note tools spec (task 9.5) therefore wipes no memory and needs no dummy key. The AI-run spec (task 9.7) runs against the real AscendMemory.

Answer 91.3: the deterministic spec `<N>-obsidian-sync-container` (task 9.6) is dropped, because it only re-tested the locally built image. Its three checks, exit code 3 without the token, exit code 3 without a set-up vault, and no state volume on the agent service, move into the container test of task 2.6 (D21, the proposal, tasks 2.6, 9.7, 9.10 and 9.11). The connector spec, the note tools spec, the AI-run chat spec and the account-gated live sync spec stay, because each proves something on the live stack that no lower test proves.

Answer 93: the column `documents.connector_id`, its chunk field and its payload index, which the vault filter of D10 matches, are now added by `add-connector-framework` (its D21 and task 1.6) instead of `add-document-management-api` (D9, the required edits list, task 4.4). The Obsidian watcher stays (A10 is not cut). The review's side remark to drive the 15 minute rescan by a per connector cron instead of the system task `obsidian-vault-rescan` is not applied: it belongs to finding A10, which the owner did not approve, and it would change the job inventory of `add-shared-scheduler` and the framework rule of a schedule owned by a system task.

Answer 98 (owner rule 98, every value with a default is a setting): made external. On the `ascend-agent` service, each as `${ENV:default}` in `application.yaml`, the same default in `ObsidianProperties` and `- ENV=${ENV:-default}` in `compose.yaml` (task 3.2): `app.obsidian.vaults-root` (`APP_OBSIDIAN_VAULTSROOT`, `/app/vaults` in the docker profile and on the compose line, the host run default not decided), `app.obsidian.zone` (`APP_OBSIDIAN_ZONE`, `Europe/Warsaw`), `app.obsidian.watcher.quiet-period` (`APP_OBSIDIAN_WATCHER_QUIETPERIOD`, `3s`), `app.obsidian.watcher.max-delay` (`APP_OBSIDIAN_WATCHER_MAXDELAY`, `30s`), `app.obsidian.max-note-bytes` (`APP_OBSIDIAN_MAXNOTEBYTES`, `2MB`), `app.obsidian.max-files` (`APP_OBSIDIAN_MAXFILES`, `20000`), `app.obsidian.read-max-chars` (`APP_OBSIDIAN_READMAXCHARS`, `40000`), `app.obsidian.read.max-candidates` (`APP_OBSIDIAN_READ_MAXCANDIDATES`, `10`), `app.obsidian.search.default-limit` (`APP_OBSIDIAN_SEARCH_DEFAULTLIMIT`, `5`), `app.obsidian.search.max-limit` (`APP_OBSIDIAN_SEARCH_MAXLIMIT`, `20`), `app.obsidian.search.snippet-max-chars` (`APP_OBSIDIAN_SEARCH_SNIPPETMAXCHARS`, `500`), `app.obsidian.write.max-content-bytes` (`APP_OBSIDIAN_WRITE_MAXCONTENTBYTES`, `64KB`), `app.obsidian.write.recent-edit-guard` (`APP_OBSIDIAN_WRITE_RECENTEDITGUARD`, `10s`), `app.obsidian.write.max-per-request` (`APP_OBSIDIAN_WRITE_MAXPERREQUEST`, `20`), `app.obsidian.status.read-interval` (`APP_OBSIDIAN_STATUS_READINTERVAL`, `30s`), `app.obsidian.status.max-age` (`APP_OBSIDIAN_STATUS_MAXAGE`, `2m`), and the rescan system task's `app.scheduler.system-tasks.obsidian-vault-rescan.cron` (`APP_SCHEDULER_SYSTEMTASKS_OBSIDIANVAULTRESCAN_CRON`, `*/15 * * * *`) and `.time-zone` (`APP_SCHEDULER_SYSTEMTASKS_OBSIDIANVAULTRESCAN_TIMEZONE`, `Europe/Warsaw`) (task 4.7). On the `obsidian-sync` service, each as `${VAR:-default}` in `compose.yaml` with the same default in the entrypoint and health check scripts (task 2.7): `OBSIDIAN_TENANT` (`default`), `OBSIDIAN_VAULT_NAME` (`main`), `OBSIDIAN_DEVICE_NAME` (`ascend-agent`), `OBSIDIAN_EXCLUDED_FOLDERS` (empty), `OBSIDIAN_CONNECT_GRACE_SECONDS` (`300`), `OBSIDIAN_SYNC_HEALTHCHECK_INTERVAL` (`30s`) and `OBSIDIAN_SYNC_MEMORY_LIMIT` (default not decided, asked of the owner before task 2.7 runs). `OBSIDIAN_AUTH_TOKEN` is a secret: no default, `.env` only, and `run` refuses to start without it (D1). The rows go into `apps/ascend-agent/docs/CONFIGURATION.md` for the agent settings (task 3.4) and into `docs/CONFIGURATION.md` for the `obsidian-sync` service (task 2.10). Kept as constants, because they are not operational: the client version `0.0.14` (a pinned dependency, raised only by a change that reruns the container test, D1, D5), the user and group id 10001 and the folders `/vaults` and `/state` (the image layout both containers are built on), the sync settings of D2 (enforced on every start by design, so a drift cannot happen), the fixed exclusions of D8, the path rules of D10 (the 255 byte segment and 1,024 byte path bounds and the forbidden characters are file system and Obsidian name rules), the one retry of an append in D11 (part of the write algorithm), the Moment.js token table of D13, the 16 hex digits of the object key and the 12 hex digits of the logged path hash (formats), the exit code 3, the status states, the refusal reasons, the metric, event and kind names, and the advisory lock class key (an enum value, answer 98.10). No test or measurement of this change uses LM Studio: the deterministic specs use the scripted model, and the AI-run spec of task 9.7 states the provider key it needs and names no LM Studio default. Changed: D3, D15, tasks 2.7, 2.10, 3.2, 3.4, 4.7 and 5.1.

Answer 98.10: the connector run lock of `add-connector-framework` has the class key `AdvisoryLockClass.CONNECTOR_RUN` (value 1). The note write lock of D11, which is keyed by the same connector id, takes its own value `OBSIDIAN_NOTE_WRITE` of that enum, added by this change with the next free class key at implementation time, so the two locks never meet (D11, task 6.4). D8 now names the framework's run lock as the session advisory lock it is.

## Open Questions

None.
