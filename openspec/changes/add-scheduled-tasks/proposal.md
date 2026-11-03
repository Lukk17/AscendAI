## Build order

Build order (owner build order of 2026-10-04, which supersedes the earlier orders): build group 4 (personal), position 12. It needs `upgrade-spring-boot-4`, `add-keycloak-login`, `add-deployment-modules`, `add-shared-scheduler`, `add-chat-streaming-and-conversations`, `add-agent-skills`, `add-agent-subagents`, `add-agent-soul` and `add-action-approvals`, all of which land earlier. `add-openclaw-plugin-host` (position 10) lands earlier too and delivers this change's notifications on Discord through the notification port, with no task here. `add-flutter-chat-app` (position 17) lands later and carries its own scheduled jobs screen. It depends on no company change.

This change depends on these changes and edits none of them:

| Change | What this change needs from it |
| :--- | :--- |
| `upgrade-spring-boot-4` | Spring Boot 4.1.1, Flyway versioned SQL migrations, the RFC 7807 problem detail with the one `ApiErrorCode` enum (its D19) and the `errors` field for validation messages |
| `add-keycloak-login` | The authorization matrix this change adds its row to, the identity resolved without a token (its D20) for a firing, `TenantContext.currentTenantId()` and `TenantContext.runAs`, and the Keycloak e2e users of tenant `default` |
| `add-deployment-modules` | `@ConditionalOnModule`, `ModuleState`, the tenant module grant, and the company extension port `AuditEventPort` with its safe default |
| `add-shared-scheduler` | The catalog entry `scheduler` with an empty `requires` list, which this change fills, the shared scheduler on db-scheduler 16.12.0, per record executions, the registration contract of system tasks, `CronRule` with five field cron in a named zone, the injected `Clock` and the `ManualScheduler` test support, and the owner notification store with `OwnerNotificationService`, the `OwnerNotificationChannel` port and `GET /api/v1/notifications` |
| `add-agent-skills` | `ChatToolset` with `AgentNativeTool` (the one place tools are composed) and the tool context keys |
| `add-agent-subagents` | The run table, the run kind `scheduled` it owns, background runs, worker slots, cost and token limits, the run deadline, the run view, `SubagentRunChangedEvent` and the tool policy port `TenantToolPolicy`, whose default allows every tool |
| `add-action-approvals` | The approval gate inside `ChatToolset`, which pauses a run that calls a tool in the "requires approval" mode |
| `add-agent-soul` | The personality file a run receives as its first system message |

`add-keycloak-login` lands before this change and its tasks use it as applied. No task waits for `add-openclaw-plugin-host` or `add-flutter-chat-app`: the first lands earlier and needs nothing of this change, and the second carries its own screen. `add-tenant-isolation`, `add-tenant-policy`, `add-usage-metering-and-quotas` and `add-audit-and-gdpr-compliance` (company, build group 5) register their implementations later, and no personal task waits for them (split of 2026-10-04, owner rule of 2026-10-04: nothing personal depends on company work). The tasks that were theirs moved to them (dependency fix of 2026-10-05). The edits each change needs are listed in design.md under "Required edits to other changes", and every one of them is made there (checked on 2026-10-03).

## Why

The owner wants the assistant to work on its own on a schedule, like OpenClaw's heartbeat, and to create its own reminders and recurring jobs: a morning briefing, a calendar check, a price watch, a reminder at a given time, with the result sent to him on Discord or in the mobile app (owner, 2026-10-02). Today the agent only answers when it is asked. `add-shared-scheduler` gives the agent a scheduler and a way to tell the owner something, and this change builds the assistant's own jobs on them.

## What Changes

- Assistant jobs, stored in a new `scheduled_job` table: a name, a job kind, a stored text, a schedule (one time, cron or fixed interval), a time zone stored per job (default `Europe/Warsaw`), an optional start and end, and for a job that thinks, the tools the run may use, an optional model, a cost and token limit per firing and a delivery mode.
- Two job kinds (owner answer 39.3). A `reminder` sends its stored text to the owner as a notification at firing time, with no model call. A `task` starts a background run of the run kind `scheduled` with the stored prompt, the stored tools and the job's limits, through the run machinery of `add-agent-subagents`. A task's firing never starts while the previous firing's run is still working.
- Limits per firing (owner answer 39.1): a cost limit and a token limit, both below the run limits of `add-agent-subagents`. There is no time limit per firing. A run of kind `scheduled` keeps the general background run limit of `add-agent-subagents` (`app.subagents.limits.max-duration-per-run`, default 10 minutes).
- Missed firings after downtime: all missed firings of one job collapse into one decision. The job fires once, late, when its last missed time is still inside its grace period (default 1 hour for recurring jobs, 24 hours for one time jobs), otherwise the firing is recorded as missed and a one time job sends a "missed reminder" notice instead. The owner confirmed these grace periods on 2026-10-02 (owner answer 43).
- A scheduled run does not see the user facts file (owner answer 39.4). When the agent creates a job, it writes the facts the job needs (a city, a threshold, a name) into the job's prompt.
- Agent tools `scheduled_job_create`, `scheduled_job_list`, `scheduled_job_update` and `scheduled_job_cancel`, offered in the main chat only. Jobs the agent creates need no approval. An agent task may only name tools the creating conversation already has, and the agent may change or cancel only jobs it created. A scheduled run never gets the scheduling tools. A tool in the "requires approval" mode of `add-action-approvals` still pauses the run for the owner's approval when a firing calls it.
- A tool `owner_notify`, offered only inside scheduled runs, so a job such as a price watch can stay quiet until it has something to say, and can end its own job after telling the owner.
- A REST API for the owner under `/api/v1/scheduled-jobs`: create, list, read, update, pause, resume, run now, cancel, and the firing history of a job.
- Every reminder, result, message, failure notice and missed reminder is an owner notification of `add-shared-scheduler` with source `scheduled_job`, readable through `GET /api/v1/notifications` and delivered through its channel port.
- Limits (owner answer 39.2): active jobs per user and per tenant, a shortest interval between firings of 15 minutes, 200 firings per tenant per day, prompt size, jobs created per chat request, how far ahead a job may be scheduled, and an automatic pause after three failed firings in a row.
- The whole feature is the module `scheduler`. `add-shared-scheduler` adds that catalog entry only as a name with an empty `requires` list, and this change fills it with the job tools, `owner_notify` and `/api/v1/scheduled-jobs`, `requires: [subagents]` and no `uses` entry, because notification delivery is `core-chat` and the jobs refer to nothing of the plugin host's module. Its beans carry `@ConditionalOnModule("scheduler")`, and a firing for a tenant without that module grant does not start. The shared scheduler engine and its system tasks stay in `core-chat`, always on.
- Tenant scoping through `TenantContext` of `add-keycloak-login` (a firing binds the job's tenant with `TenantContext.runAs`), audit events through `AuditEventPort` of `add-deployment-modules`, metrics, logs and traces for jobs and firings. Erasure and export of jobs are added by `add-audit-and-gdpr-compliance` (company) later.
- The project is under development, so there is no data migration and no backfill. Owner answer 73.1 of 2026-10-06 confirms that the data in today's development stores is disposable.

## Capabilities

### New Capabilities

- `scheduled-jobs`: the assistant job record, its two kinds, its schedule types and time zones, lifecycle states, limits, the owner REST API, tenant and user scoping, audit, metrics and logs.
- `scheduled-job-execution`: what a firing does: the reminder sent with no model call, the background run of kind `scheduled` with its prompt, tools, model and limits, the overlap rule, the missed firing rule, approvals inside a firing, failures and the automatic pause, the firing history.
- `scheduled-job-tools`: the four agent tools for jobs, the rules for jobs the agent creates, and the `owner_notify` tool inside scheduled runs.

### Modified Capabilities

(none. The archived specs in `openspec/specs/` describe no scheduling, and every capability this change touches that is not new belongs to a change that is not archived yet: the shared scheduler and owner notifications, runs, approvals, tool policy, conversations, identity, metering, the plugin host and the mobile app. Their changes are required edits listed in design.md, not delta specs here.)

## Impact

- No new dependency. db-scheduler and the notification store come with `add-shared-scheduler`.
- New code in ascend-agent, all in the module `scheduler`: `service/schedule/` (job service, schedule calculator, firing handler, limits, the agent tools, the `owner_notify` tool), `controller/ScheduledJobController`, `config/properties/ScheduledJobProperties`, models and Spring Data JDBC repositories.
- Changed code in ascend-agent: `ChatToolset` gains no logic of its own (the new tools are ordinary `AgentNativeTool` beans), `GlobalExceptionHandler` maps the new `ApiErrorCode` values, `SecurityConfig` gains this change's own row `/api/v1/scheduled-jobs/**` authenticated in the authorization matrix of `add-keycloak-login` (design D13), `StartupLogConfig` reports the count of active jobs, `application.yaml` gains `app.scheduler.jobs.*` and `app.scheduler.notify.*`, each read from its environment variable with its default, and the `ascend-agent` service of `compose.yaml` passes each one as `${ENV:-default}` (owner rule 98 of 2026-10-08, design D14).
- Database: one Flyway versioned SQL migration `V<n>__scheduled_jobs.sql` (`scheduled_job`, `scheduled_job_firing`, and the six pairs of the source `scheduled_job` inserted into `owner_notification_kind` of `add-shared-scheduler`, answer 93 of 2026-10-08), `<n>` the next free version at implementation time. Final jobs and firings beyond the newest 50 per job are deleted by two entries of the one retention task `record-retention` of `add-shared-scheduler` (answer 89.7 of 2026-10-08). Both tables carry `tenant_id VARCHAR(64) NOT NULL`, written from `TenantContext.currentTenantId()` of `add-keycloak-login`, with no foreign key to `tenants(id)`. The foreign keys of both tables to `tenants(id)` are added by the migration of `add-tenant-isolation` (company, build group 5) later, because under the owner rule of 2026-10-04 this personal change lands before that company change (the owner decision of 2026-10-03 that put them here is superseded by the owner build order of 2026-10-04).
- REST: `/api/v1/scheduled-jobs/**`, with new `ApiErrorCode` values.
- Docs: the job sections of `docs/SCHEDULING.md`, `apps/ascend-agent/AGENTS.md`, the module README, `apps/ascend-agent/docs/CONFIGURATION.md`, `docs/OBSERVABILITY.md`, Bruno requests under `docs/api/request/AscendAI/`, and two new e2e specs in `apps/ascend-agent/e2e/` (next free numbers at implementation time), a deterministic one over the Bruno folder `ascend-agent/testing/scheduled-jobs-api/` that needs no AI model (job management and reminder firings), and an AI-run one for task firings and the agent job tools, which runs against the agent with its shipped configuration (owner answer 70.4 of 2026-10-04), both listed in `docs/E2E_RUN_SCENARIOS.md` and run as the Keycloak e2e users of tenant `default` of `add-keycloak-login` (owner answer 67.4 of 2026-10-04).
- Backwards compatibility: with no jobs created, nothing fires and no notification is written. `POST /api/v1/ai/prompt` keeps its request and response.

## Relevant Skills

Load these from `.agents/skills/` before implementing this change:

- `springboot-patterns` and `java-coding-standards` for the services, the controller, configuration properties and the tests
- `database-migrations` and `postgres-patterns` for the Flyway migration, the conditional updates and the indexes
- `backend-patterns` for at most once firings, idempotent handlers and retries
- `api-design` for `/api/v1/scheduled-jobs`, the status codes, `ETag` and `If-Match`, cursor pagination and the problem detail codes
- `security-review` for agent created jobs, prompt injection through scheduled prompts, tool limits and tenant scoping
- `observability-and-logging` for the metrics and the log lines
- `tdd-workflow` for writing each rule's test first with a controllable clock
- `e2e-runbooks` for the new e2e spec
- `markdown-writer` for `docs/SCHEDULING.md` and the AGENTS.md and README updates
