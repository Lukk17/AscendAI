## Context

See proposal.md for why. This section holds only the facts the decisions rest on.

### What the earlier changes give

- `add-shared-scheduler` gives the one persistent, cluster safe scheduler on db-scheduler 16.12.0 with the execution table `scheduler_execution` (its D1 and D5), per record executions whose record and execution change in one transaction (its D3), the registration contract of system tasks with names in `SchedulerTaskName` (its D2), `CronRule` with five field cron in a named zone and fixed daylight saving rules (its D4), the one injected `Clock` and the `ManualScheduler` test support (its D6), the one retention task `record-retention` with its registered `RetentionEntry` beans (its D15, answer 89.7 of 2026-10-08), and the owner notification store: `owner_notification`, `OwnerNotificationService`, the `OwnerNotificationChannel` port, delivery retries, `GET /api/v1/notifications`, notification retention and erasure (its D7 to D11). This change adds the pairs of the source `scheduled_job` with the kinds `reminder`, `result`, `message`, `failure`, `paused` and `missed` to the table `owner_notification_kind` of that store in its own migration (D4, answer 93 of 2026-10-08). Its inventory (D2) lists this change's `scheduled-job` executions.
- `add-deployment-modules` gives the module catalog, `ASCEND_MODULES`, `@ConditionalOnModule`, `ModuleState` and the tenant module grant. The shared scheduler engine, its system tasks and the notification store are `core-chat`, always on and never a switchable module. `add-shared-scheduler` adds the catalog entry `scheduler` only as the name for the assistant's own job features, with an empty `requires` list (its D14). A firing for a tenant that lacks `scheduler` is skipped with the reason `module_denied` (the required edit `add-deployment-modules` lists for this change).
- `add-agent-subagents` gives background runs: a `subagent_run` row per run, a fair semaphore of worker slots with a waiting queue, cost, token and time limits per run (defaults 1.00 US dollar, 200000 tokens, 10 minutes), a run view and `SubagentRunChangedEvent` published after commit, the run REST API under the kind neutral path `/api/v1/runs`, and a finished runs block in the next chat turn of the run's conversation. It owns the run kinds `subagent`, `approval`, `coding`, `scheduled`, `self_review` and `integration`. `add-action-approvals` adds the state `awaiting_approval`, and its gate inside `ChatToolset` pauses a run that calls a tool in the "requires approval" mode.
- `add-agent-skills` owns `ChatToolset`, `AgentNativeTool` and the tool context keys. `add-agent-subagents` owns the tool policy port `TenantToolPolicy`, whose default allows every tool. `add-keycloak-login` gives `TenantContext.currentTenantId()`, which fails closed when no tenant is bound, `TenantContext.runAs` for work without a request, the identity resolved without a token (its D20) and the authorization matrix (its D4). `add-deployment-modules` gives the company extension port `AuditEventPort`, whose default writes one structured INFO log line. `add-agent-soul` gives every run the tenant's personality file first and keeps the user facts file out of background runs.
- `add-openclaw-plugin-host` (service `ascend-openclaw-host`) plans a durable `channel_outbox` that the plugin host reads, background run status messages, and approval prompts sent as a direct message to the owner's linked Discord account. It implements the `discord` channel of the notification port (made there, its D12). `add-flutter-chat-app` leaves push notifications out of scope.
- `upgrade-spring-boot-4` moves every REST error to the RFC 7807 problem detail of its D19 (one `ApiErrorCode` enum, a top level `code`, and an `errors` field on a validation failure).
- The owner decided on 2026-10-02 (confirmed by owner answer 73.1 of 2026-10-06) that there is no existing data to keep, so nothing here migrates or backfills data.

### Owner answers of 2026-10-02 this design follows

- 39.1: keep the per firing cost and token limits, with no time limit per firing.
- 39.2: at least 15 minutes between firings and 200 firings per tenant per day.
- 39.3: a plain reminder sends its text with no model call, and only a job that needs thinking starts a run. So there are two job kinds.
- 39.4: scheduled runs do not see the user facts file. The agent copies the facts a job needs into its prompt.
- 39.5: the shared scheduler engine and the notification store move into `add-shared-scheduler`, and this change keeps only the assistant's own jobs.
- 43: a missed job runs late when its latest missed time is within 1 hour for a recurring job and within 24 hours for a one time job (a one time reminder), and a scheduled run keeps the general background run limit of `add-agent-subagents`. This confirms the defaults of D6 and D7 and closes the open question on the grace periods.

## Goals / Non-Goals

Goals:

- The assistant's jobs as plain records whose schedule has exactly one source of truth.
- A reminder that costs nothing but a database row and a notification.
- Reuse the scheduler, notification, run, limit, approval and status machinery of the sibling changes, adding only what is missing.

Non-Goals:

- The scheduler engine, system task contract, cron rules, clock, notification store and channel port. They are `add-shared-scheduler`.
- Push notifications to the phone, the Discord adapter and the app screens. They belong to `add-flutter-chat-app` and `add-openclaw-plugin-host`, which hold them.
- Calendar or price tools. A morning briefing, a calendar check or a price watch is a prompt plus tools that already exist or are connected later as MCP tools. A job only stores their names.
- Jobs that act for another user, or that message anyone other than the job's own user.
- Schedules more frequent than the shortest interval.

## Decisions

### D1: Module and placement

This change fills the catalog entry `scheduler` that `add-shared-scheduler` added with an empty `requires` list: the entry now covers the job tools, `owner_notify` and `/api/v1/scheduled-jobs`, with `requires: [subagents]` and no `uses` entry. The shared scheduler engine and its system tasks stay `core-chat`, always on, and are never part of this module.

Why no `uses: [channels]`: every message this change sends is an owner notification, and notification storage, delivery and the `OwnerNotificationChannel` port are `core-chat` (`add-shared-scheduler` D14). The Discord channel of `add-openclaw-plugin-host` is found through that port, and an approval prompt of a gated tool in a scheduled run goes through the approval channels of `add-action-approvals`. No class of this change refers to a class of the plugin host's module, so the module rule of `add-deployment-modules` D6 needs no `uses` entry.

Every bean of this change carries `@ConditionalOnModule("scheduler")` of `add-deployment-modules`: the job service, the controller, the custom task `scheduled-job`, the two retention entries of D15a, the five agent tools and the outcome listener. With the module off, none of them exists, no job tool is offered, and executions of the task name `scheduled-job` left in the table fall under the unresolved task rule that `add-shared-scheduler` records. There is no `app.scheduler.enabled` flag.

The firing handler asks `ModuleState.effectiveFor(tenant)` whether the job's tenant has the `scheduler` grant. When it does not, the firing ends `refused_module_denied` with the reason `module_denied`, starts nothing and sends nothing, and the job keeps its schedule, so a grant given later lets the next firing run.

### D2: Two job kinds

A job has the kind `reminder` or `task` (owner answer 39.3):

- `reminder`: the stored text is the message. A firing creates one owner notification of kind `reminder` with the job name as title and the text as body, and starts no run and calls no model. Tools, model, limits and delivery mode are not set. The text is at most 4000 characters, the notification body limit, so it is never cut. A late reminder (trigger `catch_up`) gets one added line naming the scheduled time in the job's zone and how late it is.
- `task`: the stored text is the prompt of a run of kind `scheduled` (D10). Tools, limits and delivery mode are set, and model is optional.

The agent picks the kind when it creates a job: "remind me at 15:00 to call the bank" is a `reminder`, "every morning summarise my calendar and the weather" is a `task`. The tool description says so in fixed text. Why two kinds: most reminders need no thinking, and a model call per reminder costs money and adds a provider outage as a way to miss a reminder.

### D3: Per job executions on the shared scheduler

Each job that is `active` has one execution `scheduled-job/<jobId>` on the shared scheduler, a per record execution of `add-shared-scheduler` D3: the job row is the source of truth, the execution only says when to look next, and every change to the job (new schedule, pause, resume, cancel, completion) reschedules, removes or creates the execution in the same transaction. A startup check recreates the execution of any `active` job that has none and removes executions of jobs that are not `active`, one log line per repair. Several agent instances may start at once (answer 87 of 2026-10-08), so the check creates a missing execution only if it does not exist yet (the primary key `(task_name, task_instance)` of `scheduler_execution` refuses a second one, and the refusal counts as repaired) and removes a stray one with a conditional delete, so two instances that check at the same time repair nothing twice and never fail each other.

### D4: The tables

Migration `V<n>__scheduled_jobs.sql`. Every constraint and index has an explicit name. Tenant columns are `VARCHAR(64) NOT NULL`, the same type as `tenants.id`, which `add-tenant-isolation` (company) creates later.

The same migration adds this change's notification pairs to the owner notification store of `add-shared-scheduler` (answer 93 of 2026-10-08, review item S3-8). That change keeps the allowed pairs in the table `owner_notification_kind (source, kind)`, which `owner_notification` refers to through the foreign key `owner_notification_kind_fk`, and its first migration holds no pair of a later change. This migration runs `INSERT INTO owner_notification_kind (source, kind) VALUES ('scheduled_job', 'reminder'), ('scheduled_job', 'result'), ('scheduled_job', 'message'), ('scheduled_job', 'failure'), ('scheduled_job', 'paused'), ('scheduled_job', 'missed') ON CONFLICT DO NOTHING`.

Foreign keys: the owner decision of 2026-10-03 put the tenant foreign keys in this migration because this change was to land after `add-tenant-isolation` (superseded by the owner build order of 2026-10-04). Both `tenant_id` columns are written from `TenantContext.currentTenantId()` of `add-keycloak-login`, or from the job row inside `TenantContext.runAs` for a firing. Under the owner rule of 2026-10-04 this personal change lands before that company change, so the `tenants` table does not exist yet. This migration adds the foreign key from `scheduled_job_firing.job_id` to `scheduled_job(id)` `ON DELETE CASCADE`, and the foreign keys from `scheduled_job.tenant_id` and `scheduled_job_firing.tenant_id` to `tenants(id)` are added by the migration of `add-tenant-isolation`, which runs after these tables exist. `run_id` and `notification_id` of a firing stay without a foreign key, because the run retention of `add-agent-subagents` and the notification retention of `add-shared-scheduler` delete those rows on their own schedule, and the firing history keeps the id as a plain value.

`scheduled_job`:

| Column | Type | Notes |
| :--- | :--- | :--- |
| `id` | `UUID` primary key | Also the execution's `task_instance` |
| `tenant_id`, `user_id` | `VARCHAR(64)`, `VARCHAR(255)` not null | The job acts for and notifies this user |
| `kind` | `VARCHAR(8)` not null | Check in `reminder`, `task` |
| `origin` | `VARCHAR(8)` not null | Check in `owner`, `agent` |
| `created_by` | `VARCHAR(255)` null | Set to null by user erasure of the creator when it is not the job's user |
| `origin_conversation_id`, `origin_request_id` | `VARCHAR(255)`, `VARCHAR(64)` null | Text, no foreign key. Cleared when the conversation is deleted |
| `name` | `VARCHAR(100)` not null | Partial unique `(tenant_id, user_id, name) WHERE state IN ('active','paused')` |
| `prompt` | `TEXT` not null | The reminder text or the run's prompt. Check `char_length(prompt) BETWEEN 1 AND 8000`, and at most 4000 for a `reminder` |
| `schedule_type` | `VARCHAR(8)` not null | Check in `once`, `cron`, `interval` |
| `run_at` | `TIMESTAMPTZ` null | For `once` |
| `cron` | `VARCHAR(100)` null | For `cron`, five fields |
| `interval_seconds` | `INTEGER` null | For `interval` |
| `time_zone` | `VARCHAR(64)` not null | IANA zone |
| `starts_at`, `ends_at` | `TIMESTAMPTZ` null | |
| `max_firings` | `INTEGER` null | Check greater than 0 |
| `tools` | `JSONB` null | Array of tool names, for `task` |
| `model` | `VARCHAR(160)` null | `<provider>:<model>`, for `task` |
| `limit_cost_usd`, `limit_tokens` | `NUMERIC(12,6)`, `BIGINT` null | For `task` |
| `delivery_mode` | `VARCHAR(16)` null | Check in `every_run`, `on_notify`, for `task` |
| `state` | `VARCHAR(16)` not null | Check in `active`, `paused`, `completed`, `cancelled` |
| `paused_reason` | `VARCHAR(24)` null | Check in `owner`, `agent`, `failures`, `owner_unavailable`, `policy` |
| `firing_count`, `consecutive_failures` | `INTEGER` not null default 0 | |
| `last_fired_at`, `final_at` | `TIMESTAMPTZ` null | `final_at` drives retention |
| `created_at`, `updated_at` | `TIMESTAMPTZ` not null | |
| `version` | `BIGINT` not null | Optimistic lock and `ETag` |

A check constraint ties the schedule columns to `schedule_type` (exactly the columns of its type are set). A second check ties the task columns to `kind`: for `task`, `tools`, `limit_cost_usd`, `limit_tokens` and `delivery_mode` are not null, and for `reminder`, `tools`, `model`, `limit_cost_usd`, `limit_tokens` and `delivery_mode` are null. Indexes: `(tenant_id, user_id, created_at DESC)`, `(tenant_id, state)` and `(final_at) WHERE state IN ('completed','cancelled')`.

The next firing time is not a column. The job view reads it from `scheduler_execution` (`task_name = 'scheduled-job' AND task_instance = id::text`) in the same query, so the time a job will fire is stored once.

`scheduled_job_firing`: `id UUID`, `job_id UUID` (foreign key `ON DELETE CASCADE`), `tenant_id`, `scheduled_for TIMESTAMPTZ`, `fired_at TIMESTAMPTZ`, `lateness_ms BIGINT`, `trigger` (check in `schedule`, `manual`, `catch_up`), `outcome` (check in the eight outcomes of the `scheduled-job-execution` spec), `run_id UUID` null, `notification_id UUID` null (the reminder or missed notice it created), `run_state VARCHAR(16)` null, `failure_reason VARCHAR(64)` null. Unique `(job_id, scheduled_for, trigger)`, which makes a second execution of the same scheduled time a no-op (D8). Indexes `(job_id, fired_at DESC)` and `(tenant_id, fired_at) WHERE outcome IN ('started','delivered')` for the daily limit.

Entities follow the agent's Spring Data JDBC style (`@Table`, `@Id`, no JPA) with native `@Query` methods for the conditional updates and cursor pages.

### D5: The schedule calculator

`ScheduleCalculator.next(job, after)` returns the next firing instant strictly after `after`, or empty:

- `once`: `run_at` when it is after `after` and the job has not fired, else empty.
- `cron`: `CronRule.next(cron, zone, after)` of `add-shared-scheduler`.
- `interval`: the anchor is `starts_at` or `created_at`. The next time is `anchor + k * interval` for the smallest `k` that is after `after`. Elapsed time only, so daylight saving never moves it.
- Then the bounds: before `starts_at` means `starts_at` aligned to the schedule, after `ends_at` or past `max_firings` means empty.

Validation at create and update uses the same calculator: a first firing must exist and be within the horizon, the next 50 firings must be at least the shortest interval apart (15 minutes, owner answer 39.2), `ends_at` after `starts_at`, and a local `once` time is resolved in the job's zone by `ZonedDateTime.ofLocal`, which applies the daylight saving rules of the `shared-scheduler` spec. Validation messages go into the problem detail's `errors` field on REST and into the tool result for the agent.

### D6: Missed firings: fire once if still useful, otherwise record and tell

Recommended rule, as the spec states it: all missed times of one job collapse into one decision, the job fires once late when its latest missed time is inside its grace, otherwise it records `skipped_missed`, and a missed one time job becomes a `missed` notification instead of vanishing. The grace is 1 hour for recurring jobs and 24 hours for one time jobs (owner answer 43), read from `jobs.missed-grace-recurring` and `jobs.missed-grace-once` by the job's schedule type. A job has no grace of its own and no column for one (answer 93 of 2026-10-08), so the owner changes the grace for every job at once in the configuration.

Why this rule:

- A recurring job's value is tied to its time. A morning briefing two hours late is mostly noise, and the next one comes tomorrow. Inside an hour it is still useful, and the run is told how late it is so it can say so.
- A one time reminder has no "next one", so a late reminder within a day is better than none, and beyond that the owner must at least learn that it was missed. Silence is the one outcome the rule forbids.
- Collapsing into one decision bounds the cost of an outage. A job that fires every 15 minutes and missed 12 times starts at most one run, never 12.

Alternatives considered: run every missed firing (rejected, it multiplies model cost after every outage and repeats the same briefing), always run once whatever the delay (rejected, a stale briefing at noon and a reminder a week late are wrong answers), never run late (rejected, a short restart during a deployment would drop every job due in that minute).

The shared scheduler's own behaviour gives the "once" part for free (an overdue execution is picked once and rescheduled from completion). The grace check is step 3 of D8.

### D7: Limits

Owner answers 39.1 and 39.2. Per job, for kind `task`: a cost limit and a token limit per firing, defaults 0.25 US dollars and 100000 tokens, never above `app.subagents.limits.max-cost-usd-per-run` and `app.subagents.limits.max-tokens-per-run`, enforced by the run checkpoints of `add-agent-subagents`. A job has no time limit of its own. A run of kind `scheduled` keeps the general background run limit that `add-agent-subagents` gives every background run (`app.subagents.limits.max-duration-per-run`, default 10 minutes, owner answer 43), because a run with no deadline could hold a worker slot and block its job's next firing through the overlap rule forever.

Per tenant and user: at most 20 `active` plus `paused` jobs per user and 100 per tenant, at least 15 minutes between two firings, at most 200 firings per tenant per UTC day (both reminders and runs count, because both are work the owner sees), a prompt of at most 8000 characters (4000 for a reminder), at most 5 jobs created per chat request, a first firing within 366 days, and an automatic pause after 3 failed firings in a row. The reminder text size is not a setting: it is the 4000 character body limit of the owner notification store of `add-shared-scheduler`, so a reminder is never cut (answer 93 of 2026-10-08).

Several agent instances (answer 87 of 2026-10-08, CANON 26.1): the counted limits are counted from Postgres rows, never from memory, and each count and the write it guards run in one transaction under a Postgres transaction advisory lock, so two instances cannot both pass a count that only one of them may pass. A create or resume takes the lock keyed by the tenant and the user before it counts the `active` and `paused` jobs of the user and of the tenant, and a firing takes the lock keyed by the tenant before it counts the day's firings (D8 step 4). The creations per chat request are counted in the request scope, because one request runs on one instance. The messages per run of `owner_notify` are counted from the `message` notifications that carry the run id.

### D8: What one firing does

The custom task `scheduled-job` runs `ScheduledJobFiringHandler.fire(jobId, scheduledFor)`. In one transaction:

1. Load the job with a row lock. Not `active` means stop and remove the execution (a race with pause or cancel).
2. Insert the firing row for `(job_id, scheduled_for, trigger)` with `ON CONFLICT DO NOTHING`. No row inserted means this scheduled time was already handled by an earlier execution (a dead execution revived by the library), so stop and reschedule.
3. Decide the trigger: lateness up to `app.scheduler.jobs.late-threshold` (default 2 minutes, covering the 10 second poll and a slow start) is `schedule`. More than that and within the grace of the job's schedule type (D6) is `catch_up`. Beyond the grace the firing is `skipped_missed` (D6).
4. Check, in this order, each ending the firing with its outcome: the tenant has the `scheduler` module grant (`refused_module_denied`, D1), the user can be resolved and is enabled (`refused_owner_unavailable`, job paused), the tenant's daily limit, counted under the tenant's transaction advisory lock of D7 (`refused_limit`), and for a `task` the previous firing's run is final, read from its `subagent_run` row (`skipped_overlap`).
5. For a `reminder`: create the `reminder` notification through `OwnerNotificationService.create(...)` in this transaction and record outcome `delivered` with the notification id. For a `task`: start the run through `ScheduledRunStarter.start(...)`, the port that `add-agent-subagents` implements (made there, its D14a): it inserts the run row in this same transaction and starts the run's thread after commit. A refusal by the run service (waiting queue full) ends the firing as `failed_to_start` with the reason.
6. Update the job: `firing_count`, `last_fired_at`, and `completed` when no next time exists.
7. Return the completion: reschedule to `ScheduleCalculator.next(job, now)`, or remove.

The handler finishes in milliseconds, because a run works on its own thread and a reminder is one insert. So the library's heartbeat and dead execution path almost never applies to job firings, and step 2 covers the case where it does. When the transaction of a reminder fails, nothing is stored, the scheduler records a failed execution, and the library's failure handling runs the execution again.

`POST /api/v1/scheduled-jobs/{id}/trigger` calls the same handler with trigger `manual` and `scheduledFor` equal to now, without touching the execution. It runs only an `active` job. A manual run of a `paused` job answers 409 with the code `scheduled_job_state_conflict`, the same answer as a manual run of a final (`completed` or `cancelled`) job, and records no firing (owner answer 75.3 of 2026-10-07).

### D9: Tenant and identity inside a firing

A firing has no HTTP request, so no token. The handler binds the job's tenant, read from the job row, on the scheduler thread with `TenantContext.runAs` of `add-keycloak-login` before any other step, so every repository call inside reads it through `TenantContext.currentTenantId()`. It resolves the job's user to an identity (enabled flag, roles, tenant, and the extensions that company work registers later through `IdentityContributor`) through the offline resolver of `add-keycloak-login` (its D20, the same resolver the plugin host uses for a linked platform account) (split of 2026-10-04, owner rule of 2026-10-04: nothing personal depends on company work). The run service then binds that identity on the run's thread, as it does for a chat caller. Resolution failure or a disabled user ends the firing with `refused_owner_unavailable` and pauses the job, so a disabled Keycloak account stops a user's jobs. Nothing ever falls back to a guessed tenant: with no tenant bound, `TenantContext.currentTenantId()` throws (fail closed). In the personal deployment every job carries the tenant `default`.

### D10: The scheduled run

A firing of a `task` starts a run of kind `scheduled`, a kind `add-agent-subagents` owns:

- No parent, root equal to itself, depth 1, background, the job's tenant and user, no conversation (the run reports through notifications, D11), `scheduled_job_id` set, no definition, so `subagent_name`, `subagent_origin` and `definition_version` are null.
- Instructions: the tenant's personality file first, through `PromptLayout` of `add-agent-soul`, then the global system prompt, then a fixed footer of this change in the dynamic block: the job name, the scheduled time in the job's zone, the start time, the lateness when the trigger is `catch_up`, the delivery mode, and in mode `on_notify` that only `owner_notify` reaches the owner. The stored prompt is the run's first user message.
- No user facts file (owner answer 39.4), the same choice `add-agent-soul` made for every background run. The agent writes the facts a job needs (a city, a threshold, a name) into the prompt when it creates the job. The fixed description of `scheduled_job_create` tells the model so: "The job's run will not see the user's facts file. Write every fact the job needs into the prompt."
- Model: the job's model, checked against the run model allowlist of `add-agent-subagents` D11 at creation and again at firing, or the deployment's default chat model.
- Limits: the job's cost and token limits, which are never above `app.subagents.limits.max-cost-usd-per-run` and `max-tokens-per-run`, enforced by the same run checkpoints, plus the general run limit `app.subagents.limits.max-duration-per-run` (D7).
- Tools: computed at firing time from the stored names as the `scheduled-job-execution` spec says. They are assembled by `ChatToolset` for a context that carries `subagent_run_id`, `subagent_run_kind = scheduled` and `scheduled_job_id` (tool context keys made in `add-agent-subagents`, its D2), so the tool policy port `TenantToolPolicy` of `add-agent-subagents` (default allows every tool, `add-tenant-policy` registers its tenant allow-list later) and the approval gate of `add-action-approvals` apply unchanged. `Task` may be stored, so a job can delegate to a subagent at depth 2 within the job's budget.
- Approvals: a call to a gated tool pauses the run in `awaiting_approval` (approvals D6). The owner gets the approval prompt through the approval channels (REST, the app, Discord). The next firing of the same job meanwhile is `skipped_overlap`. A restart closes the paused run with `AGENT_RESTARTED`, which counts as a failed firing.

### D11: From run to notification

`ScheduledRunOutcomeListener` listens to `SubagentRunChangedEvent` after commit, for runs of kind `scheduled` that reached a final state. With several agent instances (answer 87 of 2026-10-08) the event is published on the instance that wrote the final state: the instance that ran the run, the one whose orphan sweep of `add-agent-subagents` closed it, or the one that served a cancel. So the listener always runs where the final state was written, and its writes are conditional updates on the firing and job rows, safe beside any other instance:

- It writes `run_state` onto the firing.
- `done`: resets `consecutive_failures`, and in mode `every_run` creates a `result` notification with the run's result.
- `failed`, or `cancelled` by anyone other than the owner: increments `consecutive_failures` with a conditional update, pauses the job with reason `failures` when it reaches the limit, and creates one `failure` or `paused` notification.

`owner_notify` (D12) creates `message` notifications while the run works, so a price watch reaches the owner even if its run later fails. Every notification of this change has source `scheduled_job`, the job name as title, and the job, firing and run ids.

### D12: The agent tools

Five `AgentNativeTool` beans in `service/schedule/tool/`:

- `scheduled_job_create`, `scheduled_job_list`, `scheduled_job_update`, `scheduled_job_cancel` return their callback only when the tool context has no `subagent_run_id`, which is the main chat (and a channel conversation, which is a main chat turn). The same rule `add-agent-subagents` uses for `subagent_definition_write`.
- `owner_notify` returns its callback only when `subagent_run_kind` is `scheduled`.

The rules of the `scheduled-job-tools` spec are enforced in `ScheduledJobService`, which the REST controller uses too, with a second validation step for origin `agent` (the D7 pattern of `add-agent-subagents`): for a `task`, explicit tools that are a subset of the calling request's tool list (read from the tool context, the same list `ChatToolset` computed for the turn), never a scheduling tool or a configuration writing tool, and the model allowlist. For a `reminder`, tools, model, limits and delivery mode must be absent. For both, the per request creation counter kept in the request scope.

No approval at creation, by owner decision of 2026-10-02. Why that is acceptable: a job can never do more than the conversation that created it could do directly, a scheduled run cannot create jobs, every job is bounded by the shortest interval, the per firing cost and token limits, the daily firing limit and the active job limits, gated tools still wait for the owner at every firing, and every creation is an audit event and a log line. The remaining threat is prompt injection in a fetched page that makes the model create a costly or chatty job. It is bounded, not prevented, and the risk section says so.

Tool descriptions are fixed text, so the tool list bytes do not change between requests and the provider prompt cache stays warm.

### D13: REST, errors and security

- `ScheduledJobController` under `/api/v1/scheduled-jobs`, contract in the `scheduled-jobs` spec. Cursor pagination encodes `(created_at, id)` as an opaque base64 cursor, the same as the run list. The job `ETag` is its `version`.
- New `ApiErrorCode` values, added by this change to the enum of `upgrade-spring-boot-4` D19: `scheduled_job_not_found` (404), `scheduled_job_limit_reached` (409), `scheduled_job_state_conflict` (409, also the answer to a manual run of a paused or final job, D8), `scheduled_job_version_mismatch` (412). Validation failures use the existing `validation` code with `errors`. A tenant without the `scheduler` grant gets the `module_denied` 403 of `add-deployment-modules`.
- Role rules: `add-keycloak-login` lands before this change (build group 3, right after `upgrade-spring-boot-4` (split of 2026-10-04, owner rule of 2026-10-04: nothing personal depends on company work)), and its D4 table of later changes lists this change's row, which this change adds to the matrix itself:

  | Path | Rule |
  |---|---|
  | `/api/v1/scheduled-jobs/**` (`add-scheduled-tasks`) | authenticated, scoped by the controller |

  So this change adds no interim rule and no `app.security.enabled` branch, which that change deletes. It adds its own row in `SecurityConfig`, the controller scopes by user, with `ADMIN` seeing every job of the tenant, and a security slice test proves the row (task 3.4). This change adds no other agent endpoint.

### D14: Configuration

`ScheduledJobProperties` binds `app.scheduler.jobs` and `app.scheduler.notify`. The keys `app.scheduler.default-time-zone`, `app.scheduler.system-tasks.*` and `app.notifications.*` belong to `add-shared-scheduler`.

Every value with a default is a setting (owner rule 98 of 2026-10-08): `application.yaml` writes `key: ${ENV:default}`, `ScheduledJobProperties` carries the same default in code, and the `ascend-agent` service of `compose.yaml` writes `- ENV=${ENV:-default}`. The environment variable is Spring Boot's canonical form of the full property name (`app.scheduler.` in front of each key below).

| Key | Environment variable | Default | Meaning |
| :--- | :--- | :--- | :--- |
| `jobs.default-time-zone` | `APP_SCHEDULER_JOBS_DEFAULTTIMEZONE` | `${app.scheduler.default-time-zone}` (`Europe/Warsaw`) | Zone of a job created without one |
| `jobs.max-active-per-user` | `APP_SCHEDULER_JOBS_MAXACTIVEPERUSER` | 20 | `active` plus `paused` jobs per user |
| `jobs.max-active-per-tenant` | `APP_SCHEDULER_JOBS_MAXACTIVEPERTENANT` | 100 | The same per tenant |
| `jobs.min-interval` | `APP_SCHEDULER_JOBS_MININTERVAL` | `15m` | Shortest gap between two firings |
| `jobs.horizon` | `APP_SCHEDULER_JOBS_HORIZON` | `366d` | Latest first firing |
| `jobs.max-prompt-chars` | `APP_SCHEDULER_JOBS_MAXPROMPTCHARS` | 8000 | Prompt size of a `task` |
| `jobs.max-firings-per-tenant-per-day` | `APP_SCHEDULER_JOBS_MAXFIRINGSPERTENANTPERDAY` | 200 | Firings that started a run or delivered a reminder, per UTC day |
| `jobs.max-creates-per-request` | `APP_SCHEDULER_JOBS_MAXCREATESPERREQUEST` | 5 | Agent creations per chat request |
| `jobs.default-cost-usd` | `APP_SCHEDULER_JOBS_DEFAULTCOSTUSD` | 0.25 | Cost limit of one `task` firing |
| `jobs.default-tokens` | `APP_SCHEDULER_JOBS_DEFAULTTOKENS` | 100000 | Token limit of one `task` firing |
| `jobs.missed-grace-recurring` | `APP_SCHEDULER_JOBS_MISSEDGRACERECURRING` | `1h` | Grace of every `cron` and `interval` job |
| `jobs.missed-grace-once` | `APP_SCHEDULER_JOBS_MISSEDGRACEONCE` | `24h` | Grace of every `once` job |
| `jobs.late-threshold` | `APP_SCHEDULER_JOBS_LATETHRESHOLD` | `2m` | Lateness that makes a firing `catch_up` |
| `jobs.failures-before-pause` | `APP_SCHEDULER_JOBS_FAILURESBEFOREPAUSE` | 3 | Failed firings in a row before the automatic pause |
| `jobs.firing-history` | `APP_SCHEDULER_JOBS_FIRINGHISTORY` | 50 | Firings kept per job by the retention entry `scheduled-job-firing` of D15a |
| `jobs.retention` | `APP_SCHEDULER_JOBS_RETENTION` | `30d` | Age of a final job at which the retention entry `scheduled-job` of D15a deletes it |
| `jobs.list.default-limit` | `APP_SCHEDULER_JOBS_LIST_DEFAULTLIMIT` | 20 | Page size of `GET /api/v1/scheduled-jobs` when no `limit` is sent |
| `jobs.list.max-limit` | `APP_SCHEDULER_JOBS_LIST_MAXLIMIT` | 100 | Largest `limit` the job list accepts |
| `notify.max-messages-per-run` | `APP_SCHEDULER_NOTIFY_MAXMESSAGESPERRUN` | 3 | `owner_notify` calls per run |

`jobs.default-time-zone` stays derived from the deployment zone of `add-shared-scheduler`: `application.yaml` writes `${APP_SCHEDULER_JOBS_DEFAULTTIMEZONE:${app.scheduler.default-time-zone}}`, and the compose line nests the zone's own variable, `- APP_SCHEDULER_JOBS_DEFAULTTIMEZONE=${APP_SCHEDULER_JOBS_DEFAULTTIMEZONE:-${APP_SCHEDULER_DEFAULTTIMEZONE:-Europe/Warsaw}}`, so the job zone follows the deployment zone unless the owner sets it on purpose.

The application refuses to start when a value is zero or negative, a zone is unknown, `jobs.default-cost-usd` is above `app.subagents.limits.max-cost-usd-per-run`, `jobs.default-tokens` is above `app.subagents.limits.max-tokens-per-run`, a grace is above 7 days, `jobs.min-interval` is below one minute, `jobs.max-prompt-chars` is above 8000 (the prompt check of D4), or `jobs.list.default-limit` is greater than `jobs.list.max-limit`.

Values that stay constants, because they are not operational: the column sizes and checks of D4 (name 1 to 100 characters, the prompt check of 1 to 8000 characters, `VARCHAR` widths, schema constraints that only a migration can change), the reminder and `owner_notify` message size of 1 to 4000 characters (the body check of the notification store of `add-shared-scheduler`), the sample of the next 50 firings that the shortest gap check of D5 reads (a correctness rule of the validation, not tuning), the startup guard ceilings above (a grace of at most 7 days, a shortest interval of at least one minute), the task name `scheduled-job`, the retention entry names, the error codes, the enum values, the notification source and kinds, and the metric names. The 10 second poll of the scheduler is `db-scheduler.polling-interval` of `add-shared-scheduler`. The rows of every setting of this table go into `apps/ascend-agent/docs/CONFIGURATION.md` (task 1.5).

### D15: Audit, erasure and export

`ScheduledJobService` and the firing handler record events through `AuditEventPort` of `add-deployment-modules`, whose default writes one structured INFO log line, with new actions (made in `add-audit-and-gdpr-compliance`, which registers its `AuditRecorder` backed implementation later): `SCHEDULED_JOB_CREATED`, `SCHEDULED_JOB_UPDATED` (details hold which fields changed, and a state change to paused or active), `SCHEDULED_JOB_CANCELLED`, `SCHEDULED_JOB_TRIGGERED` and `SCHEDULED_JOB_FIRED` (outcome is the firing outcome). Details hold the job id, kind, origin, schedule type and firing id, never the prompt or a result. Because the audit write is asynchronous and may be lost, the job and firing rows stay the source of truth.

Erasure and export of jobs are added by `add-audit-and-gdpr-compliance` (company, build group 5) later, which owns erasure and export (dependency fix of 2026-10-05): user erasure deletes the user's jobs (and with them their firings) and their executions in `scheduler_execution`, and sets `created_by` to null where the user created a job for someone else, tenant erasure does the same for the tenant, and user export includes the user's jobs and firings. Cancelling a job through `ScheduledJobService` already removes its execution, so that change needs no edit here. The notifications follow `OwnerNotificationErasure` of `add-shared-scheduler`.

### D15a: Retention through the one retention task

Answer 89.7 of 2026-10-08: this change has no retention task of its own and no delete on insert. It registers two `RetentionEntry` beans with the one retention task `record-retention` of `add-shared-scheduler` (its D15, default cron `15 * * * *` in `UTC`), both with `@ConditionalOnModule("scheduler")`, so with the module off nothing of this change is deleted:

- `scheduled-job`: the table `scheduled_job`, the time column `final_at`, the age `jobs.retention` (default 30 days) and the fixed condition that the job is `completed` or `cancelled`. A job that is not final is never deleted. Its firings go with it through the foreign key `ON DELETE CASCADE`.
- `scheduled-job-firing`: the table `scheduled_job_firing`, with the keep-newest rule "keep the newest `jobs.firing-history` (default 50) rows per `job_id`", ordered by `fired_at`.

The firings endpoint and `scheduled_job_list` return at most the newest `jobs.firing-history` firings, so the history a reader sees is the same as with a cap on insert, also before the task ran. `record-retention` runs on one agent instance per firing on the shared scheduler and deletes by age and count, which is safe to repeat (answer 87).

### D16: Metrics, logs and traces

Names follow `add-observability` D2 and D5, singular domain first, dotted and lower case, as `add-agent-skills` D14 does:

| Metric | Type | Tags |
| :--- | :--- | :--- |
| `schedule.jobs` | gauge | `kind`, `state`, `origin` |
| `schedule.job.changes` | counter | `source`, `action`, `outcome` |
| `schedule.firings` | counter | `kind`, `trigger`, `outcome` |
| `schedule.firing.lateness` | timer | none |
| `schedule.jobs.paused` | counter | `reason` |

The `scheduler.*` and `notification.*` metrics are `add-shared-scheduler`'s.

Logs: the firing handler adds `scheduled_job_id` and `firing_id` to the MDC that the scheduler thread already carries, and the run's own MDC keys follow from `add-agent-subagents`. Prompts, reminder texts and results only at DEBUG. The startup banner block of the scheduler gains the count of active jobs by kind.

Traces: each firing is an `Observation` named `schedule.firing`, a child of the `scheduler.execution` observation, and its run's `subagent.run` observation is its child.

## Required edits to other changes

This change does not edit any other change. Each edit below was asked of the named change by its owner. Every one of them is now made there, checked on 2026-10-03 and noted under its heading. A task here that uses an edit of an earlier change uses it as applied, and tasks.md names that change. An edit that a later change or a company change carries is that change's own work, and no task here waits for it (owner rule of 2026-10-04, dependency fix of 2026-10-05).

### `add-shared-scheduler`

1. Its inventory lists `scheduled-job` (one execution per job), and its notification store allows source `scheduled_job` with the kinds `reminder`, `result`, `message`, `failure`, `paused` and `missed`. Made in that change on 2026-10-02. Changed by answers 89.7 and 93 of 2026-10-08: final job retention and the firing history cap are the entries `scheduled-job` and `scheduled-job-firing` of its one retention task `record-retention` (D15a), not a system task `scheduled-job-retention`, and the six pairs of the source `scheduled_job` are inserted into its table `owner_notification_kind` by this change's own migration (D4), not by its first migration.

### `add-deployment-modules`

Made in that change (checked 2026-10-03, its D3 table row `scheduler` and its section for this change).

1. The catalog entry `scheduler`, added by `add-shared-scheduler` with an empty `requires` list, is filled by this change with the job tools, `owner_notify` and `/api/v1/scheduled-jobs`, `requires: [subagents]`, and no `uses` entry: its earlier `uses: [channels]` is removed, because notification delivery is `core-chat` and this change refers to no class of the plugin host's module (D1). The shared scheduler engine, its system tasks, the notification store and `/api/v1/notifications` are `core-chat`, always on (the edit `add-shared-scheduler` lists).

### `add-agent-subagents`

Made in that change (its D2, D8, D9, D13, D14a, D16, D17, its specs and its row for this change under "Edits other changes asked of this change"), checked on 2026-10-03:

1. Made. Design D13: for its run kind `scheduled`, `subagent_name`, `subagent_origin`, `definition_version` and `conversation_id` may be null, and the check constraint asks for `scheduled_job_id`, `prompt`, `provider` and `model`.
2. Made. Design D13 and D17: a nullable `scheduled_job_id UUID` column with an index, and `scheduledJobId` and `kind` in the run view from its first version. `GET /api/v1/runs` takes a repeatable `kind` filter.
3. Made. Design D14a: the port `ScheduledRunStarter.start(ScheduledRunRequest)` implemented by `SubagentRunService`: it inserts the run row in the caller's transaction, starts the run's thread after commit through the same slots and waiting queue as other background runs, binds the tenant and the identity given in the request, applies the request's cost and token limits and the general run deadline, and refuses with a reason when the waiting queue is full.
4. Made. Design D2: tool context keys `subagent_run_kind` and `scheduled_job_id` next to `subagent_run_id`, so `AgentNativeTool` beans can tell a scheduled run apart.
5. Made. Design D8 and D9: a run of kind `scheduled` gets the fixed footer this change provides instead of a definition body. The four scheduling tools, `owner_notify` outside scheduled runs, `subagent_definition_write`, `personality_propose` and `user_facts_update` are always subtracted from a run.
6. Made. Design D16: the finished runs block skips runs without a conversation.

### `add-agent-soul`

Made in that change on 2026-10-02 (its D9 and its row for this change under "Required edits to other changes"), checked on 2026-10-03:

1. Made. Design D9: runs of kind `scheduled` get the personality block and the reminder like every run, never the user facts file, and are never offered `personality_propose` or `user_facts_update`.

### `add-tenant-policy`

Company, build group 5, lands after this change. It registers its `TenantToolPolicy` implementation (the port of `add-agent-subagents`) later, and no task here waits for it. Made in that change, checked on 2026-10-03 (its D2 and its tool table, and `specs/tool-policy/spec.md`). The test that a new tenant has the five tools off moved there (dependency fix of 2026-10-05).

1. Design D2: the tool allow-list governs `scheduled_job_create`, `scheduled_job_list`, `scheduled_job_update`, `scheduled_job_cancel` and `owner_notify`. They are new tools, off for a new tenant, and the deployment default policy of the personal deployment (`app.policy.default.*`) lists them.
2. A tenant policy that removes a tool does not change stored jobs. The tool is dropped at the next firing (`scheduled-job-execution` spec).

### `add-tenant-isolation`

Company, build group 5, lands after this change, and no task here waits for it. Made in that change, checked on 2026-10-03 (its decisions 13 and 14 and `specs/tenant-isolation/spec.md`). Its decision 14 also states the rule of the owner decision of 2026-10-03 that a change landing after it adds its own foreign keys (superseded by the owner build order of 2026-10-04). This personal change lands before that company change, so the migration of `add-tenant-isolation` adds them (D4), listed in its inbox files of the dependency fix of 2026-10-05, together with the check that one tenant cannot see another tenant's jobs.

1. List `scheduled_job.tenant_id` and `scheduled_job_firing.tenant_id` with the other tenant columns, with no backfill, and add their foreign keys to `tenants.id` in its own migration, because this change now lands before it (D4, owner rule of 2026-10-04).
2. Worker threads: the scheduler thread of a firing binds the job's tenant with `TenantContext.runAs` of `add-keycloak-login` before any other step and fails closed when it cannot. This is already done in this change (D9), so that change needs no code for it.

### `add-keycloak-login`

Moved there from `add-auth-and-identity` with the split of 2026-10-04 (its D4 table, its D20, its tasks 3.7 and its `agent-authentication` and `user-identity` specs).

1. An offline identity resolution for a known user, with no token (its D20): enabled flag, roles, the tenant its extension point of D22 gives (`default` in the personal deployment) and the extensions of its `IdentityContributor` beans (the principal set that company work registers later), failing closed for a disabled or unknown user. Firings use it (D9), and it is the same need `add-openclaw-plugin-host` lists for a linked platform account, so one resolver serves both.
2. Its role matrix: `/api/v1/scheduled-jobs/**` needs an authenticated caller and is scoped by the controller. This change adds the row itself (task 3.4).

### `add-audit-and-gdpr-compliance`

Company, build group 5, lands after this change. It registers its `AuditEventPort` implementation and carries the erasure and export of jobs later, and no task here waits for it. Made in that change, checked on 2026-10-03 (its audit action table, its erasure table, its retention matrix and its `audit-logging`, `data-erasure` and `data-portability` specs). The erasure task moved there (dependency fix of 2026-10-05).

1. `specs/audit-logging/spec.md`: add `SCHEDULED_JOB_CREATED`, `SCHEDULED_JOB_UPDATED`, `SCHEDULED_JOB_CANCELLED`, `SCHEDULED_JOB_TRIGGERED` and `SCHEDULED_JOB_FIRED` to the closed vocabulary, with details that never hold the prompt or a result.
2. `specs/data-erasure/spec.md` and `specs/data-portability/spec.md`: user and tenant erasure delete `scheduled_job` (with its firings) and the matching `scheduler_execution` rows, and user export includes the user's jobs and firings, through `ScheduledJobErasure`, which that change now implements (dependency fix of 2026-10-05). The retention matrix in `docs/COMPLIANCE.md` lists final jobs (30 days).

### `add-usage-metering-and-quotas`

Company, build group 5, lands after this change. It registers its implementations later behind `QuotaGate` and `UsageEventPort` of `add-deployment-modules`, which the run loop of `add-agent-subagents` already calls, with no task here. Made in that change, checked on 2026-10-03 (its request type table, its run quota rule and its `usage-metering` and `quota-enforcement` specs).

1. `specs/usage-metering/spec.md`: add the request type `scheduled` for model calls of runs of kind `scheduled`, so the usage view shows the assistant's own work apart from delegated subagent work. Rows carry the run id and parent run id as the subagents edit already asks. A reminder makes no model call and records no usage.
2. Its quota gate, registered behind `QuotaGate` of `add-deployment-modules`, runs before each model call of a scheduled run exactly as for other runs (the default `AllowAllQuotaGate` allows every call). A refusal ends the run `QUOTA_EXCEEDED`, which this change counts as a failed firing.

### `add-chat-streaming-and-conversations`

That change lands earlier (build group 3), so this step moved here from its task 9.7 by the dependency fix of 2026-10-05 and is this change's task 3.6, plugged into its `ConversationService.delete`, with the e2e row of task 8.8.

1. Conversation delete: set `scheduled_job.origin_conversation_id` to null for the deleted conversation. Jobs are owned by their user, not by a conversation, so they keep running.

### `add-flutter-chat-app`

Lands later (build group 4, position 17) and carries this screen itself, with no task here. Made in that change, checked on 2026-10-03 (its D11, its `specs/flutter-chat/scheduled-jobs/spec.md` and its task group 17).

1. A scheduled jobs screen: list with the kind, detail with the firing history, pause, resume, run now and cancel, using `/api/v1/scheduled-jobs`. The notification list is the edit `add-shared-scheduler` lists.

### Checked, no edit needed

- `upgrade-spring-boot-4`: its D19 already defines the `errors` field, and this change adds its own codes to `ApiErrorCode` the way every sibling change does.
- `add-agent-skills`: the five tools are ordinary `AgentNativeTool` beans, and `ChatToolset` is used unchanged.
- `add-openclaw-plugin-host`: its `discord` channel of the notification port (the edit `add-shared-scheduler` lists) delivers this change's notifications with no edit of its own for this change.
- `add-observability`: this change follows its naming rules and adds its metrics to `docs/OBSERVABILITY.md` itself.

## Risks / Trade-offs

- [Prompt injection makes the model create a costly or chatty job] → subset of the conversation's tools, no scheduling tools in scheduled or subagent runs, shortest interval 15 minutes, cost and token limits per firing, daily firing limit per tenant, active job limits, at most 5 creations per request, gated tools still wait for the owner, audit and a log line per creation, and the owner sees and cancels every job through REST and the app. Bounded, not prevented.
- [The model picks the wrong kind] → a `task` where a `reminder` would do costs one run within its limits, and a `reminder` where a `task` was meant sends the text as written. The tool description gives both examples, and the owner sees the kind in the job view.
- [A paused scheduled run is lost on restart] → it ends `AGENT_RESTARTED`, counts as a failed firing, and the next firing starts fresh. The approval is cancelled by the approvals change, never run late.
- [Many tenants' jobs fire at the same minute, such as 07:00] → firings only start runs, and runs wait in the run queue of `add-agent-subagents`. A full queue ends a firing `failed_to_start`, which is visible and counted. Reminders need no slot.
- [A job needs a fact that changed after creation] → the run sees only the prompt (owner answer 39.4). The owner or the agent updates the prompt through `PATCH` or `scheduled_job_update`.

## Migration Plan

1. This change lands as build group 4, position 12 of the owner build order of 2026-10-04, with the changes it needs applied (proposal), among them `add-keycloak-login`, `add-shared-scheduler`, `add-agent-skills`, `add-agent-subagents`, `add-agent-soul` and `add-action-approvals`. No step waits for a company change. Flyway creates `scheduled_job` and `scheduled_job_firing` and inserts the six pairs of the source `scheduled_job` into `owner_notification_kind`. With no job created, nothing fires.
2. No data to migrate. The owner decided on 2026-10-02 (confirmed by owner answer 73.1 of 2026-10-06) that there is no existing data to keep, which holds only until the first real customer deployment.
3. Rollback: remove `scheduler` from `ASCEND_MODULES` or deploy the previous image. Tables stay and are ignored, and executions of `scheduled-job` fall under the unresolved task rule recorded by `add-shared-scheduler`. Flyway runs forward only, so removing the tables is a new versioned migration, written only if the owner asks.

## Owner decisions of 2026-10-06

Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores. Its tables start empty, nothing is migrated or backfilled, and it needs none of today's data.

## Owner decisions of 2026-10-07

Answer 75.3: a manual run of a paused job answers 409 with the code `scheduled_job_state_conflict`, the same as a manual run of a final job, and records no firing (D8, D13, the `scheduled-jobs` spec and tasks 8.1 and 8.7). Answer 75.1 (review of the group 3, 4 and 5 changes of 2026-10-07, fix of all 75 items approved): items 10, 35 and 70 are fixed here. Item 35: the AI-run spec of task 7.5 lives at `apps/ascend-agent/e2e/testing/<next number>-scheduled-jobs-test.md`. Item 70: the 409 of `scheduled-jobs-trigger-cancelled` in task 8.1 names its code.

## Owner decisions of 2026-10-08

Answer 76.2: the scripted model of the shared harness of `close-agent-test-gaps` is Mockoon (the `mockoon/cli` image, pinned by version and digest). This change adds its script rules to the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json`, which holds every rule of every change, and keeps its reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/scheduled-jobs/` (task 8.7).

Approved fix of 2026-10-08: every deterministic spec of this change that runs a scripted chat turn wipes in AscendMemory the memories of its users in its Reset state and Post-run cleanup (`POST /api/v1/memory/wipe` with the provider `openai` and the service token), because the memory extraction of a scripted turn embeds through the scripted model into `ascend_memory_1536` (task 8.7). Superseded by answers 91.1 and 91.3 below: task 8.7 is removed, and no deterministic spec of this change runs a scripted chat turn.

Answer 85.1: no plan text of this change exports a key or a secret in a shell. The e2e specs read their tokens through the shared token module of `add-keycloak-login`, and every secret stays in the repository `.env`. Nothing changes here.

Answer 87 (rule R1, several agent instances, CANON 26.1): checked for every mechanism of this change. Kept: the per job execution on the shared scheduler (one instance per firing), the idempotent firing row (`ON CONFLICT DO NOTHING`), the row lock on the job in a firing, and the conditional updates of the outcome listener. Changed: the counted limits (active jobs per user and tenant, firings per tenant per day) are counted under a Postgres transaction advisory lock in the transaction that writes (D7, D8 step 4), the overlap check reads the previous run's row (D8), the startup consistency check is safe when several instances start at once (D3), and the listener runs on the instance that wrote the run's final state (D11). Nothing of this change keeps a lock, counter, queue or cache in memory only.

Answer 89.7: final job retention and the firing history cap are the two `RetentionEntry` beans `scheduled-job` (table `scheduled_job`, column `final_at`, age `jobs.retention`, only final jobs) and `scheduled-job-firing` (keep the newest `jobs.firing-history` firings per job) of the one retention task `record-retention` of `add-shared-scheduler` (D15a). The system task `scheduled-job-retention` and the delete on insert are gone, and the firing reads return at most the newest 50 (D1, D14, tasks 4.4 and 7.3, the `scheduled-job-execution` spec).

Answer 91.1: the deterministic phase fakes AscendMemory in the one Mockoon container and never wipes memories in a deterministic spec. This change no longer has a deterministic spec that runs a chat turn (answer 91.3), so no memory wipe and no AscendMemory step is left in its deterministic spec of task 8.2. The AI-run spec of task 7.5 uses the real AscendMemory and keeps its cleanup of the spec user's semantic memory.

Answer 91.3: the scripted spec of task 8.7 is removed, because each of its checks only repeats a lower test: the automatic pause after three failures (task 5.2), `owner_notify` with the price watch (task 6.2), a disabled owner (task 4.3) and another user's job (task 3.4). With it go the user `e2e-jobs-owner`, this change's scripted model rules and reply files, and the dependency on the harness of `close-agent-test-gaps`. The deterministic spec of task 8.2 stays, because it alone proves a reminder fired by the real scheduler from its schedule through to the notification on the live stack, and the AI-run spec of task 7.5 stays, because it runs with real AI answers (tasks 8.3 to 8.6, the `scheduled-jobs` spec).

Answer 93: the column `missed_grace_seconds` and the per job grace are removed. The grace comes from `jobs.missed-grace-recurring` (1 hour) and `jobs.missed-grace-once` (24 hours) by the schedule type, which keeps owner answer 43 (D4, D6, D8, D14, the `scheduled-jobs` and `scheduled-job-execution` specs). `jobs.max-reminder-chars` is removed, because a reminder is always the 4000 character body limit of the notification store (D7, D14). The six pairs of the source `scheduled_job` are inserted into the table `owner_notification_kind` of `add-shared-scheduler` by this change's own migration, not by the first migration of that change (review item S3-8, D4, task 1.2). Not applied, because it would cut a capability (rule R3): the schedule type `interval` stays. Cron cannot express every interval the owner can set today, for example every 90 minutes, every 25 hours, or a fixed elapsed gap that daylight saving never moves (D5, the `scheduled-jobs` spec scenario "Interval ignores daylight saving").

Answer 98 (owner rule 98, every value with a default is a setting): made external, each as `${ENV:default}` in `application.yaml`, the same default in `ScheduledJobProperties`, and `- ENV=${ENV:-default}` on the `ascend-agent` service of `compose.yaml` (D14, task 1.4): `APP_SCHEDULER_JOBS_DEFAULTTIMEZONE` (derived from `APP_SCHEDULER_DEFAULTTIMEZONE`, `Europe/Warsaw`, through a nested compose default), `APP_SCHEDULER_JOBS_MAXACTIVEPERUSER` (20), `APP_SCHEDULER_JOBS_MAXACTIVEPERTENANT` (100), `APP_SCHEDULER_JOBS_MININTERVAL` (`15m`), `APP_SCHEDULER_JOBS_HORIZON` (`366d`), `APP_SCHEDULER_JOBS_MAXPROMPTCHARS` (8000), `APP_SCHEDULER_JOBS_MAXFIRINGSPERTENANTPERDAY` (200), `APP_SCHEDULER_JOBS_MAXCREATESPERREQUEST` (5), `APP_SCHEDULER_JOBS_DEFAULTCOSTUSD` (0.25), `APP_SCHEDULER_JOBS_DEFAULTTOKENS` (100000), `APP_SCHEDULER_JOBS_MISSEDGRACERECURRING` (`1h`), `APP_SCHEDULER_JOBS_MISSEDGRACEONCE` (`24h`), `APP_SCHEDULER_JOBS_LATETHRESHOLD` (`2m`), `APP_SCHEDULER_JOBS_FAILURESBEFOREPAUSE` (3), `APP_SCHEDULER_JOBS_FIRINGHISTORY` (50), `APP_SCHEDULER_JOBS_RETENTION` (`30d`), `APP_SCHEDULER_NOTIFY_MAXMESSAGESPERRUN` (3), and the job list page size and maximum, which were fixed numbers of the `scheduled-jobs` spec before, as `APP_SCHEDULER_JOBS_LIST_DEFAULTLIMIT` (20) and `APP_SCHEDULER_JOBS_LIST_MAXLIMIT` (100). Kept as constants, because they are not operational: the column sizes and checks of D4 (a name of 1 to 100 characters, a prompt of at most 8000 characters, which `jobs.max-prompt-chars` may not exceed), the 4000 character body limit of a reminder and an `owner_notify` message (the notification store's schema check), the sample of the next 50 firings of the shortest gap check (a validation rule), the startup ceilings of 7 days for a grace and one minute for the shortest interval, and every name, code and enum value. The rows go into `apps/ascend-agent/docs/CONFIGURATION.md` (task 1.5). The stale "shipped profile" wording of the AI-run spec now says "shipped configuration", because the `e2e` profile is gone and the deterministic phase copies its test settings into the running agent (`close-agent-test-gaps` D7). No test or measurement of this change uses LM Studio: the AI-run spec of task 7.5 names a hosted provider, and the deterministic spec of task 8.2 calls no model.

## Open Questions

None. The grace periods for missed firings were the last open question, and owner answer 43 of 2026-10-02 confirmed them (1 hour for recurring jobs, 24 hours for one time jobs), together with the general background run limit of `add-agent-subagents` for a scheduled run.
