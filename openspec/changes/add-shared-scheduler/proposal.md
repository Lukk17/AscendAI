## Build order

Build order (owner build order of 2026-10-04, which supersedes the earlier orders): build group 3 (base), position 7 (owner answer 94.5 of 2026-10-08). It needs `upgrade-spring-boot-4` (group 3, position 2: Spring Boot 4.1.1, Flyway, and the RFC 7807 problem detail of its D19), `add-keycloak-login` (group 3, position 3: the authorization matrix its notification endpoints add rows to, and `TenantContext` with `runAs`, through which every scheduler thread binds the tenant of the row it acts for) and `add-deployment-modules` (group 3, position 6: the module catalog, `ASCEND_MODULES` and `@ConditionalOnModule`, which put the shared scheduler engine in `core-chat`). Every later change that does periodic work registers it on this scheduler, and every later change that tells the owner something when no chat request is open writes an owner notification of this change: in build group 3 `add-document-management-api`, and in build group 4 among others `add-agent-subagents`, `add-agent-sandbox`, `add-action-approvals`, `add-connector-framework`, `add-obsidian-vault`, `add-openclaw-plugin-host`, `add-coding-agent-delegation`, `add-scheduled-tasks`, `add-self-improvement` and `add-self-built-integrations`. Company changes of build group 5 (`add-audit-and-gdpr-compliance`, `add-tenant-isolation`) register their tasks and their erasure of notifications later. This change does not wait for them. The edits each of them needs are listed in design.md under "Required edits to other changes".

## Why

Many changes plan periodic work in ascend-agent, and before this change each one planned its own mechanism: a one minute `@Scheduled` tick with `FOR UPDATE SKIP LOCKED` for connectors, a Postgres advisory lock or ShedLock for audit retention, separate sweeps for subagent runs and approvals, an hourly sandbox job, and the timed work of self-improvement. Private schedulers would mean several ways to lose a firing after a restart and several places to test time. Two changes, `add-scheduled-tasks` and `add-self-improvement`, also need one way to tell the owner something outside a chat request. The owner decided on 2026-10-02 to take the shared scheduler and the owner notification store out of `add-scheduled-tasks` into this change, so that they land early (build group 3, position 7 of the owner build order of 2026-10-04) and every later change builds on them.

## What Changes

- One shared, persistent, cluster safe scheduler for the whole agent, built on the open source library db-scheduler (Apache 2.0) through its Spring Boot 4 starter, with one execution table created by a Flyway migration. The engine and its system tasks (retention, syncs, sweeps) are part of the `core-chat` module of `add-deployment-modules`, always on and never a switchable module.
- The module catalog gains the entry `scheduler`, only as the name for the assistant's own job features, with an empty `requires` list. `add-scheduled-tasks` fills that entry with its job tools and `requires: [subagents]`, and with no `uses` entry, because notification delivery is `core-chat`.
- System tasks: periodic work of any change, registered through one contract (a name in one closed enum, a five field cron and a time zone from configuration, with every minute as the shortest step and no fixed delay schedule, a handler that is safe to run twice), plus one time executions per entity for work such as a delayed review. Local work of one instance runs on Spring Boot's auto-configured `TaskScheduler` with `@Scheduled`, so the agent has two timers and no private timer thread (owner answer 89.3 of 2026-10-08).
- One retention task, `record-retention`, that deletes old rows of every change through the retention entries each change registers (table, time column, age, condition, optionally a keep-newest rule and cleanup hooks), in place of one retention task per change (owner answer 89.7 of 2026-10-08).
- An inventory of every periodic job of every change, with its home (shared scheduler or local to one instance) and its task name, so nothing builds a second scheduler.
- The lock and clock rules: one due execution runs on exactly one instance, a running execution that dies is run again, every handler is safe to run twice, and every service that reads time takes one injected `Clock`. Tests use the library's manual scheduler with a settable clock and never wait for real time.
- One cron format for the whole agent: five fields (minute precision), validated in one place, always evaluated in a named time zone, with fixed daylight saving rules.
- The missed firing rule for system tasks: an overdue system task runs once when an instance starts, never once for every missed time, and then follows its schedule.
- One tenant rule for work without a request: a scheduler thread that acts for a stored row (a per record execution, a system task that walks rows, a cleanup hook of a retention entry) binds the tenant stored on that row with `TenantContext.runAs` of `add-keycloak-login` before any other step, and every table this change creates carries `tenant_id VARCHAR(64) NOT NULL`, written from `TenantContext.currentTenantId()`, with no foreign key.
- Owner notifications: a stored notification per message to a user, readable through `GET /api/v1/notifications`, offered in the caller's transaction to every channel of the port `OwnerNotificationChannel` that can reach the user (the Discord channel of the plugin host `add-openclaw-plugin-host` implements it later), whose own queue sends it in real time and is the one retry layer, with the end state of each delivery recorded (owner answer 89.6 of 2026-10-08). The allowed pairs of source and kind live in a lookup table that each later change fills with its own migration (owner answer 93 of 2026-10-08), the `subject_ids` column holds the records a notification reports, the `actions` column holds its buttons, every button of every channel is handled through one action endpoint by the `ChannelActionHandler` of its action type, and the notification `read_at` is the only seen marker.
- Metrics, logs and the startup banner block of the scheduler, with one gauge of overdue executions as the one signal of a scheduler that has stopped firing (owner answer 93 of 2026-10-08: the starter's own statistics and health indicator are switched off).
- The project is under development, so there is no data migration and no backfill. Owner answer 73.1 of 2026-10-06 confirms that the data in today's development stores is disposable.

## Capabilities

### New Capabilities

- `shared-scheduler`: the one persistent scheduler of the agent: what must run on it and what stays local, the registration of system tasks, cluster safety, the one cron format and time zone rule, missed executions of system tasks, shutdown, the injectable clock, the one retention task, metrics and logs.
- `owner-notifications`: the stored notification with its sources, kinds and subject ids, the notification port and its channels, the record of each delivery's end state, the one action endpoint rule, the notification REST API, retention and its metrics. Erasure and export of notifications are company work of `add-audit-and-gdpr-compliance`, which adds them later.

### Modified Capabilities

(none. The archived specs in `openspec/specs/` describe no scheduling and no notifications. Every capability that registers work here belongs to a change that is not archived yet, and its change is a required edit listed in design.md, not a delta spec here.)

## Impact

- Dependencies: `com.github.kagkarlsson:db-scheduler-spring-boot-4-starter` 16.12.0 (Apache 2.0, latest release on Maven Central, published 2026-05-29), added to `apps/ascend-agent/gradle/libs.versions.toml` and `build.gradle.kts`. The library's test helpers (`ManualScheduler`, `SettableClock`) ship in the main `db-scheduler` artifact, so no extra test dependency is needed.
- New code in ascend-agent, all in `core-chat`: `scheduler/` (scheduler configuration, `CronRule`, `SchedulerTaskName`, the system task registration contract, the overdue gauge, the clock bean), `service/notification/` (notification service, the `OwnerNotificationChannel` and `ChannelActionHandler` ports, the delivery outcome record), `scheduler/retention/` (the task `record-retention`, `RetentionEntry`, `RetentionCleanup`), `controller/NotificationController`, `config/properties/SchedulerProperties` and `config/properties/OwnerNotificationProperties`, models and Spring Data JDBC repositories.
- Changed code in ascend-agent: `GlobalExceptionHandler` maps `notification_not_found`, `SecurityConfig` gains the notification rules, `StartupLogConfig` reports the scheduler, `application.yaml` gains `db-scheduler.*`, `app.scheduler.*` and `app.notifications.*`, each value with a default written as `${ENV:default}`, and the `ascend-agent` service of `compose.yaml` passes each of them as `${ENV:-default}` (owner rule 98 of 2026-10-08, design D10).
- Database: two Flyway versioned SQL migrations, `V<n>__shared_scheduler.sql` (`scheduler_execution`) and `V<n>__owner_notifications.sql` (`owner_notification_kind`, `owner_notification`, `owner_notification_delivery`), each `<n>` the next free version at implementation time.
- REST: `/api/v1/notifications/**`, with the new `ApiErrorCode` value `notification_not_found`.
- Docs: `docs/SCHEDULING.md` (new), `apps/ascend-agent/AGENTS.md`, the module README, `apps/ascend-agent/docs/CONFIGURATION.md`, `docs/OBSERVABILITY.md`, a decision record in `apps/ascend-agent/docs/architecture/decisions/` (next free number at implementation time) for the library choice, and Bruno requests under `docs/api/request/AscendAI/` for the notification endpoints.
- Backwards compatibility: with no task registered and no notification created, the scheduler polls an empty table and nothing is sent. `POST /api/v1/ai/prompt` keeps its request and response.

## Relevant Skills

Load these from `.agents/skills/` before implementing this change:

- `springboot-patterns` and `java-coding-standards` for the scheduler wiring, the services, the controller, configuration properties and the tests
- `build-dependency-management` for adding db-scheduler to the version catalog
- `database-migrations` and `postgres-patterns` for the two Flyway migrations, the lookup table, the constraints and the indexes
- `backend-patterns` for at most once execution, idempotent handlers, batched retention deletes and graceful shutdown
- `hexagonal-architecture` for the `OwnerNotificationChannel` port
- `api-design` for `/api/v1/notifications`, the status codes, cursor pagination and the problem detail code
- `observability-and-logging` for the metrics, the overdue gauge, the log lines and the startup banner
- `tdd-workflow` for writing each rule's test first with a controllable clock
- `architecture-decision-records` for the library decision record
- `markdown-writer` for `docs/SCHEDULING.md` and the AGENTS.md and README updates
- `e2e-runbooks` for the end-to-end specs of task group 5
