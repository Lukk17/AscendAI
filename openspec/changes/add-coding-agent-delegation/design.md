## Context

See proposal.md for why. This section holds only the current state that shapes the approach.

- This change is build group 4, position 11 of the owner build order of 2026-10-04. It needs `close-agent-test-gaps`, `upgrade-spring-boot-4`, `add-keycloak-login`, `add-deployment-modules`, `add-shared-scheduler`, `add-agent-skills`, `add-agent-subagents`, `add-agent-sandbox` and `add-action-approvals`, which land earlier, and no company change.
- `add-deployment-modules` owns module switching: the catalog, `ASCEND_MODULES` (from `COMPOSE_PROFILES`), `@ConditionalOnModule`, the module secret check and the tenant module grant. Its catalog has the entry `coding` with `GITHUB_APP_ID` and `GITHUB_APP_PRIVATE_KEY` as agent secrets, and it removes `app.coding.enabled` and the error code `coding_disabled`. By owner decision of 2026-10-03 the sandbox is core and always on, so the entry `coding` requires no other module.
- `add-shared-scheduler` owns the db-scheduler engine and the system task contract: a recurring task bean with a name from one closed enum `SchedulerTaskName` and a cron from `app.scheduler.system-tasks.<name>.*`, safe to run twice, run once per deployment.
- `add-agent-sandbox` gives a runner service on port 9940 with a REST API to create a workspace, run a command (at most 900 seconds), read a file (1 MiB), write a file (4 MiB, with append), copy a folder out as a tar archive (50 MiB) and destroy a workspace. Workspaces run on gVisor `runsc` in production and on `runc` with a WARN banner on Docker Desktop. Only workspaces run on `runsc`, never Ascend's own services. They have no network by default, or an internal network whose only exit is a per-workspace Stripe Smokescreen egress proxy with a host allow-list. The runner never sets `Binds`, never puts a secret into an environment variable, label or command, and labels every object so its reaper removes leftovers. Workspace limits have maxima of 2 CPUs, 4096 MiB memory and 2 hours, and at most 4 workspaces exist at once. It also holds every runner addition this change needs, written into it on 2026-10-02 from this change's required edits (its D15 and D16): profiles marked `project-backed` that mount one project folder of the coding project area `ascend-coding-area` at `/workspace` through a volume subpath instead of the tmpfs, the four coding area endpoints done by an `area-helper` container, the runner configuration `app.runner.coding-area.*` with its startup checks, the host setup script `infra/sandbox/coding-area/setup-coding-area.sh`, the per-workspace credential gateway sidecar and its image `infra/sandbox/credential-gateway/`, the labels and reaper rules for both, and their metrics. This change adds the `coding` profile with its image (D16) and everything on the agent side.
- `add-agent-subagents` gives the `subagent_run` table, the states `waiting`, `running`, `awaiting_approval`, `done`, `failed`, `cancelled`, background runs on virtual threads with a heartbeat and a restart sweep, `RunContext`, `SubagentRunChangedEvent`, `/api/v1/runs` with events and cancel, the finished runs block in the next chat turn, and the price table `infra/pricing/pricing.yaml`. It owns the closed set of run kinds: `subagent`, `approval`, `coding`, `scheduled`, `self_review` and `integration`. The run table, the run service and `/api/v1/runs` are `core-chat` (owner decision of 2026-10-02), so they exist whatever modules are active. A coding run never enters `awaiting_approval`, because its push and its cleanup are approvals of their own (D14).
- `add-action-approvals` gives `ApprovalService`, an `ApprovalActionHandler` per kind with category, preview, execute, deny and expire, canonical JSON with a SHA-256 digest, at most once execution, a 24 hour timeout counted as a denial, a closed set of categories fixed in code, and `ApprovalChangedEvent`, which the app and the Discord channel of the OpenClaw plugin host `ascend-openclaw-host` of `add-openclaw-plugin-host` follow to show the owner every pending approval. Its closed sets already hold the categories `code_publish` and `workspace_cleanup` and the kinds `coding_push` and `coding_project_cleanup` for this change.
- `add-deployment-modules` also gives the company extension ports `UsageEventPort` (default does nothing), `AuditEventPort` (default writes one structured INFO log line), `QuotaGate` (default `AllowAllQuotaGate`) and `ModelAccessPolicy` (default `ConfiguredModelAccessPolicy`), each registered with `@ConditionalOnMissingBean`. `add-usage-metering-and-quotas` (company, build group 5) registers later the ledger with a closed set of request types behind `UsageEventPort`, its quota gate, and per tenant BYOK provider keys stored encrypted. This change does not wait for it.
- `add-agent-subagents` gives the tool policy port `TenantToolPolicy`, whose first implementation allows every tool. `add-tenant-policy` (company, build group 5) registers later its tenant allow-list behind that port, where a new tool ships off, and its provider and model allow-lists. This change does not wait for it.
- `add-shared-scheduler` (build group 3, before this change) also gives `OwnerNotificationService` and the `owner_notification` table in `core-chat`, whose allowed `(source, kind)` pairs live in its table `owner_notification_kind`. This change adds its own pairs, the source `coding_area` with the kinds `low_space` (empty `subject_ids`) and `cleanup` (`subject_ids` holds the cleanup approval's id), in its own Flyway migration (D15, answer 93). Its job inventory lists the system task `coding-area-free-space-check` of this change in zone `UTC`, and its one retention task `record-retention` runs the retention entries this change registers (D15, answer 89.7).
- `add-action-approvals` (build group 4, before this change) accepts an approval request of source `system`, started by a timed job, with no user, no conversation and no run, decided by the tenant administrator as usual (owner answer 49.2 of 2026-10-03).
- The agent runs on `eclipse-temurin:21-jre-alpine`, has JGit from `add-agent-skills`, and no `git` binary.
- Production target: one virtual server per customer, 24 to 32 GB of memory, Hetzner Cloud or Contabo, no nested virtualization. Development: Docker Desktop on Windows 11.

### Owner decisions of 2026-10-02 and 2026-10-03 this design follows

- 36.1: Claude Code is dropped completely. Only OpenCode is used, running on an OpenCode subscription such as OpenCode Go instead of a per-token API key where possible. The provider stays configurable so an API key or LM Studio also works.
- 36.2: secrets go into a per-workspace credential gateway, never into the workspace (D7).
- 36.3, replaced by the owner: no pool of fixed disk images wiped after each run. Coding projects live on one shared disk area. A project's folder is never deleted while its work is not done or not committed and pushed. Many runs and projects share the space. When free space falls below 10 percent, the agent asks the owner which projects to clean, and cleans nothing without his yes (D3 to D5).
- 36.4: a GitHub App with one narrow token per step (D9), installed on the owner's own repositories.
- 36.5: default limits of 5.00 US dollars and 45 minutes per run (maxima 20.00 and 90), 1 coding run at once (maximum 2), 30 model requests per minute (D12).
- 36.6: the package registry allow-list of D8.
- 36.7: the end-to-end spec uses a dedicated new private test repository (D23).
- 44: OpenCode Go is accepted with its terms risk (see the risk read below). A pay-per-token provider (`opencode-zen` or an API key provider) stays configurable as the fallback (D10). The `.env` names `OPENCODE_API_KEY` and `CODING_AREA_HOST_PATH` are approved (D10, D22). In production the coding project area is a separate partition mounted at `/srv/ascend/coding` (D4).
- 2026-10-03: the sandbox is core, always on and never switchable, so `coding` no longer requires it. `add-tenant-isolation` lands before this change, so this change adds the foreign keys of its own tables to `tenants(id)` and to its other tables in its own Flyway migration, and its stores follow the tenant rules of that change from their first day (superseded by the owner build order of 2026-10-04: `add-tenant-isolation` is company work of build group 5 and lands after this change, so it adds the foreign keys to `tenants(id)` in its own migration, and this change keeps its other foreign keys, D15, D24).
- 49 (2026-10-03): 49.1 the low space warning names its projects only in its text, and the cleanup approval carries the exact project list (D5). 49.2 an approval request started by a timed job has source `system` with no user, conversation or run, and the tenant administrator decides it as usual (D5). 49.4 resource-named error codes for not found and forbidden are allowed (D21).

### Measured and sourced facts this design rests on

Checked on 2026-10-02:

| Fact | Source |
| :--- | :--- |
| OpenCode is MIT, home `anomalyco/opencode` (`sst/opencode` redirects), npm `opencode-ai` 1.18.34 published 2026-09-30, native binary per platform, release tarballs `opencode-linux-x64[-baseline][-musl].tar.gz` | GitHub API `repos/anomalyco/opencode`, `https://registry.npmjs.org/opencode-ai/latest` read with curl on 2026-10-02 (version 1.18.34), releases API |
| `opencode run --format json` prints one JSON event per line (`step_start`, `text`, `reasoning`, `tool_use`, `step_finish`, `error`). `step_finish` carries `cost` and `tokens` with input, output, reasoning and cache read and write. Exit code 1 on error, else 0 | `packages/opencode/src/cli/cmd/run.ts` and `packages/schema/src/v1/session.ts` at tag `v1.18.34` |
| In `opencode run` a permission set to `ask` is auto-rejected (approved only with `--auto`), so run mode never waits. OpenCode has no money or token budget setting, only the agent option `steps` | `run.ts` at `v1.18.34`, https://opencode.ai/docs/permissions/, https://opencode.ai/docs/agents/ |
| OpenCode config: `provider.<id>.options.baseURL` and `options.apiKey` per provider, `{env:VAR}` substitution, `OPENCODE_CONFIG_CONTENT` (inline, loaded after the project file), `"share": "disabled"`, `"autoupdate": false`, `"lsp": false`, `OPENCODE_DISABLE_MODELS_FETCH`, `OPENCODE_DISABLE_LSP_DOWNLOAD`, `--pure`. Data, cache, config and state folders follow `XDG_*` and `HOME` | https://opencode.ai/docs/config/, https://opencode.ai/docs/providers/, https://opencode.ai/docs/cli/, `packages/core/src/global.ts` |
| OpenCode stores credentials added with `/connect` or `opencode auth login` in `~/.local/share/opencode/auth.json`, and also reads a key from an environment variable or from `{env:VAR}` in the config | https://opencode.ai/docs/providers/ |
| OpenCode Go is "a low cost subscription plan" for "open coding models". Go costs 10 US dollars a month, Go Plus 40 US dollars a month. Limits are dollar amounts per model, counted over 5 hours (20 percent of the monthly limit), a week (50 percent) and a month (100 percent). Usage beyond them can fall back to the Zen balance when enabled | https://opencode.ai/go, https://opencode.ai/docs/go/ |
| OpenCode Go authentication: subscribe in the OpenCode console, take the API key from `opencode.ai/auth`, and give it to OpenCode (`/connect`, or a key in the config). Endpoints: `https://opencode.ai/zen/go/v1/chat/completions` (OpenAI compatible), `https://opencode.ai/zen/go/v1/responses` and `https://opencode.ai/zen/go/v1/messages` (Anthropic style). Model ids are written `opencode-go/<model>` | https://opencode.ai/docs/go/ |
| `GET https://opencode.ai/zen/go/v1/models` answered 200 without a key and listed, among others, `minimax-m3`, `minimax-m2.7`, `kimi-k3`, `kimi-k2.7-code`, `glm-5.3`, `glm-5.3-flash`, `deepseek-v4-pro` and `deepseek-v4.1-flash`. Third party review pages list different model sets, so only the live list counts, and it changes over time | curl on 2026-10-02 |
| "You can use it with OpenCode or any agent." "Traffic is monitored for abuse that degrades the experience for other users." "Only one workspace member may subscribe." | https://opencode.ai/go, https://opencode.ai/docs/go/ |
| OpenCode Zen is pay as you go per million tokens, endpoint `https://opencode.ai/zen/v1/`, API key from the console, with optional automatic reload and monthly spending limits | https://opencode.ai/docs/zen/ |
| OpenCode Terms of Service, effective 2026-08-15, forbid use that "automatically or programmatically extracts data or Output" and "any processes that run or are activated while you are not logged into the Services, or that otherwise interfere with the proper working of the Services". They contain no clause that limits OpenCode Go to personal use or that names account sharing | https://opencode.ai/legal/terms-of-service |
| `opencode serve` is unsecured unless `OPENCODE_SERVER_PASSWORD` is set | https://opencode.ai/docs/server/ |
| Docker Engine 26.0 (API 1.45) added `VolumeOptions.Subpath`, which mounts one subfolder of a named volume. The subfolder must already exist. The daemon opens each path part without following symbolic links, so a link cannot lead the mount out of the volume | https://docs.docker.com/engine/storage/volumes/, https://github.com/moby/moby/pull/45687 |
| Docker's `local` volume driver accepts `type`, `o` and `device`, so a named volume can be bound to a host folder with `type=none`, `o=bind` and `device=<path>` | `daemon/volume/local/local_unix.go` in `moby/moby` master |
| A GitHub App installation token is created by `POST /app/installations/{installation_id}/access_tokens` with optional `repositories` and `permissions` that can only narrow the App's own, and expires one hour after creation | https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app |

Risk read from these facts, recorded in the ADR with its date: the OpenCode terms do not say that a subscription may drive unattended runs on a server, and one clause forbids "processes that run or are activated while you are not logged into the Services". A coding run is started by the owner's own request in his chat, and runs on his own key, but it does run unattended for up to an hour. The OpenCode Go page invites use "with OpenCode or any agent" and monitors traffic for abuse. Confidence that the owner's personal use of his own Go key from his own server is allowed: medium. Confidence that one Go subscription may serve other tenants: low, so it is never done (D10). If OpenCode objects or changes its terms, the owner switches the deployment default provider to `opencode-zen` or to an API key provider in configuration, and nothing else changes. The owner accepted this risk in answer 44 of 2026-10-02.

## Goals / Non-Goals

Goals:

- The assistant never writes the code of a coding task itself. It starts OpenCode, follows it and reports.
- OpenCode never sees a provider key, a git token with write access, or any platform secret, even when the repository it works on is hostile.
- A project's work is never deleted without the owner's yes, and never while a run works on it.
- Reuse the runner of `add-agent-sandbox` and the run, approval, scheduler and metering machinery of the sibling changes, and add only what a coding run needs.
- Every push and every pull request is approved by the owner first, and nothing is merged.

Non-Goals:

- Claude Code, or any coding agent other than OpenCode (owner decision 36.1).
- Git hosts other than GitHub. The token port is generic, and a GitLab adapter is a later change.
- Interactive pairing with OpenCode, or follow-up messages to a running OpenCode process. A follow-up is a new run on the same project.
- Creating a new repository on GitHub. A new project's result is a bundle and a diff the owner downloads. Pushing it means the owner creates an empty repository and starts a project on it.
- Automatic cleanup of project folders by age, size or state. Only the owner's approved cleanup deletes a folder (owner decision 36.3), apart from user and tenant erasure, which is itself an explicit order.
- A size limit per project. The area is shared, and the free space check, the run stop below 5 percent and the owner's cleanup protect it (D5).
- Coding runs started by subagents. The tools are offered to the main chat only.
- Data migration. The project is under development, so there is nothing to migrate. Owner answer 73.1 of 2026-10-06 confirms that the data in today's development stores is disposable.

## Decisions

### D1: Run OpenCode's own command line tool headless, not an SDK and not a server

OpenCode runs as `opencode run --format json`, its documented headless interface, which prints one JSON event per line and ends on its own.

Alternatives considered:

- `opencode serve` with its HTTP API. It needs an inbound port into the workspace, which the runner has no route for by design, and it is unsecured without a password.
- Running OpenCode next to the agent or in the agent's container. Rejected: no isolation from the agent's secrets and data.
- Claude Code. Dropped by owner decision 36.1. The run kind, the orchestrator and the gateway keep no Claude Code path, so a second coding agent would be a later change with its own adapter.

### D2: A coding run is a run of kind `coding`, with one detail table

The run row in `subagent_run` gives status, list, cancel, events, heartbeat, the restart sweep and the finished runs block for free, and the mobile app and the Discord channel of the OpenClaw plugin host already follow that table. The kind `coding` is in the closed set of run kinds that `add-agent-subagents` owns. For kind `coding`, `subagent_name` holds `opencode`, `definition_version` holds the coding image digest, `prompt` holds the task text, `provider` and `model` hold the resolved model, and the limit columns hold the run's limits. Detail that only a coding run has lives in `coding_run` (D15).

Coding runs use their own pool of the one slot pool `RunSlots` of `add-agent-subagents` (its D10, answer 89.7 of 2026-10-08), not the pool of the subagent worker slots, because a coding run holds a project and 4 GiB of memory for up to an hour and must not starve subagents, and the reverse. This change registers the pool `coding` for the run kind `coding` with one `RunPoolRegistration` bean: the running limit `app.coding.limits.max-running` (default 1) and the waiting bound `app.coding.limits.max-waiting` (default 4). It keeps no semaphore or counter of its own. The counts live in the `subagent_run` rows in Postgres, so the limit holds across every agent instance (answer 87): a coding run takes its slot when its row moves to `running`, waiting coding runs start in arrival order across the cluster, and a slot freed on one instance wakes a waiting run on another through the `run_slot_freed` notification.

### D3: Coding projects

A coding project is the unit of work that owns a folder on the shared area: one GitHub repository on one work branch, or one new project. `delegate_coding` with `repository` or `new_project` creates a project and its first run. `delegate_coding` with `project_id` starts a new run on an existing project, so follow-up work continues on the same files and the same branch. Two projects may point at the same repository, each with its own folder and its own branch.

Each project has a `source_kind`: `github` (a GitHub repository), `new_project` (an empty new project) or `seed` (asked for by `add-self-built-integrations`). A `seed` project is never created by a tool. Trusted agent code starts its runs through the internal entry point `CodingRunService.startSeeded(SeedRunRequest)`, which takes the tenant, the user, a project name, a tar archive of the seed folder, the provider and model, the limits, the egress allow-list and a `purpose`. The seed is written as the project's base commit (D6 phase 3), so the diff and the bundle of its runs are relative to the seed. A `seed` run's gateway has only the `model` route and no `git` route, its egress allow-list is the one its caller gives instead of `app.coding.network.allow` (validated the same way and at most the runner's 32 entries), and a `seed` project can never be published (`coding_not_publishable`, D14). `purpose` is `user` for every project made through the tools and `integration` for the seed runs of `add-self-built-integrations`. Provider, model, key, limits, quota and free space are resolved and checked as for any run. A `seed` project follows the same states, the same one-owner rule and the same cleanup rules as every other project.

Project state, kept in `coding_project.state` (D15), the owner's three states plus the two steps of a cleanup:

| State | Meaning | Set when |
| :--- | :--- | :--- |
| `in_progress` | A run of the project is `waiting` or `running`, or a publish or cleanup of it is executing | A run is created, a publish or cleanup starts executing |
| `done` | No run is active, and the work branch holds commits the remote does not have (always for a `new_project` or `seed` project, whose work lives only in its folder and in the stored bundles) | A run or a publish ends and `head_commit` differs from `pushed_commit` |
| `pushed` | No run is active, and every commit of the work branch is on the remote branch | A publish succeeds, or a run ends with `head_commit` equal to `pushed_commit` |
| `deleting` | An approved cleanup is removing the folder | Cleanup execution starts |
| `deleted` | The folder is gone. The row stays for the run history until its retention | Cleanup execution ends |

Nothing is ever left uncommitted when a run ends, because the collect step of D13 commits leftovers. So "committed and pushed" is exactly `head_commit = pushed_commit`, and the state is computed from those two columns, never guessed.

One active owner per project: the conditional update `UPDATE coding_project SET state = 'in_progress', version = version + 1 WHERE id = ? AND state IN ('done','pushed')` claims a project for a run, a publish or a cleanup. Zero rows means it is busy, and the second caller is refused with `coding_project_busy`. A new run on a busy project waits in the coding slot queue only when its own project claim succeeds, so two runs never share a folder. The runner enforces the same rule a second time (D4).

### D4: The shared coding project area

The runner side of this decision (the volume, the subpath mount, the helper container, the area endpoints, the host setup script and the startup checks) is built by `add-agent-sandbox` (its D15), where it was written on 2026-10-02 from this change's required edits. This section keeps the whole picture, because the agent's rules rest on it.

Layout and storage:

- One named volume `ascend-coding-area`, created by the runner at startup when missing. In production (`app.runner.coding-area.mode: host`) it is a `local` driver volume with `type=none`, `o=bind` and `device=<app.runner.coding-area.host-path>`, so the files live in a host folder the deployment guide places on its own file system (in production a separate partition mounted at `/srv/ascend/coding`, owner answer 44). Filling the area then cannot fill the disk that Docker, PostgreSQL and the system use. In development (`mode: volume`) it is a plain named volume with a WARN banner, the same pattern as `runc` there.
- Inside the volume: `tenants/<tenantId>/projects/<projectId>/`, where the tenant id is the tenant slug and the project id is a UUID the agent made. Inside a project folder: `repo/` (the git work tree), `home/` (HOME and the `XDG_*` folders of OpenCode), `tmp/`, `out/` and `run/` (the task file, the event stream and the error log of the current run). Every file is owned by user 10002, the workspace user.
- The host setup (`infra/sandbox/coding-area/setup-coding-area.sh` of `add-agent-sandbox`, run once with `sudo` by the deployment guide) creates the host folder with owner 10002, mode 0700, and prints a WARN when the folder is not a mount point of its own.

How a workspace sees one project only:

- A coding workspace is created with `project: {id}` in the create body. The runner adds one `Mounts` entry of type `volume`, source `ascend-coding-area`, target `/workspace`, read-write, with `VolumeOptions.Subpath = tenants/<tenant>/projects/<projectId>`, where the tenant comes from the `X-Ascend-Tenant` header, never from the body. The subpath is built by the runner from two values it validates (a tenant slug and a UUID), never from a free path.
- The daemon opens each part of the subpath without following symbolic links (Context), so a link placed anywhere cannot lead the mount out of the project folder. Inside the container a link resolves inside the container's own view, which holds only that project.
- One workspace per project at a time: the workspace carries the label `ascend.sandbox.project=<projectId>`, and the runner refuses a create for a project that already has a live workspace with 409 `project_busy`.
- The forbidden settings test of the runner allows a `volume` mount only for `ascend-coding-area`, only at `/workspace`, only with a subpath that matches `tenants/<slug>/projects/<uuid>`, and only for a profile marked `project-backed`.

Area operations, done by a short-lived helper container (kind `area-helper` in the labels, the base image, `runc`, user 10002, no network, no capability, read-only root, only the area volume mounted at `/area`, removed when done). It never runs project code:

| Runner endpoint | Helper command | Use |
| :--- | :--- | :--- |
| `POST /v1/coding-area/projects` body `{projectId}` | `mkdir -m 0700 -p -- /area/tenants/<t>/projects/<p>/{repo,home,tmp,out,run}` | Create a project folder before its first workspace |
| `GET /v1/coding-area` | `df -B1 --output=size,avail /area` | Total and free bytes and the free percent of the area, plus the mode |
| `GET /v1/coding-area/projects/{projectId}` | `du -sxB1 -- /area/tenants/<t>/projects/<p>` | Size of one project |
| `DELETE /v1/coding-area/projects/{projectId}` | `rm -rf --one-file-system -- /area/tenants/<t>/projects/<p>` then a check that the path is gone | Remove a project folder. 409 `project_busy` when a workspace mounts it. `rm -rf` never follows a link out of the folder |

All four are tenant scoped by the `X-Ascend-Tenant` header like every runner call. The runner keeps no record of projects: the folders are the record, and the agent's `coding_project` table holds the state.

Startup checks of the runner: the volume exists or is created, its options match the configured mode and host path, `df` answers, and under the `production` profile it refuses to start in `volume` mode or with an empty host path. The banner shows the mode, the host path, the size and the free percent.

Why not the earlier pool of fixed-size disk images: the owner replaced it (decision 36.3). A project's work must survive its run so later runs and the publish continue on it, which a disk wiped after each run cannot give, and one shared area lets many projects use the space they need.

### D5: Free space, the owner's cleanup and the run stop

Free space check, the system task `coding-area-free-space-check` of `add-shared-scheduler` (cron `*/15 * * * *` in zone `UTC`, from `app.scheduler.system-tasks.coding-area-free-space-check.cron` and `.time-zone`), registered only when the module `coding` is active:

1. Read `GET /v1/coding-area` and set the gauge `coding.area.free.ratio`.
2. When the free percent is below `app.coding.area.low-space-percent` (10), log one WARN line, measure the size of every project that is not `deleted` (`GET /v1/coding-area/projects/{id}`, stored in `size_bytes` and `size_measured_at`), and then:
   - when no `coding_project_cleanup` approval is pending and at least one project is `pushed`, submit one approval of kind `coding_project_cleanup` (D14) that proposes the `pushed` projects with the oldest last activity first, enough of them to bring the free space to `app.coding.area.target-free-percent` (20), or all `pushed` projects when that is not enough. The request has source `system` of `add-action-approvals`, because a timed job starts it, so it carries no user, no conversation and no run, and it belongs to the tenant `app.coding.area.cleanup-approver.tenant`, whose administrator decides it as usual (owner answer 49.2). Its payload holds the exact list of proposed projects with the state and `version` of each (owner answer 49.1). Right after it, the task creates one owner notification through `OwnerNotificationService` of `add-shared-scheduler` with source `coding_area`, kind `cleanup` and the approval's id as its only subject id, saying that a cleanup approval waits,
   - create one owner notification through `OwnerNotificationService` of `add-shared-scheduler` with source `coding_area`, kind `low_space` and empty subject ids, at most once per `app.coding.area.notify-interval` (24 hours) while space stays low. It says how much space is free, and names in its body only the projects that use the most and the projects that are `done` and not pushed (owner answer 49.1), and that a cleanup approval is waiting when there is one. The project list that a cleanup acts on is only ever the one in the approval's payload.
   - Both notifications go to the user `app.coding.area.notify-user` of the tenant `app.coding.area.cleanup-approver.tenant`.
3. A pending approval is delivered to the owner by the approval channels (the app's pending list and, through the OpenClaw plugin host `ascend-openclaw-host` of `add-openclaw-plugin-host`, a Discord message). That approval is the question "which projects may I clean", and the notification is the warning. The Discord prompt of the cleanup approval uses the action types `approval_approve` and `approval_deny` of the one action endpoint `POST /api/v1/channel-host/actions` of `add-openclaw-plugin-host`, and the notifications are delivered through the channels of the notification port, whose one retry layer is the channel's own queue (owner answer 89.6 of 2026-10-08).

The task is safe to run twice: the pending approval check, which also keeps the `cleanup` notification to one per approval, and the notification interval of `low_space` keep it from asking twice.

Cleanup is never automatic. Two paths lead to it, both through `ApprovalService`:

- The proposal of the free space check above, approved or denied as a whole.
- The owner's own choice: the tool `coding_project_cleanup` or `POST /api/v1/coding-projects/cleanup` with a list of project ids. It submits one `coding_project_cleanup` approval for exactly those projects, with source `chat` and the asking user, as any request from a conversation or the REST API. A project in `in_progress` or `deleting` is refused before the approval. A `done` project may be listed only when the owner names it, and its preview line says in plain words that its work is not pushed and will be lost, with its commit count since the last push. This is how the owner decides when even his unpushed work may go.

The approval's preview lists, per project: tenant, repository or new project name, state, size, last activity, commits not pushed, and whether a pull request is open. Execution (`CodingProjectCleanupApprovalHandler.execute`), per project in the approved list:

1. Claim the project with the conditional update of D3 extended to the state and `version` stored in the approval payload. A project whose state or version changed since the approval (a new run started, a publish ran) is skipped with reason `project_changed` and kept.
2. Move it to `deleting`, call `DELETE /v1/coding-area/projects/{id}`, then move it to `deleted` and set `deleted_at`.
3. A runner error leaves the project `deleting` with reason `cleanup_failed`. The approval's execution is at most once by the approval change's own rule, so it is never retried on its own. The owner sees it in the project list and can approve a new cleanup.

The result of the execution lists the deleted, skipped and failed projects and the free percent after it.

Run stop: every poll of a running coding run (D6) also reads `df -B1 --output=avail,size /workspace` inside the workspace, which reports the area's file system because the project folder is a subfolder of it. When the free percent is below `app.coding.area.stop-run-below-percent` (5), the orchestrator stops OpenCode, collects the result (D13 needs only a few small writes), and ends the run `failed` with reason `DISK_LOW`. `delegate_coding` refuses a new run with reason `disk_low` below the same 5 percent, and its error lists the largest projects and says whether a cleanup approval is waiting. Task 9.2 proves that `df` inside a `runsc` workspace reports the host file system of the area, and if it does not, the orchestrator reads `GET /v1/coding-area` at most once a minute instead.

### D6: The orchestrator drives the runner API as it is

`CodingRunOrchestrator` works on the run's virtual thread in phases, each phase a step in the run's last step text:

1. Prepare: check the project claim, limits, quota and free space, resolve the provider, model and key (D10), and mint the read token (D9) when the project has a repository. On a project's first run, `POST /v1/coding-area/projects` creates the folder. The work branch name is `<prefix><first 12 hex of the project id>` (prefix `ascend/coding-` by default), made once per project.
2. Workspace: `POST /v1/workspaces` with profile `coding`, `project: {id}`, the run id, the allow-list of D8 (for a `seed` run, its caller's), the gateway routes and secrets of D7, and `ttlSeconds` equal to the run's time limit plus the collect and grace time, capped at the runner maximum.
3. Repository: on the first run of a repository project, one command `git clone --branch <base> --single-branch http://gateway:8080/git/<owner>/<name>.git /workspace/repo` and `git switch -c <branch>`. On a later run, `git -C /workspace/repo status --porcelain` must be empty and the branch must be the work branch, otherwise the run ends `failed` with `REPOSITORY_ERROR`. The run's start commit is `git rev-parse HEAD`, stored as `coding_run.start_commit`. For a `new_project` project, the first run does `git init` and one empty commit. For a `seed` project, the first run writes the seed tar with `PUT .../files?path=run/seed.tar&append=true` in parts of at most the runner's write limit, extracts it into `/workspace/repo` with `tar -x --no-same-owner --no-same-permissions -f /workspace/run/seed.tar -C /workspace/repo`, deletes the tar, runs `git init`, and commits the whole tree as the base commit with the fixed author of D13.
4. Start: one command starts OpenCode detached with `setsid nohup ... > /workspace/run/events.jsonl 2> /workspace/run/stderr.log & echo $!`, keeps the process group id in the orchestrator's memory for the run's lifetime (no column holds it, because only the instance that runs the run polls and stops it, and a restart closes the run, answer 93), and returns at once. The task text is written first with `PUT .../files?path=run/task.md`, never put into a shell string.
5. Poll: every `poll-interval` (default 5 seconds) one command reads new bytes of `events.jsonl` from the last offset, kept in the orchestrator's memory like the process group id (`tail -c +<offset> ... | head -c 60000`), reports whether the process group is still alive, and reports the area's free bytes (D5). The bytes read per poll are at most `app.coding.progress.max-read-bytes` (default 60000). The parser of D11 updates tokens, cost and last step, and the loop checks cancel, deadline, cost, quota and free space.
6. Stop when needed: `kill -TERM -<pgid>`, wait up to `app.coding.limits.stop-wait` (default 10 seconds), then `kill -KILL -<pgid>`.
7. Collect (D13), then destroy the workspace, and in every case of failure destroy it too. The project folder stays. The project's state moves to `done` or `pushed` by D3.

No runner endpoint is added for long commands or streaming: the runner's command limit of 900 seconds applies to each short command, and the detached process is bounded by the run's deadline and the workspace expiry.

Alternatives considered: a streaming exec endpoint in the runner (rejected, a long-held HTTP connection per run and new runner code for something polling does in a few lines), and a long single command (rejected, the 900 second maximum and the per-workspace lock would block the polls).

### D7: Credentials live in a per-workspace credential gateway

Secrets must not enter the workspace: the repository is untrusted code, its tests and install scripts run there, and any secret in the workspace can be read and sent to any allowed host (a package registry accepts uploads). The sandbox change decided that authenticated egress is added at the proxy, never as an environment variable. So each coding workspace gets one gateway container (kind `gateway` in the runner labels) next to its egress proxy.

The gateway itself is described once, in `add-agent-sandbox` D16: its image `infra/sandbox/credential-gateway/`, its networks and hardening, the route fields and the two route kinds (`credential` on port 8080, `inbound` on its own port 8081, each kind listening only on its own port), the secret files written through exec standard input, the network alias `gateway` with `NO_PROXY`, the private upstream list and the access log that never holds a header, query or body. This section keeps only what a coding run adds on top of it.

- Route kind: a coding run and a publish workspace use only `credential` routes. They never ask for an `inbound` route, which exists for `add-self-built-integrations`.
- Routes of a coding run: `model` to the run's provider (D10) with that provider's paths, and `git` to `https://github.com` limited to `/<owner>/<name>.git/info/refs` and `/<owner>/<name>.git/git-upload-pack`. The publish workspace's `git` route also allows `git-receive-pack` (D14). A `new_project` project has no `git` route, and a `seed` run has only the `model` route (D3). A local LM Studio is reached only when the operator lists its address (`http://host.docker.internal:1234`) as a private upstream of the runner, and the runner then creates that gateway with `ExtraHosts: ["host.docker.internal:host-gateway"]` (`add-agent-sandbox` D16, `close-agent-test-gaps` D8), so the name resolves on Linux Docker Engine too. A provider without a key (`lmstudio`) gets a route with no header.
- Secrets: the agent sends the model key and the git token of a run in the create body over the stack's private network with the runner token, which the runner API of `add-agent-sandbox` accepts (its D16), and keeps them only in memory for that call.
- Inside the workspace: the OpenCode provider base URL is `http://gateway:8080/model`, git gets the rule `url.http://gateway:8080/git/.insteadOf https://github.com/`, and the key the workspace holds is the fixed text `ascend-placeholder`.
- The runner tests of `add-agent-sandbox` prove the alias `gateway` resolves under `runc`, and task 9.2 here proves it under `runsc`. If it does not under `runsc`, the runner gives each workspace network a subnet from a configured pool and the gateway a fixed host address in it, and the base URL uses that address.

Alternatives considered:

- Secrets as environment variables of the workspace, or OpenCode's own `auth.json` in the project folder. Rejected: any process in the workspace reads them, and the project folder outlives the run, so a key in `home/` would stay on disk. It also breaks the sandbox spec's rule that a workspace holds no platform secret.
- Smokescreen with TLS interception to add headers. Rejected: it would need a CA trusted inside the workspace and Smokescreen does not add headers.
- Routing OpenCode's model calls through the ascend agent as a model gateway. Rejected: the workspace would need a route to the agent, which the sandbox design forbids, and the agent would become a streaming proxy for an hour per run.
- One shared gateway for all workspaces. Rejected for the same reason the sandbox change gives one egress proxy per workspace: it would have to tell workspaces apart by source address, and a bug would hand one run's key to another.

### D8: Network of a coding workspace

The workspace sits on its own internal network with two neighbours, the egress proxy and the gateway. The egress allow-list comes only from configuration (for a `seed` run, from its trusted caller, D3): `app.coding.network.allow` (default, owner decision 36.6: `registry.npmjs.org`, `pypi.org`, `files.pythonhosted.org`, `repo.maven.apache.org`, `repo1.maven.org`, `plugins.gradle.org`, `services.gradle.org`, `downloads.gradle.org`, `proxy.golang.org`, `sum.golang.org`, `crates.io`, `static.crates.io`, `index.crates.io`) plus `app.coding.network.tenant-allow.<tenant>`, at most the runner's 32 entries. `github.com`, `opencode.ai` and the model provider's host are never on it, so the only route to them is the gateway, which is limited to one repository with a read-only token and to the model paths. Gradle wrapper downloads that redirect to GitHub release hosts are covered by `downloads.gradle.org`. Anything not on the list fails, which OpenCode sees as an error and reports.

### D9: GitHub access through a GitHub App, one narrow token per step

The owner creates a GitHub App on his account with repository permissions `contents: write`, `pull_requests: write` and `metadata: read`, no webhook, and installs it only on his own repositories that he chooses (owner decision 36.4). `.env` holds `GITHUB_APP_ID` and `GITHUB_APP_PRIVATE_KEY` (the PEM, base64 encoded), the agent secrets of the module `coding` in the catalog of `add-deployment-modules`. `GitHubAppTokenService` signs a 9 minute RS256 JWT with the JDK's `Signature` class, finds the installation with `GET /repos/{owner}/{repo}/installation`, and creates an installation token with `repositories: [<name>]` and exactly one permission set per step:

| Step | Permissions | Where it is used |
| :--- | :--- | :--- |
| Clone and later fetches of a coding run | `contents: read`, `metadata: read` | The coding run's gateway |
| Read the default branch and check the branch | `metadata: read` | The agent, REST |
| Approved push | `contents: write`, `metadata: read` | The publish workspace's gateway |
| Approved pull request | `pull_requests: write`, `metadata: read` | The agent, REST |

Tokens are held in memory only for the call that uses them and are never stored, logged or returned. A token expires after one hour by GitHub's rule. A run longer than about 55 minutes does not need a fresh token, because the clone or the fetch happens at the start. Which repositories can be used depends on the client and is read from GitHub, never written into the spec (owner decision 65.10 of 2026-10-04). `GitHubRepositoryCatalog` lists the App's installations with `GET /app/installations` (signed with the App JWT), and for each installation creates a token with only `metadata: read` and reads `GET /installation/repositories` page by page. Every agent instance keeps its own copy of the list and reads it for itself (answer 87, CANON 26.1: local timed work that is correct when every instance runs it for itself): at startup, on a Spring `@Scheduled` refresh every `app.coding.repositories.refresh` (default `10m`) on Spring Boot's auto-configured `TaskScheduler`, never a timer or thread pool of its own and never a task of the shared scheduler, and again when a call answers that the App has no installation on a repository. It logs one INFO line with the number of installations and the full names of the repositories (`owner/name`), and one INFO line naming each repository added or removed since the last read. It keeps the list in memory only, as a cache whose time to live is `app.coding.repositories.refresh`: a list older than that is read again before a call uses it, so a missed or slow refresh never serves an old list for longer than one interval, and every instance holds the same list within one interval. No shared invalidation is needed, because a stale entry can only name a repository that GitHub then refuses when the installation token is minted (D9 above), or leave out a new one until the next read. A read that fails keeps the last good list, logs a WARN and raises `coding.repositories.refresh.failed`.

The list is shown through `GET /api/v1/coding-repositories` (authenticated, scoped to the caller's tenant) and the read-only tool `coding_repositories`. Each entry has `fullName`, `private`, `defaultBranch` and `allowed` (whether the caller's tenant may use it). Optional narrowing stays configuration: `app.coding.repositories.allow` (entries `owner/name` or `owner/*`, empty by default, which allows every installed repository) and `app.coding.repositories.tenant-allow.<tenant>`. A repository must be installed and, when a list is set, on it.

### D10: Providers, models and keys

OpenCode is the only coding agent. The provider of a run is configurable, in this order of choice: the tool input `provider`, the tenant's `app.coding.tenant-default-provider.<tenant>`, then `app.coding.default-provider`. Supported providers, each with its gateway upstream and paths:

| Provider | OpenCode provider id | Gateway upstream and paths | Key |
| :--- | :--- | :--- | :--- |
| `opencode-go` | `opencode-go` | `https://opencode.ai/zen/go`, paths `/v1/chat/completions`, `/v1/responses`, `/v1/messages` | The OpenCode console key of the subscription |
| `opencode-zen` | `opencode` | `https://opencode.ai/zen`, paths `/v1/chat/completions`, `/v1/responses`, `/v1/messages` | The OpenCode console key, billed per token |
| `anthropic` | `anthropic` | `https://api.anthropic.com`, `/v1/messages` | API key |
| `openai` | `openai` | `https://api.openai.com`, `/v1/chat/completions`, `/v1/responses` | API key |
| `gemini` | `google` through its OpenAI compatible endpoint | the agent's configured Gemini base URL | API key |
| `minimax` | `minimax` | the agent's configured MiniMax base URL | API key |
| `lmstudio` | `lmstudio` (custom, `@ai-sdk/openai-compatible`) | the operator's listed LM Studio address, `/v1/chat/completions` | none |

- The model comes from the tool input or `app.coding.providers.<provider>.default-model`, checked against `app.coding.providers.<provider>.models` and then through `ModelAccessPolicy` of `add-deployment-modules` (its company extension ports), which decides whether the tenant may use that provider and model. Its default `ConfiguredModelAccessPolicy` allows every provider the deployment has enabled, and the coding providers of `app.coding.providers.*` count as enabled while the module `coding` is active. `add-tenant-policy` (company, build group 5) registers its implementation with the tenant's provider and model allow-lists later, and this change does not wait for it. No coding-specific policy port is kept (ruling 13.1 of the dependency fix of 2026-10-05): the coding model lists are plain configuration checked before the port is asked, and the tenant decision is the same question `ModelAccessPolicy` answers for chat models. The `opencode-go` model list in configuration is checked by task 5.2 against the live `GET https://opencode.ai/zen/go/v1/models` answer, never copied from review pages. A local-only tenant can delegate with `lmstudio`.
- The OpenCode config inside the workspace (D11) points the provider's `options.baseURL` at `http://gateway:8080/model` and sets `options.apiKey` to the placeholder. No `auth.json`, no `opencode auth login` and no key in an environment variable of the workspace. Task 5.2 proves that the built-in `opencode-go` and `opencode` providers accept a `baseURL` override. If one does not, the config declares a custom provider with the same model ids on the matching AI SDK package, pointed at the gateway.
- The key: through `ProviderKeyResolver.resolve(tenantId, provider)`, a port this change owns, which returns the plain provider key to trusted agent code in memory, never through any API, for the credential gateway. Its default `DeploymentProviderKeyResolver`, registered with `@ConditionalOnMissingBean`, returns the deployment key only when `app.coding.providers.<provider>.allow-deployment-key` is true, and no key otherwise. The deployment key of `opencode-go` and `opencode-zen` is `OPENCODE_API_KEY` in `.env` (name approved by the owner in answer 44), and the API key providers use the agent's own configured key. `add-usage-metering-and-quotas` (company, build group 5) registers later the implementation that returns the tenant's BYOK key first (with `opencode-go` and `opencode-zen` as BYOK providers) and falls back to the deployment key by the same setting. This change does not wait for it.
- Subscription rule: an OpenCode Go subscription belongs to one person ("Only one workspace member may subscribe") and its terms are read as personal use (Context, Risk). So `allow-deployment-key` for `opencode-go` is true only in the personal deployment, where the key is the owner's own, and the customer stack installer sets it false. The agent refuses to start with `opencode-go` allowed to use the deployment key and more than one tenant configured. Every tenant of a multi-tenant deployment brings its own key.
- Usage limits of the subscription: OpenCode Go's own 5 hour, weekly and monthly dollar limits answer with an error when reached. The parser maps that error to the reason `PROVIDER_LIMIT` (a `failed` run), and the result text says that the subscription's limit was reached and when the 5 hour window allows more. Falling back to the Zen balance is a setting of the owner's OpenCode account, not of this change.

### D11: The OpenCode adapter

`OpenCodeAgent` builds the command and the config and parses the stream. It is one class, because OpenCode is the only coding agent (YAGNI). The fake binary of D23 makes it testable.

- Command: `opencode run --pure --format json --model <provider id>/<model> --agent build < /workspace/run/task.md` in `/workspace/repo`. Never `--auto`.
- `OPENCODE_CONFIG_CONTENT` JSON: `share: disabled`, `autoupdate: false`, `lsp: false`, `enabled_providers: [<provider id>]`, the provider with `options.baseURL` set to the gateway route and `options.apiKey` set to the placeholder, the agent `build` with `steps` from the run limits and `permission` with `edit`, `bash`, `read`, `glob`, `grep`, `list` allowed and `webfetch`, `websearch`, `external_directory`, `task`, `question` and `doom_loop` denied, so nothing is ever left at `ask`.
- Environment: `HOME=/workspace/home`, every `XDG_*` folder under `/workspace/home`, `TMPDIR=/workspace/tmp`, `OPENCODE_DISABLE_MODELS_FETCH=1`, `OPENCODE_DISABLE_AUTOUPDATE=1`, `OPENCODE_DISABLE_LSP_DOWNLOAD=true`, `OPENCODE_DISABLE_SHARE=1`, `OPENCODE_DISABLE_CLAUDE_CODE=1`, `OPENCODE_DISABLE_PROJECT_CONFIG=1`. `OPENCODE_DISABLE_SHARE` and `OPENCODE_DISABLE_PROJECT_CONFIG` are read by the code but not documented, so task 5.1 checks them on the pinned version. Because the project folder outlives the run, `home/` keeps OpenCode's own session data between runs of the same project, and holds no key (D7).
- Usage: each `step_finish` event's `cost` and `tokens`. OpenCode has no spend limit, so the agent's own check (D12) is the budget.

The rules file appended to the task says: work only in `/workspace/repo` on the current branch, commit with clear messages, never push and never change git remotes, run the project's tests, write nothing outside the repository except `/workspace/out`, and end with a summary of what changed, how it was tested and what is left.

### D12: Three layers bound cost and time

1. OpenCode's own limit: the `steps` option of the `build` agent.
2. The agent's check at every poll. Counted cost is the larger of the reported cost and tokens priced with `infra/pricing/pricing.yaml`, the same table the subagent limits use. For `opencode-go` the counted cost is what the subscription's dollar limits count too, so the same number guards both. At or over the limit, or past the deadline, the orchestrator stops the process group. Between two polls the gateway's request rate (default 30 model requests per minute) bounds the spend.
3. The workspace expiry of the runner and the destroy at deadline plus `grace` (default 60 seconds), whatever the process does.

Defaults (all under `app.coding.limits`, each with a maximum, owner decision 36.5): cost 5.00 US dollars per run (maximum 20.00), time 45 minutes (maximum 90), 1 running and 4 waiting coding runs (maximum 2 running), poll interval 5 seconds, model requests 30 per minute.

### D13: Collecting the result

After the process ends, still inside the run's deadline plus `grace`, the orchestrator runs short commands in the workspace:

1. `git add -A` and, when anything is staged, one commit `chore(ascend): uncommitted changes of coding run <id>` with the fixed author `AscendAI coding run <noreply@ascend.ai>`, so nothing is ever left uncommitted in the project.
2. Commit list, `git diff --stat <start_commit>..HEAD` and `git diff <start_commit>..HEAD` into `/workspace/out/`.
3. When a `test_command` was given: `bash -lc '<test_command>'` under `timeout` (at most the runner's 900 second command maximum and inside the deadline), with exit code and the last 64 KiB of output kept. The test command comes from the tool input that the owner's conversation produced, runs in the same sandbox as everything else, and gets no more rights than OpenCode had.
4. `git bundle create /workspace/out/changes.bundle <start_commit>..<branch>` when the run made new commits.
5. OpenCode's summary from its last text event, at most 20000 characters.
6. `GET .../archive?path=out` (runner limit 50 MiB). Each part is capped first: diff 10 MiB, events 10 MiB, test output 64 KiB, bundle `max-bundle-bytes` 25 MiB. A bundle above its cap is not stored, and the result says so. The work itself stays in the project folder.
7. Empty `/workspace/out/` and `/workspace/run/` for the next run.

The agent then scans every file and the summary for the run's exact secret values (D7 makes this a backstop, not the main protection), uploads to the bucket `coding-output` under `tenant/<tenantId>/coding/<runId>/` (`summary.md`, `diff.patch`, `diffstat.txt`, `commits.json`, `test-output.txt`, `events.jsonl`, `changes.bundle`, `result.json`, which also records the cost OpenCode reported next to the counted cost), with the tenant of the run's row, stores the prefix and digests in `coding_run`, sets `coding_project.head_commit`, and moves the run to `done` with the short result text of the spec and the project to `done` or `pushed` (D3).

### D14: Publishing and cleanup after approval

`coding_publish` and `POST /api/v1/coding-projects/{id}/publish` build a `CodingPushAction` and submit it to `ApprovalService` as kind `coding_push`, category `code_publish` (a category of `add-action-approvals` whose `allow` can never be remembered, and the kind's handler provided by this change). Payload: project id and version, repository, base branch, work branch, the head commit to push, the commit already pushed (null on the first publish), commit ids and messages since that commit, diffstat, and the pull request fields. The preview is built by the server from the project folder's stored results, never from model text. A second request is blocked by the conditional update of `publish_state` in D15, so two requests racing each other cannot both submit an approval. A publish is refused when the project is `in_progress`, has no repository (a `new_project` or `seed` project, `coding_not_publishable`), or has nothing to push (`head_commit` equals `pushed_commit`).

`CodingPushApprovalHandler.execute`:

1. Claim the project (D3) with the approved version, else `project_changed`.
2. Read the default branch through REST with a metadata token. Refuse `branch_is_default` when the work branch equals it (it never can with the prefix, the check is the guard).
3. Create a publish workspace of profile `coding` on the same project (`app.coding.publish.cpus`, default 1 CPU, and `app.coding.publish.memory-mib`, default 1024 MiB) whose gateway has only the `git` route with `git-receive-pack` allowed and a fresh `contents: write` token.
4. Check `git -C /workspace/repo rev-parse refs/heads/<branch>` equals the approved head, else `branch_changed`. Check `git ls-remote --heads origin <branch>`: empty on the first publish, or equal to `pushed_commit` on a later one, else `branch_moved`. Then `git push origin <head>:refs/heads/<branch>` with no force flag and no other refspec, which is a fast-forward on a later publish.
5. Destroy the publish workspace.
6. When asked and the project has no open pull request yet, mint a `pull_requests: write` token and `POST /repos/{owner}/{repo}/pulls` with head, base, the approved title and body. One call, no retry that could make a second pull request. When one is already open, the push updates it and the result names it.
7. Store `pushed_commit`, `pull_request_url` and `publish_state`, move the project to `pushed`, and return the outcome as the approval's execution result. A crash in the middle leaves the approval `unknown` by the approval change's own rule, is never retried, and leaves the project `in_progress` until the restart check below.

`CodingProjectCleanupApprovalHandler`: kind `coding_project_cleanup`, category `workspace_cleanup` (a category of `add-action-approvals` whose `allow` can never be remembered), execution as in D5.

Restart check: at startup, and in every firing of the orphan sweep of `add-agent-subagents` (its D14, a shared scheduler task run by one instance of the cluster), the project service moves every project left `in_progress` with no live run, publish or cleanup to `done` or `pushed` by D3, and every project left `deleting` stays `deleting` with reason `cleanup_failed`, because only the owner may decide to try again. With several agent instances (answer 87), "live" is read from the shared rows, never from the memory of the instance that checks: a run is live while its `subagent_run` row is `waiting` or `running` and the orphan sweep has not closed it, and a publish or cleanup is live while its approval's execution is still running on a live instance by the executor liveness rule of `add-action-approvals`. So a starting instance never takes back a project that a run on another instance still works on. The move is the conditional update of D3 on the project's `version`, so two instances that check at once move it once.

`GitHubClient` has no method that merges, deletes a reference, changes a protected branch or changes settings, and an architecture test fails when any class of `service/coding/` names a merge or delete endpoint path.

### D15: Tables `coding_project` and `coding_run` and their Flyway migration

One Flyway versioned SQL migration `V<n>__create_coding_project_and_run.sql` (`<n>` is the next free version at implementation time). Flyway runs it in every deployment, also when the module is off (`add-deployment-modules` D15). Every constraint and index is named. The same migration adds this change's notification pairs to the table `owner_notification_kind` of `add-shared-scheduler`: `INSERT INTO owner_notification_kind (source, kind) VALUES ('coding_area', 'low_space'), ('coding_area', 'cleanup') ON CONFLICT DO NOTHING` (answer 93 of 2026-10-08, group 3 item S3-8).

Database links: this change's migration adds the foreign keys between its own tables and to the tables of earlier changes. It adds no foreign key to `tenants(id)`: `add-tenant-isolation` (company, build group 5) creates the `tenants` table and adds `coding_project_tenant_fk` and `coding_run_tenant_fk` (no action on delete, tenant erasure deletes the rows first) in its own migration later (dependency fix of 2026-10-05, which follows the owner build order of 2026-10-04). `coding_project` gets the unique constraint `coding_project_tenant_id_uk` on `(tenant_id, id)`, so a run names its project together with its tenant and can never point at a project of another tenant:

| Constraint | Columns | References | On delete |
| :--- | :--- | :--- | :--- |
| `coding_project_publish_approval_fk` | `coding_project.publish_approval_id` | `approval_request(id)` of `add-action-approvals` | `SET NULL` |
| `coding_project_cleanup_approval_fk` | `coding_project.cleanup_approval_id` | `approval_request(id)` | `SET NULL` |
| `coding_run_run_fk` | `coding_run.run_id` | `subagent_run(id)` | `CASCADE` |
| `coding_run_project_fk` | `(coding_run.tenant_id, coding_run.project_id)` | `coding_project(tenant_id, id)` | no action |

`user_id` has no foreign key, because users live in the identity provider of `add-keycloak-login`, not in a table of the agent.

`coding_project`:

| Column | Type | Notes |
| :--- | :--- | :--- |
| `id` | `UUID` primary key | Also the folder name |
| `tenant_id` | `VARCHAR(64)` not null | From `TenantContext` of `add-keycloak-login`. No foreign key here, `add-tenant-isolation` adds `coding_project_tenant_fk` later |
| `user_id` | `VARCHAR(255)` not null | The user who created it |
| `source_kind` | `VARCHAR(16)` not null | Check in `github`, `new_project`, `seed` (D3) |
| `purpose` | `VARCHAR(16)` not null default `user` | Check in `user`, `integration` (D3) |
| `repository` | `VARCHAR(201)` null | `owner/name`. Check: not null exactly when `source_kind` is `github` |
| `new_project` | `VARCHAR(100)` null | The project name of a `new_project` or `seed` project. Check: not null exactly when `source_kind` is not `github` |
| `base_branch` | `VARCHAR(255)` null | |
| `work_branch` | `VARCHAR(255)` not null | |
| `state` | `VARCHAR(16)` not null | Check in `in_progress`, `done`, `pushed`, `deleting`, `deleted` |
| `state_reason` | `VARCHAR(32)` null | For example `cleanup_failed` |
| `version` | `INTEGER` not null default 0 | Raised on every claim and state move |
| `head_commit`, `pushed_commit` | `CHAR(40)` null | |
| `publish_state` | `VARCHAR(24)` not null default `none` | Check in `none`, `pending`, `pushed`, `pull_request_opened`, `denied`, `expired`, `failed`, `unknown` |
| `publish_approval_id`, `cleanup_approval_id` | `UUID` null | FKs to `approval_request(id)`, `ON DELETE SET NULL` |
| `pull_request_url` | `VARCHAR(500)` null | |
| `size_bytes` | `BIGINT` null | Last measured size |
| `size_measured_at`, `last_activity_at`, `deleted_at` | `TIMESTAMPTZ` null | |
| `created_at`, `updated_at` | `TIMESTAMPTZ` not null | |

Indexes: `(tenant_id, last_activity_at DESC)`, partial `(state) WHERE state IN ('in_progress','deleting')` for the restart check.

`source_kind` and `purpose` were asked for on `coding_run` by `add-self-built-integrations`. They live on `coding_project`, because the check they replace is on that table and a project's source never changes between its runs. A run reads them through its `project_id`.

`coding_run`:

| Column | Type | Notes |
| :--- | :--- | :--- |
| `run_id` | `UUID` primary key | FK `coding_run_run_fk` to `subagent_run(id)` `ON DELETE CASCADE` |
| `tenant_id` | `VARCHAR(64)` not null | From the run's project row. No foreign key here, `add-tenant-isolation` adds `coding_run_tenant_fk` later |
| `project_id` | `UUID` not null | FK `coding_run_project_fk` with `tenant_id` to `coding_project(tenant_id, id)` |
| `provider` | `VARCHAR(32)` not null | Check in the providers of D10 |
| `start_commit`, `end_commit` | `CHAR(40)` null | |
| `test_command` | `VARCHAR(1000)` null | |
| `workspace_id` | `UUID` null | The runner's workspace |
| `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens` | `BIGINT` not null default 0 | |
| `model_usage` | `JSONB` not null default `'{}'` | Per model token counts for the ledger |
| `exit_code` | `INTEGER` null | |
| `commits`, `files_changed`, `insertions`, `deletions` | `INTEGER` null | |
| `test_exit_code` | `INTEGER` null | |
| `output_prefix` | `VARCHAR(512)` null | `tenant/<tenantId>/coding/<runId>/` |
| `bundle_sha256` | `CHAR(64)` null | |
| `created_at`, `updated_at` | `TIMESTAMPTZ` not null | |

Indexes: `(tenant_id, created_at DESC)`, `(project_id, created_at DESC)`.

The cost of a run is stored once (answer 93): the counted cost of D12 in `cost_usd` of the run's `subagent_run` row, the same column every run kind uses, written at every poll. `coding_run` holds no cost column. The cost OpenCode itself reported stays in the run's stored `events.jsonl` and `result.json` objects (D13), where the owner can compare the two. The process group id and the read offset of `events.jsonl` are not columns either: only the instance that runs the run polls and stops it, so both live in that orchestrator's memory, and a restart closes the run instead of resuming it (D6).

Claims are conditional updates. A publish request claims with `UPDATE coding_project SET publish_state = 'pending', publish_approval_id = ? WHERE id = ? AND tenant_id = ? AND publish_state IN ('none','pushed','pull_request_opened','denied','expired','failed') AND state IN ('done')`, and zero updated rows means a publish is pending, the project is busy, or nothing waits to be pushed.

Retention runs on the shared retention task `record-retention` of `add-shared-scheduler` (owner answer 89.7 of 2026-10-08), with two beans this change registers with `@ConditionalOnModule("coding")`: a `RetentionCleanup` on the run entry `subagent-run` of `add-agent-subagents` that deletes the object store prefix of each coding run before its run row is deleted (the run retention of `add-agent-subagents`, 30 days), and a `RetentionEntry` `coding-project` (table `coding_project`, time column `updated_at`, the same age, condition `state = 'deleted'` and no run of the project left). Neither ever touches a project folder. Both are safe to run twice. This change keeps no retention task of its own.

### D16: Images

- `infra/sandbox/images/coding/Dockerfile`: `FROM` the base profile image of `add-agent-sandbox` by digest, adds Node.js 22 LTS from the official tarball checked against its published SHA-256, Temurin JDK 21 from its tarball with checksum, `python3-venv` and `pip`, `build-essential`, `ripgrep`, `jq`, and the OpenCode `opencode-linux-x64` tarball of the pinned release (1.18.34 on 2026-10-02) checked against the release's SHA-256. It removes set-user-id bits again and keeps the users 10001 and 10002 of the base image. The exact versions are the ones current when task 6.1 runs, written into the Dockerfile and the image's README, never `latest`.
- The credential gateway image `infra/sandbox/credential-gateway/` is built by `add-agent-sandbox` (its D16) and used here as it is.
- The coding image is built, scanned with Trivy and signed by the supply chain gate of `docker-patterns`, and its digest goes into the runner's `coding` profile in the same commit. A new OpenCode version is a deliberate image rebuild, so the owner sees the version change in the diff. No CI workflow is added by this change, the rebuild is a documented step in `infra/sandbox/images/coding/README.md`.

### D17: Resources on a 24 to 32 GB server

| Item | CPU | Memory | Disk |
| :--- | :--- | :--- | :--- |
| Coding workspace (profile `coding`) | 2.0 | 4096 MiB | its project folder on the area |
| Its egress proxy and gateway | 0.5 | 128 MiB | none |
| Publish workspace with proxy and gateway | 1.25 | 1152 MiB | the same project folder |
| Subagent and chat workspaces, 4 at the sandbox defaults | 4.0 | 4352 MiB | tmpfs inside memory |

The runner allows 4 workspaces in total, so a coding run plus a publish leave two places for other workspaces. The worst case of all sandbox work at once is about 7.5 GiB of memory, on top of the stack whose use task 9.4 measures. On a 24 GB server the default of 1 coding run at once stays. On a 32 GB server 2 are possible by configuration. The area needs the space of every project the owner keeps, which the deployment guide sizes at 100 GiB to start, and the free space check watches it. Task 9.4 measures the real peak of an OpenCode run that builds a Gradle project and a Node project under `runsc` before the defaults are final.

### D18: Metering

- Model spend: when the run ends in any state, the orchestrator records one `UsageEvent` per model in `model_usage` through `UsageEventPort` of `add-deployment-modules`, with request type `coding-agent`, the tenant, user, conversation, run id, provider, model, input, output and cache read tokens. The default of the port does nothing. `add-usage-metering-and-quotas` (company, build group 5) registers its implementation later, which writes each event as a ledger row. The run's `cost_usd` on `subagent_run` holds the counted cost, the same way subagent runs keep theirs, and is the only stored copy of it (D15).
- Sandbox time: the usage event of request type `sandbox` that `add-agent-sandbox` records per destroyed workspace covers the coding workspace and the publish workspace, because both are created through the same `SandboxClient` with the run id.
- Quota: `QuotaGate.check(QuotaRequest)` of `add-deployment-modules` (its company extension ports) runs before the run starts and at every poll, with the tenant, the user and the request type `coding-agent`, and a refusal ends the run `QUOTA_EXCEEDED`. Its default `AllowAllQuotaGate` allows every call, and the run's own cost and time limits (D12) bound its spend. `add-usage-metering-and-quotas` registers its quota gate behind this port later, and this change does not wait for it.
- The run's own counters and the metrics work alone, as in `add-agent-subagents` D12.

### D19: Metrics, logs and traces

Agent metrics, domain `coding.` after `add-observability` D2 and D5:

| Metric | Type | Tags |
| :--- | :--- | :--- |
| `coding.runs.started` | counter | `provider` |
| `coding.runs.finished` | counter | `provider`, `state`, `reason` |
| `coding.run.duration` | timer | `provider`, `state` |
| `coding.tokens` | counter | `provider`, `type` |
| `coding.cost.usd` | counter | `provider` |
| `coding.limit.hits` | counter | `limit` (`cost`, `time`, `quota`, `disk`, `provider`) |
| `coding.refusals` | counter | `reason` |
| `coding.publish` | counter | `outcome` |
| `coding.secret.redactions` | counter | none |
| `coding.area.free.ratio` | gauge | none |
| `coding.area.low.space` | counter | none, counts checks that found the area below the warning level |
| `coding.projects` | gauge | `state` |
| `coding.project.cleanups` | counter | `outcome` (`deleted`, `skipped`, `failed`) |

Runner metrics of the gateway and the area (`sandbox.gateways.created`, `sandbox.area.helper.runs`, `sandbox.area.free.bytes`) are defined by `add-agent-sandbox` (its D13).

Logs: MDC `tenant_id`, `subagent_run_id`, `coding_project_id`. INFO per phase and per state change, WARN per refusal, limit hit, redaction, low space check, failed cleanup and failed destroy. Task text, summary, diff and events only at DEBUG. The secret values of a run are registered with a log filter for the run's lifetime that replaces them with a marker in any line, as a backstop to the rule that they are never logged.

Traces: the run is an `Observation` named `coding.run` with child spans per phase, and runner calls are client spans under it. The free space check and cleanup execution are observations named `coding.area.check` and `coding.project.cleanup`.

Startup banner block: OpenCode version and image digest, providers with default model and whether each may use the deployment key (never the key), default and maximum limits, repository allow-list size, GitHub App configured or not (never the key), area mode, host path and free percent.

### D20: Threat model

| Threat | Control |
| :--- | :--- |
| Hostile repository code reads secrets | No secret in the workspace or the project folder (D7), placeholder key only |
| Hostile code reaches another project | The workspace mounts one project subfolder, the daemon does not follow links in the subpath, one workspace per project, helper containers run no project code (D4) |
| Hostile code exfiltrates the owner's code | Only package registries and the gateway are reachable, the gateway reaches one repository read only. Uploads to a registry stay possible and are accepted for the owner's own repositories (Risks) |
| Hostile code fills the disk | The area sits on its own file system, runs stop below 5 percent free, the owner is asked to clean below 10 percent (D5) |
| OpenCode pushes, merges or deletes on its own | Read-only token, `git-receive-pack` refused by the gateway on coding runs, no merge or delete code in the agent |
| Prompt injection in the repository widens OpenCode's rights | Inline config, disabled project config and denied permissions (D11) |
| Approved push differs from what the owner saw | Stored action with the head commit and the project version, branch name made by the server, both re-checked before the push |
| Work is deleted without the owner's yes | No automatic cleanup, cleanup only through an approval that is never remembered, state and version re-checked before each deletion |
| Run never ends | Deadline, process group kill, workspace expiry |
| Model spend runs away | Three layers of D12, the quota gate, and the subscription's own limits |
| Token theft from the agent | Tokens are one hour, one repository, one permission set, never stored |
| Another tenant reads a result or a project | Tenant keyed rows, object prefixes and folders, 404 on mismatch |

### D21: Errors

New `ApiErrorCode` values (resource-named codes for not found and forbidden are allowed by owner answer 49.4 of 2026-10-03): `coding_run_not_found` (404), `coding_project_not_found` (404), `coding_result_not_ready` (409), `coding_nothing_to_publish` (409), `coding_publish_pending` (409), `coding_project_busy` (409), `coding_not_publishable` (409, a `new_project` or `seed` project, one code for both, owned by this change, and the name `add-self-built-integrations` uses for its seed projects), `coding_cleanup_not_allowed` (409, a project `in_progress` or `deleting` in a cleanup list). Validation failures use the existing `validation` code with `errors` of D19 of `upgrade-spring-boot-4`. With the module off the routes do not exist (404), and a tenant without the module grant gets `module_denied` (`add-deployment-modules` D8). Runner codes of `add-agent-sandbox`: `project_busy` (409), `project_not_found` (404). Refusals inside the tools are tool results, never HTTP errors of the chat request.

### D22: Configuration

`CodingProperties` binds `app.coding` and carries `@ConditionalOnModule("coding")`: `default-provider` (`opencode-go` when `OPENCODE_API_KEY` is set, otherwise `lmstudio`), `tenant-default-provider.<tenant>`, `providers.<provider>.default-model`, `.models`, `.allow-deployment-key`, `.base-url` (where a provider has no fixed upstream), `limits.*` (D12), `network.allow`, `network.tenant-allow`, `repositories.allow`, `repositories.tenant-allow`, `branch-prefix` (`ascend/coding-`), `output.bucket` (`coding-output`), `output.max-*` (D13), `area.low-space-percent` (10), `area.target-free-percent` (20), `area.stop-run-below-percent` (5), `area.notify-interval` (24h), `area.cleanup-approver.tenant` (the tenant that the cleanup approval of the free space check and both notifications belong to, whose administrator decides that approval, the owner's tenant of the personal deployment by default), `area.notify-user` (the user of that tenant who receives the `low_space` and `cleanup` notifications, the owner by default, never a field of the approval, which has no user), `github.app-id`, `github.private-key` (from `GITHUB_APP_PRIVATE_KEY`), `github.base-url` (the GitHub REST API base address, default `https://api.github.com`, answer 86.2 of 2026-10-08, the one setting that points `GitHubAppTokenService`, `GitHubClient` and `GitHubRepositoryCatalog` at a fake in tests), `github.git-url` (`https://github.com`), `publish.preview-diff-bytes` (16 KiB). There is no `enabled` key: the module switch decides. The application refuses to start on a zero or negative limit, a default above its maximum, a branch prefix that is empty or does not end in `-` or `/`, an allow-list entry that is not `owner/name` or `owner/*`, `stop-run-below-percent` not below `low-space-percent`, `low-space-percent` not below `target-free-percent`, an unknown provider, or `opencode-go` with `allow-deployment-key` true and more than one tenant. The GitHub App secrets are checked by the module secret check of `add-deployment-modules`.

Runner configuration, defined by `add-agent-sandbox` (its D15): `app.runner.coding-area.mode` (`host` or `volume`), `.host-path` (from `CODING_AREA_HOST_PATH`, name approved by the owner in answer 44, `/srv/ascend/coding` in production), `.volume` (`ascend-coding-area`), `.helper-timeout` (60s). This change adds the profile `coding` to `app.runner.profiles` with the coding image digest (D16) as the default of `app.runner.profiles.coding.image`, which the environment variable `SANDBOX_CODING_IMAGE` replaces when it is set (D23), marked `project-backed`, with default limits of 2 CPUs and 4096 MiB.

Settings and environment variables (owner rule 98 of 2026-10-08): every value of this change with a default is a setting. The agent writes each as `key: ${ENV:default}` in `application.yaml`, `CodingProperties` carries the same default, and the `ascend-agent` service of `compose.yaml` writes `- ENV=${ENV:-default}`. ENV is Spring Boot's canonical environment form of the property (upper case, dots become underscores, hyphens removed). A per-provider or per-tenant map key is written out in `application.yaml` with its own placeholder, so the hyphen of a provider id never has to survive environment binding (for example `APP_CODING_PROVIDERS_OPENCODEGO_DEFAULTMODEL` for `app.coding.providers.opencode-go.default-model`). A list is one comma separated value. Task 7.1 builds them, task 7.23 documents them.

| Property | Environment variable | Default |
| :--- | :--- | :--- |
| `app.coding.default-provider` | `APP_CODING_DEFAULTPROVIDER` | empty, which keeps the derived rule above (`opencode-go` when `OPENCODE_API_KEY` is set, otherwise `lmstudio`) |
| `app.coding.providers.<provider>.default-model` | `APP_CODING_PROVIDERS_<PROVIDER>_DEFAULTMODEL` | for `opencode-go` the id task 5.2 reads from the live model list, for the others not decided |
| `app.coding.providers.<provider>.models` | `APP_CODING_PROVIDERS_<PROVIDER>_MODELS` | for `opencode-go` the live list of task 5.2, for the others not decided |
| `app.coding.providers.<provider>.allow-deployment-key` | `APP_CODING_PROVIDERS_<PROVIDER>_ALLOWDEPLOYMENTKEY` | not decided (D10 says only that the customer stack installer sets it false for `opencode-go`) |
| `app.coding.providers.lmstudio.base-url` | `APP_CODING_PROVIDERS_LMSTUDIO_BASEURL` | not decided (the operator's LM Studio address) |
| `app.coding.limits.cost-usd` and `.max-cost-usd` | `APP_CODING_LIMITS_COSTUSD`, `APP_CODING_LIMITS_MAXCOSTUSD` | `5.00` and `20.00` |
| `app.coding.limits.time` and `.max-time` | `APP_CODING_LIMITS_TIME`, `APP_CODING_LIMITS_MAXTIME` | `45m` and `90m` |
| `app.coding.limits.max-running` and `.max-running-ceiling` | `APP_CODING_LIMITS_MAXRUNNING`, `APP_CODING_LIMITS_MAXRUNNINGCEILING` | `1` and `2` |
| `app.coding.limits.max-waiting` | `APP_CODING_LIMITS_MAXWAITING` | `4` |
| `app.coding.limits.poll-interval` | `APP_CODING_LIMITS_POLLINTERVAL` | `5s` |
| `app.coding.limits.model-requests-per-minute` | `APP_CODING_LIMITS_MODELREQUESTSPERMINUTE` | `30` |
| `app.coding.limits.grace` | `APP_CODING_LIMITS_GRACE` | `60s` |
| `app.coding.limits.stop-wait` | `APP_CODING_LIMITS_STOPWAIT` | `10s` (the wait between TERM and KILL of D6 step 6) |
| `app.coding.limits.steps` | `APP_CODING_LIMITS_STEPS` | not decided (the `steps` option of D11 and D12) |
| `app.coding.network.allow` | `APP_CODING_NETWORK_ALLOW` | the registry list of D8 (owner decision 36.6) |
| `app.coding.repositories.allow` | `APP_CODING_REPOSITORIES_ALLOW` | empty |
| `app.coding.repositories.refresh` | `APP_CODING_REPOSITORIES_REFRESH` | `10m` |
| `app.coding.branch-prefix` | `APP_CODING_BRANCHPREFIX` | `ascend/coding-` |
| `app.coding.output.bucket` | `APP_CODING_OUTPUT_BUCKET` | `coding-output` |
| `app.coding.output.max-diff-bytes` | `APP_CODING_OUTPUT_MAXDIFFBYTES` | `10MB` |
| `app.coding.output.max-events-bytes` | `APP_CODING_OUTPUT_MAXEVENTSBYTES` | `10MB` |
| `app.coding.output.max-test-output-bytes` | `APP_CODING_OUTPUT_MAXTESTOUTPUTBYTES` | `64KB` |
| `app.coding.output.max-bundle-bytes` | `APP_CODING_OUTPUT_MAXBUNDLEBYTES` | `25MB` |
| `app.coding.output.max-summary-chars` | `APP_CODING_OUTPUT_MAXSUMMARYCHARS` | `20000` |
| `app.coding.progress.max-last-step-chars` | `APP_CODING_PROGRESS_MAXLASTSTEPCHARS` | `500` |
| `app.coding.progress.max-read-bytes` | `APP_CODING_PROGRESS_MAXREADBYTES` | `60000` (bytes of `events.jsonl` read per poll, D6 step 5) |
| `app.coding.area.low-space-percent` | `APP_CODING_AREA_LOWSPACEPERCENT` | `10` |
| `app.coding.area.target-free-percent` | `APP_CODING_AREA_TARGETFREEPERCENT` | `20` |
| `app.coding.area.stop-run-below-percent` | `APP_CODING_AREA_STOPRUNBELOWPERCENT` | `5` |
| `app.coding.area.notify-interval` | `APP_CODING_AREA_NOTIFYINTERVAL` | `24h` |
| `app.coding.area.free-space-read-interval` | `APP_CODING_AREA_FREESPACEREADINTERVAL` | `1m` (the fallback read of D5 when `df` does not report the area) |
| `app.coding.area.cleanup-approver.tenant` | `APP_CODING_AREA_CLEANUPAPPROVER_TENANT` | `default`, the owner's tenant of the personal deployment |
| `app.coding.area.notify-user` | `APP_CODING_AREA_NOTIFYUSER` | not decided (the owner's user id) |
| `app.coding.github.base-url` | `APP_CODING_GITHUB_BASEURL` | `https://api.github.com` (answer 86.2) |
| `app.coding.github.git-url` | `APP_CODING_GITHUB_GITURL` | `https://github.com` |
| `app.coding.publish.preview-diff-bytes` | `APP_CODING_PUBLISH_PREVIEWDIFFBYTES` | `16KB` |
| `app.coding.publish.cpus` and `.memory-mib` | `APP_CODING_PUBLISH_CPUS`, `APP_CODING_PUBLISH_MEMORYMIB` | `1` and `1024` (the publish workspace of D14 step 3) |
| `app.scheduler.system-tasks.coding-area-free-space-check.cron` and `.time-zone` | `APP_SCHEDULER_SYSTEMTASKS_CODINGAREAFREESPACECHECK_CRON`, `APP_SCHEDULER_SYSTEMTASKS_CODINGAREAFREESPACECHECK_TIMEZONE` | `*/15 * * * *` and `UTC` |

The maps `app.coding.tenant-default-provider.<tenant>`, `app.coding.network.tenant-allow.<tenant>` and `app.coding.repositories.tenant-allow.<tenant>` have no default entry, so they get no compose line. `app.coding.github.app-id` comes from `GITHUB_APP_ID` and `app.coding.github.private-key` from `GITHUB_APP_PRIVATE_KEY`, both `.env` only with no default, and `OPENCODE_API_KEY` is a secret with no default. The runner side: `SANDBOX_CODING_IMAGE` on the `ascend-sandbox-runner` service of `compose.yaml` as `${SANDBOX_CODING_IMAGE:-<the coding image digest of D16>}`, the same digest as the default of `app.runner.profiles.coding.image`, written in the same commit as that digest, and the CPU and memory keys of `app.runner.profiles.coding.limits` (`add-agent-sandbox` D7) with the defaults 2 CPUs and 4096 MiB, each as `${ENV:default}` in the runner's `application.yaml` and `- ENV=${ENV:-default}` on the runner's compose service, ENV in the canonical form of the key names that `add-agent-sandbox` gives `limits.*` (task 6.2). These runner rows go into `docs/CONFIGURATION.md`, because the runner has no configuration file of its own. Kept as constants, because they are not operational: the provider ids, upstream addresses and model paths of the D10 table (fixed upstream protocol addresses, the configurable ones are the agent's existing provider settings), the gateway address `http://gateway:8080` inside the workspace network (owned by `add-agent-sandbox` D16), the paths under `/workspace`, the OpenCode command, its inline config keys and its `OPENCODE_DISABLE_*` environment (security switches, never tuned), the 9 minute App JWT lifetime (GitHub allows at most 10 minutes), the GitHub App permission sets, the fixed commit author, the object names under the run prefix, the error codes, the metric names and the test markers. The runner's own maxima (the 900 second command maximum, the 50 MiB archive limit, the 32 allow-list entries) and `app.runner.coding-area.*` are settings of `add-agent-sandbox`.

### D23: Tests

- Fake OpenCode: `apps/ascend-agent/src/test/resources/fake-coding-agent/fake-opencode`, a small Bash script that prints recorded event streams of the real format (captured from the pinned version by task 5.1 and stored as fixtures), edits and commits a file, and follows markers in the task text: `#exceed-cost`, `#ignore-sigterm`, `#hang`, `#exit-1`, `#provider-limit`, `#print-env`, `#leak-token` (writes the value it is given by the test), `#try-push`, `#try-network <host>`, `#try-other-project`, `#fill-disk`, `#no-change`. A test image `ascend-sandbox-coding-test` adds it on top of the coding image under the real binary name, as `/usr/local/bin/opencode` in place of the real one, so the agent always runs the fixed command `opencode` of D11 and holds no setting that names a command (answer 90 of 2026-10-08: no test code and no test-only setting in real logic or service configuration). There is no `app.coding.command`, no startup check of a command folder and no `/opt/fake/bin`. Which image a `coding` workspace runs is the runner's ordinary profile setting `app.runner.profiles.coding.image`, whose value comes from one environment variable, `SANDBOX_CODING_IMAGE`, passed to the runner's compose service as `${SANDBOX_CODING_IMAGE:-<coding image digest>}` with no `.env.example` line (owner rule 98 of 2026-10-08), so the shipped default is the coding image digest of D16. How a test picks the coding test image, the one way for every change: it sets `SANDBOX_CODING_IMAGE` to the `ascend-sandbox-coding-test` image in the environment of the runner process it starts. A Testcontainers integration test passes the variable to the runner container it starts, and the deterministic e2e phase runs the coding spec last, recreates the runner once with the variable set in the shell of that one `docker compose up -d --force-recreate ascend-sandbox-runner` command, and its end step recreates the runner with nothing set, whose end check prints `docker compose exec ascend-sandbox-runner printenv SANDBOX_CODING_IMAGE` (the shipped image or nothing), the steps `close-agent-test-gaps` D7 names and task 9.5 adds (owner answer 98.1 of 2026-10-08). The value is an image reference, not a secret (answer 85.1). No setting, profile or overlay of the agent or the runner names the fake, and neither has an `e2e` profile. `add-self-built-integrations` (its D23 and task 10.8) adds an integration mode to the same fake and picks the image the same way.
- Unit tests: input validation, every refusal reason, provider and limit resolution, the stream parser against the fixtures, cost counting, branch names, project state rules, the cleanup proposal choice, the redaction scan, the approval payloads and previews, the GitHub App JWT and token request bodies (no merge or delete path anywhere, architecture test), configuration refusals.
- Integration tests (Testcontainers runner on Docker Desktop with `runc` and area mode `volume`, a local `git daemon` or a Gitea container as the git host behind the gateway, a Mockoon container (`mockoon/cli`, pinned by version and digest) that loads the same shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json` as the live stack (answer 86.1 of 2026-10-08) and serves the model provider under `/v1/` and GitHub's REST API under `/github/`, with `app.coding.github.base-url` pointed at it, Testcontainers PostgreSQL): a full run, a follow-up run on the same project, cancel, time, cost and disk limits, `#ignore-sigterm`, `#print-env` and a search for the secret values, `#try-push` refused, `#try-network` refused, `#try-other-project` finding nothing, restart sweep, result endpoints and their tenant check, publish approve, deny and expire, a second publish fast-forwarding, `branch_moved`, the free space check with a low area, cleanup approve, deny and `project_changed`.
- Runner tests of the area, the project mount and the gateway belong to `add-agent-sandbox` (its D14). This change adds the `coding` profile test (task 6.2) and the agent's Pact consumer interactions for them (task 3.1).
- Escape suite of `add-agent-sandbox` gains the coding profile with its project mount and gateway, and on a Linux host with `-PexpectRuntime=runsc` and area mode `host` (task 9.2).
- Tenant rules (D24): a migration test for every foreign key of D15, and an integration test for a call with no tenant bound. The test with two tenants for every coding store is in `add-tenant-isolation` (company), which adds it later.
- End-to-end (owner request of 2026-10-04: every planned change carries end-to-end tests, deterministic Bruno tests wherever no AI model is needed): two new specs in `apps/ascend-agent/e2e/`, each with the next free number at implementation time. The publish path is proven once end to end, by the AI-run spec (answer 91.3 of 2026-10-08), and below it by `CodingPublishIT` (task 8.3).
  - The scripted model of the shared harness of `close-agent-test-gaps` starts only for the deterministic spec below, never for the AI-run spec, which runs against the agent with the shipped profile (owner answer 70.4 of 2026-10-04).
  - `<N>-coding-delegation-fake-agent`, deterministic: the scripted model and e2e overlay of the shared harness of `close-agent-test-gaps` call `delegate_coding`, `coding_projects` and the cleanup with fixed arguments, and the runner's `coding` profile runs the test image through `SANDBOX_CODING_IMAGE`, whose `opencode` is the fake, so no AI model and no GitHub account are needed. On `new_project` targets it proves the run states and events, the result, diff and bundle endpoints, the object keys, `coding_result_not_ready`, `coding_not_publishable`, a follow-up run, `#no-change`, cancel with the project kept, the cost limit, the refusal of a limit above the maximum, the login role rules, and a cleanup approved with its warning. The other tenant steps are added to this spec in place by `add-tenant-isolation` (company) later.
  - The former deterministic account-gated spec `<N>-coding-publish-github` is dropped by answer 91.3 of 2026-10-08: it proved the publish path a third time. Its deny, fast-forward, `coding_publish_pending`, pull request once and `branch_moved` cases are proven by `CodingPublishIT` (task 8.3) against the shared Mockoon environment, the repository catalog by `GitHubRepositoryCatalogTest` (task 4.4), and a real push to GitHub by the AI-run spec below.
  - `<N>-coding-delegation-real`, AI-run: the live stack, a real chat model and real OpenCode with a 0.50 US dollar limit on the dedicated private test repository of owner decision 36.7 with the owner's GitHub App: the repository listed by `GET /api/v1/coding-repositories`, a trivial task delegated by the model, the run followed to `done`, the result and diff read, a publish approved through `/api/v1/approvals`, the branch checked on GitHub, a follow-up run on the same project, a cleanup of the pushed project approved and its folder gone, and a cancelled run whose workspace is gone and whose project folder stays. It runs alone.
  - Not provable end to end, and proven by the integration and escape tests above instead: the isolation markers (`#print-env`, `#try-push`, `#try-network`, `#try-other-project`), because they need a fake that tries to break out and a search of the workspace from outside, `#fill-disk` and the free space check with its notifications, because they need a small test area, the restart sweep, the seed runs, which `add-self-built-integrations` proves end to end, and the usage events, which the integration tests prove with a test `UsageEventPort` bean. The ledger rows, erasure and export are proven by `add-usage-metering-and-quotas` and `add-audit-and-gdpr-compliance` (company) when they register their implementations.

### D24: Tenant rules of the coding stores

Every coding store is keyed by tenant from the first day, through `TenantContext` of `add-keycloak-login` (`default` in the personal deployment). `add-tenant-isolation` (company, build group 5) adds the foreign keys to `tenants(id)` and the cross tenant checks later, and this change does not wait for it (owner rule of 2026-10-04):

- Tables: `coding_project` and `coding_run` carry `tenant_id VARCHAR(64) NOT NULL` with the foreign keys of D15, and every repository query filters on `tenant_id`. A row of another tenant is answered as not found (404 on the endpoints, `coding_project_not_found` or `coding_run_not_found`, and a tool error in the tools).
- Project folders: only under `tenants/<tenantId>/projects/<projectId>/` of the coding project area, where the runner builds the path from the `X-Ascend-Tenant` header of the call (D4), and the agent sends the tenant of the project row, never a tenant from tool input.
- Objects: run results only under the prefix `tenant/<tenantId>/coding/<runId>/` of the `coding-output` bucket. The agent serves an object only when its key starts with the caller's tenant prefix.
- Fail closed: the tenant comes from `TenantContext.currentTenantId()` of `add-keycloak-login`, which throws when no tenant is bound. A tool call, an endpoint call, a seed run start, the free space check and the retention task with no tenant bound are refused and touch no row, folder or object. The background thread of a coding run and the approval handlers bind the tenant of the run's or project's row with `TenantContext.runAs` before any other step. The free space check binds the tenant of each project it measures the same way, and its approval belongs to `app.coding.area.cleanup-approver.tenant`.

### D25: Audit, erasure and export

Audit: the run service records `CODING_RUN_STARTED`, the publish handler `CODING_RUN_PUBLISHED` and the cleanup handler `CODING_PROJECT_CLEANED` through `AuditEventPort` of `add-deployment-modules`, with the run or project id, the repository and the outcome, never the task text or the diff. The default of the port writes one structured INFO log line. `add-audit-and-gdpr-compliance` (company, build group 5) registers its implementation later.

Erasure and export of the coding stores (user and tenant erasure of the `coding_project` and `coding_run` rows, their `coding-output` objects and the project folders, and user and tenant export with one gzip tar archive of each project folder through `GET /v1/coding-area/projects/{id}/archive` of the runner of `add-agent-sandbox` D15) are added by `add-audit-and-gdpr-compliance` later, which owns erasure and export (dependency fix of 2026-10-05). This change gives it what it needs without an edit here: the run service's cancel, the runner's area delete and archive endpoints, and the tenant and user keys on every row, folder and object. Branches pushed to GitHub are outside the system and are neither erased nor exported. A project folder never holds a secret, because no secret ever enters it (D7).

### D26: Login roles of the coding endpoints

`add-keycloak-login` (build group 3 of the owner rule of 2026-10-04) lands before this change, and a change that adds endpoints after it adds its own rows to its authorization matrix (its D4), with a security slice test per row, and its coverage test `SecurityMatrixCoverageTest` fails the build for an endpoint with no row. This change adds these rows to the matrix in `SecurityConfig`, in the filter chain like every other row and not by method security:

| Path | Rule |
| :--- | :--- |
| `GET /api/v1/coding-repositories`, `GET /api/v1/coding-projects`, `GET /api/v1/coding-projects/*`, `GET /api/v1/coding-runs/*/result`, `GET /api/v1/coding-runs/*/diff`, `GET /api/v1/coding-runs/*/bundle` | authenticated, scoped by the controller to the caller's tenant |
| `POST /api/v1/coding-projects/*/publish`, `POST /api/v1/coding-projects/cleanup` | `ADMIN` only |

The read endpoints need a signed-in user of the tenant, `USER` or `ADMIN`, and the controller answers 404 for a project or run of another tenant (D24). The owner endpoints, publish and cleanup, need `ADMIN`: the filter chain answers 403 to a `USER` token before the controller runs, the controller checks `ADMIN` of the project's own tenant again, and an `ADMIN` of another tenant gets 404 `coding_project_not_found`. This change has no other owner endpoint. Run status, list, events and cancel stay on `/api/v1/runs/**`, whose row `add-agent-subagents` already owns in that matrix. The tools `delegate_coding`, `coding_repositories`, `coding_projects`, `coding_publish` and `coding_project_cleanup` are not endpoints and are governed by the tool policy port `TenantToolPolicy` of `add-agent-subagents`, whose default allows every tool, and a publish or cleanup they request is still decided only by a tenant `ADMIN` through the approval. Under the Spring profile `dev` the synthetic identity holds both roles, as `add-keycloak-login` defines (its D5).

## Required edits to other changes

This change edits no other change. Each edit below belongs to the named change. A target that lands earlier in the owner build order of 2026-10-04 already reflects its edit, which is marked made. A company target of build group 5 lands later and carries its own edit when it lands. No task of this change waits for an edit or is blocked by one.

### `add-deployment-modules`

Already written in that change: the catalog entry `coding` (agent secrets `GITHUB_APP_ID` and `GITHUB_APP_PRIVATE_KEY`), the removal of `app.coding.enabled`, and the removal of the error code `coding_disabled`. This change follows them as written (D21, D22). `OPENCODE_API_KEY` is not an agent secret of the module, because `lmstudio` and BYOK keys work without it.

From the owner decision of 2026-10-03 (owner answer 52) that the sandbox is core, made in that change, checked on 2026-10-03 (its D3 catalog and its section for this change):

1. The catalog entry `coding` requires no module. Its `requires: sandbox` and the sentence that `coding` without `subagents` fails on `sandbox` are removed.

### `add-shared-scheduler`

Made in that change on 2026-10-02 (its D2 inventory, its D7 and its required edit for this change):

1. The closed enum `SchedulerTaskName` gains `coding-area-free-space-check`, registered by this change only when the module `coding` is active (D5), cron in zone `UTC`, matching its job inventory. The former `coding-run-retention` is gone: retention is two entries of its one retention task `record-retention` (D15, answer 89.7 of 2026-10-08).
2. The allowed notification pairs live in its table `owner_notification_kind (source, kind)`, and its first migration holds no pair of a later change (answer 93 of 2026-10-08, group 3 item S3-8). This change adds the source `coding_area` with the kinds `low_space` (empty `subject_ids`, the projects named only in the body) and `cleanup` (`subject_ids` holds the cleanup approval's id), with no job, firing or run id, in its own migration (D15), used by the free space check of this change (D5).

### `add-agent-sandbox`

Made in that change on 2026-10-02 (its D3, D4, D6 to D9, D13 to D16 and its spec `agent-sandbox-runner`):

1. Design D4, D9 and spec `agent-sandbox-runner` "Workspaces are isolated": a profile marked `project-backed` mounts exactly one subfolder `tenants/<tenant>/projects/<projectId>` of the volume `ascend-coding-area` at `/workspace` through `VolumeOptions.Subpath`, instead of the tmpfs. The forbidden settings test allows that mount and no other.
2. Design D3 and the runner spec "lifecycle": the create body gains an optional `project` object (`id`) and an optional `gateway` object (`routes` with name, upstream, allowed paths, header kind, rate per minute, and the secret value), the workspace view gains `storage` (`tmpfs` or `project`) and `gateway` (route names only), and the error codes `project_busy` (409) and `project_not_found` (404).
3. Design D3: the coding area endpoints `POST /v1/coding-area/projects`, `GET /v1/coding-area`, `GET /v1/coding-area/projects/{projectId}` and `DELETE /v1/coding-area/projects/{projectId}`, done by the `area-helper` container of D4 here, tenant scoped by `X-Ascend-Tenant`.
4. Design D9 "The agent sends no secret to the runner" becomes: the agent sends the gateway secrets of a coding or publish workspace in the create body, and the runner writes them only into the gateway container's tmpfs through exec standard input, never into an environment variable, label, command or log, and keeps no copy.
5. Design D6 and D8: a sidecar kind `gateway` and a helper kind `area-helper` in the labels, the label `ascend.sandbox.project`, create order network, proxy, gateway, workspace, destroy in reverse, gateways reaped like proxies, helpers reaped when older than their timeout. The gateway joins the workspace network with the alias `gateway`, and `NO_PROXY` of a workspace holds `gateway`. Gateways and helpers run on the engine's default runtime like the egress proxy.
6. Design D7: profiles marked `project-backed` with their own default limits inside the runner maxima, and the runner configuration `app.runner.coding-area.*` of D22 with its startup checks. The profile `coding` itself, with the image of `infra/sandbox/images/coding/` and the defaults 2 CPUs and 4096 MiB, is added to the runner configuration by this change (D16, D22, task 6.2), because its image is built here.
7. Design D13: the metrics `sandbox.gateways.created`, `sandbox.area.helper.runs`, `sandbox.area.free.bytes`, and the banner lines for the area and the gateway image.
8. Design D15 and the spec "Coding project area operations run in helper containers": the endpoint `GET /v1/coding-area/projects/{projectId}/archive`, which streams one project folder as a gzip tar archive through the `area-helper`, answers 409 `project_busy` while a workspace mounts the project and never follows a link out of the folder, for the export of D25. Made in that change on 2026-10-03 (its D15, its runner spec and its task 10.3).

### `add-agent-subagents`

Made in that change on 2026-10-02 (its D10, D13 and D16, listed in its table of edits other changes asked of it):

1. The kind `coding` is already in its closed set of run kinds. For kind `coding`, `subagent_name` holds `opencode`, `definition_version` the image digest, `subagent_origin` is `owner`.
2. The closed failure set gains `CODING_AGENT_ERROR`, `SANDBOX_ERROR`, `REPOSITORY_ERROR`, `PROVIDER_LIMIT` and `DISK_LOW`.
3. Design D10: runs of kind `coding` use their own pool `coding`, registered by this change in the one slot pool `RunSlots` of that change through a `RunPoolRegistration` bean, not `max-running` of subagents (answer 89.7 of 2026-10-08). Made there.
4. Design D16: the finished runs block lists coding runs with the project, the outcome and the start of the result, and names the result endpoint.

### `add-action-approvals`

1. Made in that change: the categories `code_publish` and `workspace_cleanup` in its D9 and its category check constraint, each with remember `allow` never and remember `deny` yes.
2. Made in that change: design D3, kind `coding_push` with its handler `CodingPushApprovalHandler` and kind `coding_project_cleanup` with its handler `CodingProjectCleanupApprovalHandler`, both provided by this change, the same way `personality_change` is provided by `add-agent-soul`.
3. Made in that change, its D3 and D10, checked on 2026-10-03, from owner answer 49.2: an approval request of source `system`, started by a timed job, with no user, no conversation and no run, decided by the tenant administrator as usual. The cleanup approval of the free space check (D5) is submitted that way.

### `add-usage-metering-and-quotas`

Company, build group 5, lands after this change. It registers its implementations later, and no task here waits for it (owner rule of 2026-10-04, dependency fix of 2026-10-05). The three edits below were made in that change (its `usage-metering` and `byok-provider-keys` specs, its design D8, D9, D11 and D12). Edit 2 is turned around: `ProviderKeyResolver` is now this change's port with a deployment key default (D10), and that change registers the BYOK implementation. The tasks that register its implementations are in its inbox file of the dependency fix of 2026-10-05.

1. `specs/usage-metering/spec.md` first requirement: add `coding-agent` to the closed list of request types, with a scenario that a finished coding run writes one row per model it used, carrying its `run_id`. This change records the events through `UsageEventPort` (D18).
2. Design D8 and D9: register the implementation of this change's `ProviderKeyResolver` that returns the plain provider key of a tenant (BYOK first, the deployment key when allowed) to trusted agent code in memory, never through any API, for the credential gateway of this change. The BYOK providers gain `opencode-go` and `opencode-zen`. Its quota gate behind `QuotaGate` of `add-deployment-modules` applies to coding runs too (D18).
3. Design D11: `coding-agent` joins the `request_type` tag values.

### `add-tenant-policy`

Company, build group 5, lands after this change. It registers its implementations later, and no task here waits for it. Both edits below were made in that change (its design D1 and D8, its `provider-model-policy` spec and its task 2.6), and now plug in through ports:

1. Design D2: its `TenantToolPolicy` implementation (the port of `add-agent-subagents`) governs `delegate_coding`, `coding_projects`, `coding_publish` and `coding_project_cleanup`, which ship off for a new tenant. The deployment default policy of the personal deployment lists all four.
2. Design D1: its implementation of `ModelAccessPolicy` of `add-deployment-modules` (D10) checks the coding run's provider and model against the tenant's provider and model allow-lists before a coding run starts, through the same `TenantPolicyService` check, with `opencode-go` and `opencode-zen` as provider names. There is no coding agent choice to check, because OpenCode is the only one.

### `harden-cloud-deployment`

`harden-cloud-deployment` lands earlier (build group 3, position 4), so both edits moved here by the dependency fix of 2026-10-05 and are this change's own work: task 4.6 and the MODIFIED requirements of `specs/production-deployment/spec.md` of this change. `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY` (the PEM, base64 encoded) and `OPENCODE_API_KEY` (personal deployment only) come from `.env`:

1. `docs/DEPLOYMENT.md` "one cloud VM per customer" gains the coding area setup of D4 (a separate partition mounted at `/srv/ascend/coding`, `setup-coding-area.sh` of `add-agent-sandbox`, `CODING_AREA_HOST_PATH`), the GitHub App setup of D9, and `OPENCODE_API_KEY` for the personal deployment only.
2. Its secrets list gains `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY` and `OPENCODE_API_KEY`. The check that the App key is not empty is the module secret check of `add-deployment-modules`, not a rule of `ProductionStartupGuard` (answer 89.10 of 2026-10-08: the one production startup guard of `add-keycloak-login`, which replaces `ProductionCredentialGuard`).

### `add-audit-and-gdpr-compliance`

Company, build group 5, lands after this change. It registers its `AuditEventPort` implementation and carries the erasure and export of the coding stores (D25), and no task here waits for it. Edits 1, 2 and 3 are made in that change (its design, its `audit-logging`, `data-erasure` and `data-portability` specs, its proposal and its tasks 8b.2 and 8b.5), and the erasure and export task moved there (dependency fix of 2026-10-05):

1. User erasure and export include the user's `coding_project` and `coding_run` rows and the `tenant/<tenantId>/coding/<runId>/` objects of the `coding-output` bucket. User erasure also deletes the project folders the user created, after stopping their runs, because the erasure order is itself the owner's explicit decision. Tenant erasure deletes all of them and the folder `tenants/<tenantId>/` of the area. Branches already pushed to GitHub are outside the system and are not touched.
2. Audit actions `CODING_RUN_STARTED`, `CODING_RUN_PUBLISHED` and `CODING_PROJECT_CLEANED` with run or project id, repository and outcome, never the task text or the diff.
3. Export covers everything erasure covers (D25): user export also holds one gzip tar archive of each project folder the user created, and tenant export holds the rows, the objects and one archive of every project folder of the tenant. Made there: its D9 table row for this change and its `data-portability` spec name the project folder archives, fetched through the archive call of the sandbox runner.

### `add-keycloak-login`

Made in that change: its D4 table of later changes that add rows lists this change with the rows of D26, and its `agent-authentication` requirement "Each later change adds its own matrix rows and no endpoint is left without one" makes every later change add its own rows. These rows were listed in `add-auth-and-identity` until its login part was split into `add-keycloak-login` on 2026-10-04. Its D4 table names `/api/v1/coding-projects` and the run reads but not `GET /api/v1/coding-repositories`, which this change adds in its own row as D26 says.

1. Its list of later changes that add rows to the authorization matrix names this change with the rows of D26: the coding project and run reads authenticated and scoped by the controller, publish and cleanup `ADMIN` only.

### `add-tenant-isolation`

Company, build group 5, lands after this change, and no task here waits for it (owner rule of 2026-10-04). The owner decision of 2026-10-03 that each change landing after it adds its own foreign keys is kept as a record (superseded by the owner build order of 2026-10-04). Its decision 14, its `tenant-isolation` requirement for the stores of other changes (with a scenario for a coding run of another tenant) and its proposal list these stores. Its foreign keys to `tenants(id)` and its cross tenant checks of the coding stores are in its inbox files of the dependency fix of 2026-10-05.

1. Its decision 14 and its `tenant-isolation` capability list `coding_project` and `coding_run` (with `tenant_id`, and their foreign keys `coding_project_tenant_fk` and `coding_run_tenant_fk` to `tenants(id)` added by its own migration), the project folders under `tenants/<tenantId>/projects/` of the coding project area, and the prefix `tenant/<tenantId>/coding/` of the `coding-output` bucket, with the fail closed rule that `TenantContext` of `add-keycloak-login` already gives (D15, D24).

### Applied here from other changes

- `add-self-built-integrations` edit 1: the `seed` source with its internal entry point, the seed as the base commit, `purpose` `integration`, the caller's egress allow-list and no publish with `coding_not_publishable` (D3, D6, D8, D14, D21 and the `coding-delegation` spec).
- `add-self-built-integrations` edit 2: `source_kind` (`github`, `new_project`, `seed`) and `purpose` replace the check that exactly one of `repository` and `new_project` is set (D15, on `coding_project`, see there).
- `add-self-built-integrations` edit 3: the gateway route kind `inbound` on its own port 8081, and credential routes only on their own port 8080. Both are described once in `add-agent-sandbox` D16, which D7 points to.
- `add-mcp-tool-servers` edit 1: the three passages that named a server that change no longer ships (a Context line, a comparison in D9 and this change's required edit to that change) are removed. The GitHub App tokens of D9 stay as they are.

## Risks / Trade-offs

- [OpenCode's terms do not clearly allow unattended runs on a subscription] → the subscription key is the owner's own and used only in the personal deployment, runs start from his own request, the risk and the quoted clauses are recorded in the ADR with their date, and the provider is configuration, so switching to `opencode-zen` or an API key is one setting.
- [OpenCode Go's model list or limits change] → the model list is configuration checked against the live endpoint by task 5.2, and a provider limit ends the run with a clear `PROVIDER_LIMIT` reason.
- [A package registry on the allow-list accepts uploads, so hostile code can send the repository's source out] → Accepted for the owner's own repositories and stated in `docs/SECURITY.md`. No secret can leave this way. A tenant can shorten the allow-list to nothing for a run that needs no packages.
- [gVisor lacks a system call a build tool needs] → the coding image is tested under `runsc` with a Gradle, a Node and a Python build (task 9.3), and a failing tool shows as a command error OpenCode can see.
- [OpenCode changes a flag or its event format] → the version is pinned, the parser is tested against recorded fixtures of the pinned version, and a version bump is a deliberate image rebuild with the fixtures recorded again.
- [OpenCode's undocumented switches do not behave as read] → task 5.1 proves each one on the pinned version before the adapter relies on it, and the network rules of D8 hold whatever OpenCode's settings say.
- [The reported cost is wrong] → the counted cost is the larger of the reported cost and our own price table, and the gateway rate bounds spend between polls.
- [The shared area fills up because the owner does not answer] → new runs are refused and running ones stop below 5 percent, the area is on its own file system so the rest of the server keeps working, the owner is asked again after a denied or expired approval at the next check, and the notification repeats every 24 hours.
- [A project folder holds files a later run did not expect] → a later run requires a clean work tree on the work branch, else `REPOSITORY_ERROR`, and the owner decides.
- [A publish or cleanup crashes in the middle] → the approval's execution is `unknown` or the project `deleting`, never retried on its own, and the owner sees it. A push is a new or fast-forwarded branch and harms nothing.
- [Development on Docker Desktop has neither gVisor nor a separate file system for the area] → WARN banners, readiness fields and metric tags, and the production profile refuses both, the same pattern as the sandbox change.
- [A repository larger than the free space] → the clone fails with a clear `REPOSITORY_ERROR`, or the run stops with `DISK_LOW`.

## Migration Plan

1. Land as build group 4, position 11 of the owner build order of 2026-10-04, after the changes it needs (proposal). No step waits for a company change: `add-usage-metering-and-quotas`, `add-tenant-policy`, `add-audit-and-gdpr-compliance` and `add-tenant-isolation` (company, build group 5) register their implementations later (owner rule of 2026-10-04). The required edits to `add-shared-scheduler`, `add-agent-subagents`, `add-action-approvals`, `add-agent-sandbox` and `add-keycloak-login` (the matrix rows, made there when its login part was split out of `add-auth-and-identity` on 2026-10-04) are already made there. The edits once asked of `harden-cloud-deployment` are this change's task 4.6.
2. Production host: create the area's own partition and mount it at `/srv/ascend/coding` (owner answer 44), run `infra/sandbox/coding-area/setup-coding-area.sh` of `add-agent-sandbox` once with that path, create the GitHub App, install it on the chosen repositories, and put `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `CODING_AREA_HOST_PATH` and, in the personal deployment, `OPENCODE_API_KEY` into `.env`.
3. Build the coding image (the gateway image comes with `add-agent-sandbox`), write its digest into the runner's `coding` profile, add `coding` to `COMPOSE_PROFILES` (the sandbox runner is core and already runs), and start the stack. Flyway creates `coding_project` and `coding_run` in every deployment.
4. The tools, routes and system tasks exist only while `coding` is in `COMPOSE_PROFILES`. The agent reads the repositories of the App's installations from GitHub at startup, logs them, and lists them through `GET /api/v1/coding-repositories` and the tool `coding_repositories` (D9).
5. Rollback: remove `coding` from `COMPOSE_PROFILES` and run `docker compose up -d`. The tools and routes disappear and the system tasks stop. Workspaces left behind are removed by the runner's reaper. Project folders stay on the area until the owner decides, because nothing deletes them without his yes. The tables stay and are ignored, and Flyway runs forward only, so dropping them is a new migration written only if the owner asks.

## Owner decisions of 2026-10-06

Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores. This change needs none of today's data. Its tables and its disk area for coding projects start empty.

## Owner decisions of 2026-10-07

Answer 75.1 (review of the group 3, 4 and 5 changes of 2026-10-07, fix of all 75 items approved): items 33, 34, 69 and 72 are fixed here. Item 33: the checks of the undocumented switches and the recorded fixtures are task 5.1, not 5.2 (D11, D23 and the risks). Item 34, answer 75.4: the scenario lists of task 9.9 are written from this change's requirements. Item 69: no task is marked blocked by a required edit. Item 72: D23 names the e2e overlay of the shared harness as the second place where `app.coding.command` points at the fake (superseded by answer 90 of 2026-10-08: `app.coding.command` is removed and the fake is installed under the real binary name).

## Owner decisions of 2026-10-08

Answer 76.2: the scripted model of the shared harness of `close-agent-test-gaps` is Mockoon (the `mockoon/cli` image, pinned by version and digest). This change adds its script rules to the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json`, which holds every rule of every change, and keeps its reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/coding/` (task 9.5).

Answer 76.2 (the owner strongly prefers Mockoon, and no group 3 to 5 change uses the earlier mock server any more), applied to this change's own tests and confirmed by owner answer 78.3 of 2026-10-08 (unit tests use the JDK `HttpServer`, integration and e2e fakes use Mockoon containers): the unit tests of tasks 4.1 and 4.4 run against a local JDK `com.sun.net.httpserver.HttpServer` fake, as `close-agent-test-gaps` D1 already uses, so no test dependency is added, and the integration tests of D23 and tasks 7.6 and 8.3 and the Bruno requests of task 8.5 use a Mockoon container (the `mockoon/cli` image, pinned by version and digest) with its own environment file as the model provider and as GitHub's REST API (the environment file superseded by answer 86.1: the Testcontainers Mockoon loads the shared `scripted-model.json`). For the Bruno requests of task 8.5 this is superseded by answer 82.5 below.

Answer 78.3: both kinds of fake stay for this change's own tests: unit tests use the JDK `HttpServer`, and integration and e2e fakes use Mockoon containers. This confirms the application recorded in the answer 76.2 entry above.

Answer 82.5 (the owner called the earlier design overengineered and not best practice): one Mockoon container, `e2e-scripted-model` of `close-agent-test-gaps`, serves every HTTP fake of the plans that runs against the live stack. The Bruno requests of task 8.5 therefore use no Mockoon container of their own: the fake GitHub REST API is served by `e2e-scripted-model` in the harness phase of `close-agent-test-gaps` D7, its routes and rules in the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json` under the path prefix `/github/`, which no other fake uses (`close-agent-test-gaps` D5 lists the prefix of every fake), its reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/github/`, and its global variables, if any, starting with `github_`. The e2e overlay points the agent's GitHub REST API base address `app.coding.github.base-url` (answer 86.2) at `http://e2e-scripted-model:3000/github` (container port 3000, `close-agent-test-gaps` D8 rule 1). The integration tests of D23 and tasks 7.6 and 8.3 (Testcontainers) keep their own Mockoon container, which loads the same shared environment file by answer 86.1, and unit tests keep the JDK `HttpServer` (answer 78.3).

Approved fix of 2026-10-08: every deterministic spec of this change that runs a scripted chat turn wipes in AscendMemory the memories of its users in its Reset state and Post-run cleanup (`POST /api/v1/memory/wipe` with the provider `openai` and the service token), because the memory extraction of a scripted turn embeds through the scripted model into `ascend_memory_1536` (tasks 9.6 and 9.7). Superseded by answer 91.1 of 2026-10-08: the deterministic phase fakes AscendMemory in the one Mockoon container, so no deterministic spec wipes memories, and task 9.7 is removed by answer 91.3.

Answer 81.3, addition (mandatory): every host and port of this change follows the rules of `close-agent-test-gaps` D8, so the plan works on Linux Docker Engine, where `host.docker.internal` does not resolve by itself. Checked on 2026-10-08: the workspace reaches the model and git only through the gateway alias `gateway` on its own network (rule 1), the LM Studio upstream on `host.docker.internal` is reached by the gateway with the extra hosts entry that `add-agent-sandbox` D16 now adds for such a route (D7 here, rule 3), the image check of task 6.1 calls no other service (rule 5), and the mentions of Docker Desktop describe the development engine and name no address.

Answer 85.1: no plan text of this change exports a key or a secret in a shell. `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `OPENCODE_API_KEY` and the chat provider key of the AI-run spec come only from the repository `.env` (task 9.8). `SANDBOX_CODING_IMAGE`, set for the deterministic phase, is an image reference and not a secret.

Answer 86.1: the Testcontainers integration tests of D23 and tasks 7.6 and 8.3 run a Mockoon container that loads the same `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json` as the live stack, the model provider under `/v1/` and GitHub's REST API under `/github/`, instead of an environment file of their own.

Answer 86.2: the GitHub REST API base address setting is `app.coding.github.base-url`, default `https://api.github.com` (D22, replacing the earlier `github.api-url`). The neutral wording "the agent's GitHub REST API base address" of CANON 24.7 is replaced by that name in the answer 82.5 entry above and in task 8.5.

Answer 87 (rule R1, several agent instances): checked every mechanism. The coding slot pool is now the pool `coding` of the one Postgres backed `RunSlots` (answer 89.7). The repository list cache is refreshed by Spring's `@Scheduled` on the auto-configured `TaskScheduler`, per instance, with a time to live of one refresh interval (D9, task 4.4). The project restart check runs at startup and in the orphan sweep and reads liveness only from shared rows, so a starting instance never takes back a project another instance still works on (D14, task 7.5). Kept as written: the project and publish claims as conditional Postgres updates (D3, D15), the free space check on db-scheduler, run cancel and the restart sweep of `add-agent-subagents`. The process group id and the stream offset stay in the memory of the one instance that runs the run, which is correct, because only that instance polls and stops it.

Answer 88 (rule R2): no company plug-in point of this change changes (`ProviderKeyResolver`, `UsageEventPort`, `QuotaGate`, `ModelAccessPolicy`, `TenantToolPolicy`, `AuditEventPort`).

Answer 89.6: both alerts of the free space check are still created through `OwnerNotificationService.create` (the `cleanup` notice stays, rule R3). The Discord prompt of the cleanup approval uses the action types `approval_approve` and `approval_deny` of the one action endpoint `POST /api/v1/channel-host/actions` of `add-openclaw-plugin-host`, and delivery retries live only in the channel's own queue (D5 step 3).

Answer 89.7: the coding slot pool is one pool, `coding`, of the one slot pool `RunSlots` of `add-agent-subagents` (its D10), registered with a `RunPoolRegistration` bean from `app.coding.limits.max-running` and `max-waiting`. The counts live in Postgres, so the limit holds with several agent instances (answer 87). Retention is two beans on the one retention task `record-retention` of `add-shared-scheduler`, a `RetentionCleanup` on the run entry `subagent-run` and a `RetentionEntry` `coding-project`, and the system task `coding-run-retention` is gone. Changed: D2, D15, the context, the required edits list, the proposal, tasks 7.5 and 7.16.

Answer 89.10: the one production startup guard is `ProductionStartupGuard` of `add-keycloak-login` with `application-production.yaml`. This change's MODIFIED copy of "Credentials flow from the environment with a production startup guard" carries the new base text and the two new scenarios, and the module secret check of `add-deployment-modules` stays the check of the GitHub App key (the required edit for `harden-cloud-deployment`).

Answer 90: no test code and no test-only setting in real logic or service configuration. `app.coding.command`, its startup check of `/usr/local/bin` and `/opt/fake/bin`, and the runner's `e2e` profile are removed. The fake OpenCode is installed under the real binary name `/usr/local/bin/opencode` in the test image `ascend-sandbox-coding-test`, and the runner's `coding` profile image `app.runner.profiles.coding.image` comes from the one environment variable `SANDBOX_CODING_IMAGE`, whose default is the shipped coding image (D22, D23, the proposal, tasks 6.2, 7.1 and 9.5). A test picks the test image only by setting `SANDBOX_CODING_IMAGE` in the environment of the runner it starts, which D23 states as the one way, and `add-self-built-integrations` uses the same fake and the same way for its integration mode.

Answer 91.1: in the deterministic phase AscendMemory is faked in the one Mockoon container `e2e-scripted-model` under `/ascend-memory/`, so the deterministic spec of task 9.6 wipes no memory and needs no dummy key. The AI-run spec of task 9.8 runs against the real AscendMemory.

Answer 91.3: the publish path was proven three times end to end. The deterministic account-gated spec `<N>-coding-publish-github` (task 9.7) is dropped, the AI-run spec of task 9.8 stays as the one end-to-end proof of a real push and also lists the repository through `GET /api/v1/coding-repositories`, and `CodingPublishIT` (task 8.3) keeps every publish refusal and race case. Changed: D23, the proposal, the `coding-delegation` spec requirement on end-to-end proof, and tasks 9.5, 9.8, 9.9 and the blocking table.

Answer 93: the cost of a run is stored once, in `cost_usd` of `subagent_run`, and `coding_run` loses `reported_cost_usd` and `counted_cost_usd`, the reported cost staying in the stored `events.jsonl` and `result.json` (D13, D15, D18). The unread columns `agent_pgid` and `events_offset` are removed (D6, D15). The runner's tenant header becomes `X-Ascend-Tenant`, the one tenant header name (D4, D24, task 7.20, sent to `add-agent-sandbox` and `add-self-built-integrations` through `inbox93`). This change adds its notification pairs `('coding_area', 'low_space')` and `('coding_area', 'cleanup')` to `owner_notification_kind` in its own migration (group 3 item S3-8, D15, task 7.2). Not applied, because each would remove a capability: moving the seed runs into `add-self-built-integrations` (the seed source is the entry point that change calls), and dropping the `GitHostTokens` port (a company extension point for a later Git host, rule R2).

Answer 98 (owner rule 98, every value with a default is a setting): the settings table under D22 lists every value of this change with a default, with its property, environment variable and default. The agent writes each as `${ENV:default}` in `application.yaml` with the same default in `CodingProperties` and `- ENV=${ENV:-default}` on the `ascend-agent` compose service (task 7.1, and task 7.16 for the free space check's cron and zone). The runner's `SANDBOX_CODING_IMAGE` gets the compose line `${SANDBOX_CODING_IMAGE:-<coding image digest>}` and no longer an `.env.example` line, because rule 98 adds no `.env.example` line for a setting with a default, and the `coding` profile's CPU and memory limits get compose lines on `ascend-sandbox-runner` (task 6.2, D23). New setting names of this round: `app.coding.limits.cost-usd`, `.max-cost-usd`, `.time`, `.max-time`, `.max-running-ceiling`, `.poll-interval`, `.model-requests-per-minute`, `.grace`, `.steps`, `app.coding.output.max-diff-bytes`, `.max-events-bytes`, `.max-test-output-bytes`, `.max-bundle-bytes`, `.max-summary-chars`, `app.coding.progress.max-last-step-chars` and `app.coding.area.free-space-read-interval`. Added in the resumed round of the same day, from values D6 and D14 had kept in their text: `app.coding.limits.stop-wait` (`10s`), `app.coding.progress.max-read-bytes` (`60000`), `app.coding.publish.cpus` (`1`) and `app.coding.publish.memory-mib` (`1024`). Values nobody decided, written neutrally and asked of the owner before task 7.1 runs: the default models and model lists of every provider but `opencode-go` (whose values task 5.2 reads from the live list), `allow-deployment-key` per provider, the LM Studio base address, `limits.steps` and `area.notify-user`. Secrets with no default: `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `OPENCODE_API_KEY`. Constants kept, and why, are listed under D22. Rows: the agent's in `apps/ascend-agent/docs/CONFIGURATION.md`, the runner's in `docs/CONFIGURATION.md` (task 7.23). Where LM Studio is a default in a test or a measurement here, listed and not changed (owner answer 98.10): task 5.2 checks an `lmstudio` provider through the gateway on the pinned version, and `app.coding.default-provider` resolves to `lmstudio` wherever `OPENCODE_API_KEY` is unset, which includes the deterministic spec of task 9.6 and the integration tests unless they name a provider (the fake OpenCode calls no model there). The measurement of task 9.4 and the AI-run spec of task 9.8 use `opencode-go`.

Answer 98.1: no test line in `compose.yaml`, and the deterministic phase reaches the running containers by copy and recreate (`close-agent-test-gaps` D7). The coding spec (task 9.6) runs last in the deterministic phase, together with the integration spec of `add-self-built-integrations` task 10.8. Before it the runner is recreated once with `SANDBOX_CODING_IMAGE` set to the test image digest in the shell of that one command (`docker compose up -d --force-recreate ascend-sandbox-runner`). The end step recreates the runner with nothing set, and the end check prints `docker compose exec ascend-sandbox-runner printenv SANDBOX_CODING_IMAGE`, which shows the shipped coding image or nothing. The runner's config folder is `/app/config`, because `add-agent-sandbox` task 7.1 gives the runner image `WORKDIR /app`. This change copies nothing into it, and `add-self-built-integrations` task 10.8 adds the runner overlay copy and its removal check on top of these steps. This closes the open point of round 93 on whether one runner recreate is allowed: it is decided. Changed: D23 and task 9.5.

## Owner decisions of 2026-10-09

Answer 101: LM Studio is used only in tests that test LM Studio support. Task 5.2 checks that the gateway of the coding workspace reaches a local LM Studio, the `lmstudio` provider of D10, so it keeps LM Studio. No other test or measurement of this change uses LM Studio. No task changes.

## Open Questions

None. The owner answered questions 36.1 to 36.7 and 44 on 2026-10-02 and 49.1, 49.2 and 49.4 on 2026-10-03, decided on 2026-10-03 that the sandbox is core and that each later change adds its own foreign keys (the second superseded by the owner build order of 2026-10-04, D15), and this design follows them. Answer 44 closed the two former open questions: the `.env` names `OPENCODE_API_KEY` and `CODING_AREA_HOST_PATH` are approved, and the production area is a separate partition mounted at `/srv/ascend/coding`. Which repositories the GitHub App is installed on depends on the client: owner decision 65.10 of 2026-10-04, the agent reads them from the installation through the GitHub API, logs them and lists them (D9), instead of a fixed list. Owner decision 65.11 of 2026-10-04: the Linux host with gVisor for the `runsc` tests is chosen at implementation time, and no deployment target is chosen now.
