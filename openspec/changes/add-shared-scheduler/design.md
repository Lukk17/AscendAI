## Context

See proposal.md for why. This section holds only the facts the decisions rest on.

### The agent today and the changes that will use this one

- ascend-agent has no scheduled work at all: no `@Scheduled`, no `@EnableScheduling`, no `TaskScheduler` (searched `apps/ascend-agent/src` on 2026-10-02).
- Every periodic job planned across the active changes is listed in the inventory of D2. Before this change, each owning change planned its own mechanism: `add-document-connectors` D2 (now `add-connector-framework` D2, split of 2026-10-04) a one minute `@Scheduled` tick with `SELECT ... FOR UPDATE SKIP LOCKED` (and its D2 rejected Quartz as "overkill"), `add-audit-and-gdpr-compliance` D7 a daily `@Scheduled` job behind a Postgres advisory lock or ShedLock, `add-agent-subagents` D14 a sweep and a retention job, `add-action-approvals` D8 and D10 an expiry sweep every 30 seconds and a daily retention job, `add-agent-sandbox` an hourly retention job and an hourly destroy retry, `add-document-management-api` D9 a daily retention job, and `add-self-improvement` D9 its timed work.
- `add-deployment-modules` puts "the shared scheduler engine" in the always active `core-chat` module (its D3 table and the line after it), with `ASCEND_MODULES`, `@ConditionalOnModule` and `ModuleState`. A system task that belongs to a module is registered only when its module is active (its required edit to `add-scheduled-tasks`).
- `upgrade-spring-boot-4` moves the agent to Spring Boot 4.1.1, Spring Framework 7.0.9, Jackson 3 and Flyway 12.4.0, and every REST error to the RFC 7807 problem detail of its D19 (one `ApiErrorCode` enum, a top level `code`, and an `errors` field on a validation failure).
- The owner decided on 2026-10-02 (confirmed by owner answer 73.1 of 2026-10-06) that there is no existing data to keep, so nothing here migrates or backfills data. On the same day he moved the shared scheduler engine, the system tasks, the job inventory, the lock and clock rules, the cron and time zone rules, the missed firing rule for system tasks, and the owner notification store with its port out of `add-scheduled-tasks` into this change (owner answer 39.5), because `add-self-improvement` needs the notification store early and every other change needs the scheduler early.

### The libraries, checked on 2026-10-02

| | Spring `@Scheduled` with ShedLock | Quartz with JDBC job store | JobRunr | db-scheduler |
| :--- | :--- | :--- | :--- | :--- |
| Version | ShedLock 7.10.1 | 2.5.2, managed by Spring Boot 4.1.1 | 9.0.0 | 16.12.0 (2026-05-29) |
| Licence | Apache 2.0 | Apache 2.0 | LGPL 3.0 or later, plus a commercial licence for Pro | Apache 2.0 |
| Spring Boot 4 | 7.x supports Spring 7.0 and Spring Boot 4.x (its compatibility matrix) | `spring-boot-quartz` module in Spring Boot 4.1.1 | `jobrunr-spring-boot-4-starter` 9.0.0 | `db-scheduler-spring-boot-4-starter` 16.12.0, built against Spring Boot 4.0.6 |
| What it is | A lock only. Its README: "ShedLock is not and will never be full-fledged scheduler, it's just a lock. If you need a distributed scheduler, please use another project (db-scheduler, JobRunr)." | A full scheduler, clustered through row locks | A background job platform with a dashboard | A persistent cluster safe scheduler in one table |
| Tables | 1 lock table, schedules stay in code | 11 `QRTZ_` tables | Its own set of tables | 1 table |
| Jobs created at runtime | Not supported, would have to be written by us | Yes | Yes, recurring jobs limited to "up to 100" in the open source edition | Yes, one time tasks and per entity recurring executions |
| Missed runs after downtime | Not handled | Per trigger misfire instructions | "Schedule Missed Recurring Jobs (After Downtime)" is a Pro feature | An overdue execution is picked once at start, recurring schedules continue from completion |
| Cron and zones | Spring cron with a zone | Quartz cron dialect (seconds and `?`), zone per trigger | Cron with a zone | `Schedules.cron(String, ZoneId)` with Spring style cron, `daily(ZoneId, LocalTime...)`, `fixedDelay(Duration)` |
| Test clock | Spring has none for `@Scheduled` | No injectable clock | Not checked further | `ManualScheduler` with `SettableClock`, `tick`, `setTime`, `runAnyDueExecutions`, in the main artifact |
| Paid tiers | None | None | Pro Business 850 euro per month per production cluster, for mutexes, rate limits, priority queues, chaining and missed run catch up | None |

Sources: https://github.com/kagkarlsson/db-scheduler (README, the `v16.12.0` tag for `Schedules.java`, `CronSchedule.java`, `testhelper/ManualScheduler.java` and the PostgreSQL DDL in `src/test/resources/postgresql_tables.sql`), https://repo1.maven.org/maven2/com/github/kagkarlsson/db-scheduler-spring-boot-4-starter/maven-metadata.xml and the 16.12.0 POMs (parent properties `spring-boot-4.version` 4.0.6 and `jackson.version` 2.21.3), https://github.com/lukas-krecan/ShedLock (README and its compatibility matrix), https://repo1.maven.org/maven2/net/javacrumbs/shedlock/shedlock-spring/maven-metadata.xml, https://repo1.maven.org/maven2/org/springframework/boot/spring-boot-dependencies/4.1.1/spring-boot-dependencies-4.1.1.pom (`quartz.version` 2.5.2, `jackson-2-bom.version` 2.21.5), https://repo1.maven.org/maven2/org/quartz-scheduler/quartz/2.5.2/quartz-2.5.2.pom (Apache 2.0), https://repo1.maven.org/maven2/org/jobrunr/jobrunr/9.0.0/jobrunr-9.0.0.pom (LGPL 3.0 and commercial), https://repo1.maven.org/maven2/org/jobrunr/jobrunr-spring-boot-4-starter/maven-metadata.xml and https://www.jobrunr.io/en/pricing/.

Facts about db-scheduler that shape the design, read from the same sources:

- The execution table has the columns `task_name`, `task_instance`, `task_data` (bytes), `execution_time`, `picked`, `picked_by`, `last_success`, `last_failure`, `consecutive_failures`, `last_heartbeat`, `version` and `priority`, with the primary key `(task_name, task_instance)`. The table name is configurable.
- Polling defaults to every 10 seconds, so an execution can start up to 10 seconds after its time. `enableImmediateExecution` lets a newly scheduled execution that is already due run without waiting for the next poll.
- A running execution renews a heartbeat (default every 5 minutes). After 6 missed heartbeats an execution is dead and, by default, is rescheduled to `now()` and run again. So a handler must be safe to run twice.
- A recurring execution's next time is computed from the time the execution finished ("the nearest time according to the Schedule, but still in the future"), so an overdue recurring task runs once and does not catch up every missed time.
- A failing recurring task is rescheduled by its schedule, a failing one time task is retried after 5 minutes by default, and both can be overridden.
- `SchedulerClient` methods use a new connection from the data source, and "to have the action be a part of a transaction, it must be taken care of by the DataSource provided, for example using something like Spring's `TransactionAwareDataSourceProxy`".
- The README on the main branch already describes a `DbSchedulerOverrides` bean "as of 17.0.0". 17.0.0 is not released. 16.12.0 is what this change uses.
- Spring Boot 4.1.1 manages the Jackson 2 line (2.21.5) next to Jackson 3, so the starter's Jackson 2 dependency resolves to a managed version. This design never serialises data into `task_data`, so no serializer is used.

## Goals / Non-Goals

Goals:

- One scheduler for every piece of shared timed work in the agent, so a firing is lost or doubled in no change and time is tested one way.
- One inventory that names every periodic job of every change and where it runs.
- One notification store and one channel port that every later change writes to, which works today without any channel and grows a channel per change without touching the code that creates notifications.

Non-Goals:

- The assistant's own jobs, their tools, their REST API and their firing rules. They are `add-scheduled-tasks`.
- The handlers of other changes' system tasks. Each owning change writes its own handler on the contract of D2.
- A dashboard for the scheduler. The metrics and the overdue gauge cover operations (D12, D13).
- Push notifications to the phone, the Discord adapter and the app screens. They are required edits to `add-flutter-chat-app` and `add-openclaw-plugin-host`.
- Seconds in cron expressions, cron macros such as `@daily`, and fixed delay schedules. The shortest step is one minute (`* * * * *`), and no planned task needs less (D2).
- Periodic work inside other services (ascend-ocr, the Python services, the sandbox runner). Their periodic work is their own and is not in the agent. The inventory lists the ones other changes plan so nothing is forgotten.

## Decisions

### D1: db-scheduler is the shared scheduler

ascend-agent depends on `com.github.kagkarlsson:db-scheduler-spring-boot-4-starter` 16.12.0, declared in `gradle/libs.versions.toml`.

Why db-scheduler:

- It solves exactly the two problems every planned job has, persistence and "one and only one scheduler instance gets to pick and run a task execution", in one table, which fits a project that already owns its schema through Flyway.
- It stores runtime created executions next to code defined recurring tasks, so assistant jobs, per connector syncs, delayed reviews and retention tasks are one mechanism.
- Its overdue behaviour is the rule this change wants for system tasks (run once, then continue), and its handler sees the scheduled time, so the stricter rule for assistant jobs in `add-scheduled-tasks` is a small check in that change's handler.
- It ships a manual scheduler with a settable clock in the main artifact, which makes tests with a controllable clock a supported path rather than a workaround.
- Apache 2.0, a Spring Boot 4 starter, PostgreSQL support with `SKIP LOCKED`, regular releases in 2026, and production use listed by Wise, NAV and Vy.

Rejected:

- Spring `@Scheduled` with ShedLock: ShedLock states it is only a lock. It handles neither runtime created jobs, nor one time jobs, nor missed runs, nor a durable next fire time. Building those around it is writing a scheduler, which the owner ruled out.
- Quartz with its JDBC job store: correct and well known, but 11 tables for this need, its own cron dialect (six or seven fields, `?`) next to the Spring cron the rest of the agent uses, a `JobDataMap` model that duplicates state the owning rows already hold, and no injectable clock, so time based tests would wait or reach into internals. `add-document-connectors` D2 (now `add-connector-framework` D2) rejected it for the same weight.
- JobRunr: the open source edition limits recurring jobs to "up to 100", and catch up of missed recurring jobs after downtime, mutexes and rate limits are in the paid Pro edition (850 euro per month per production cluster). Per user assistant jobs would hit the first limit and need the second.

Fallback, stated now so it is not invented later: if the starter does not start on Spring Boot 4.1.1 (it is built against 4.0.6), task 1.2 fails and the agent wires the plain `db-scheduler` artifact with one configuration class of its own, `SchedulerBuilder` on the existing `DataSource`. The library choice does not change.

A decision record `ADR-NNN-shared-scheduler-db-scheduler.md` in `apps/ascend-agent/docs/architecture/decisions/` (next free number at implementation time) records this table and its reasons.

### D2: What runs on the shared scheduler, what stays local, and the inventory

Rule: work that writes shared state, and must therefore happen once per deployment, runs on the shared scheduler. Work that only refreshes one instance's memory, or proves one instance alive, runs on Spring Boot's auto-configured `TaskScheduler` with `@Scheduled` methods, because every instance must do it for itself (owner answers 89.3 and 87 of 2026-10-08). `@EnableScheduling` is switched on once by `add-deployment-modules`, which lands first and needs it for `McpReconnectScheduler` (its D19). No change builds a private `ThreadPoolTaskScheduler`, `ScheduledExecutorService` or timer thread for timed work. So the agent has exactly two timers: db-scheduler for persistent and cluster-wide work, and the one auto-configured `TaskScheduler` for local work, which Spring Integration pollers use too.

Inventory of every periodic job planned in the active changes. The name column is the `task_name`. For a per record execution the `task_instance` is the record id. Each owning change registers its own task bean and its own handler on the contract below, which is the required edit listed for it at the end of this design.

| Work | Owning change | Home | Name and shape | Default schedule |
| :--- | :--- | :--- | :--- | :--- |
| Sync of one connector on its cron | `add-connector-framework` | shared | `connector-sync`, one execution per connector | the connector's own cron and zone |
| Connector freshness check | `add-connector-framework` | shared, `core-chat` (document search, always on) | system task `connector-freshness-check` | `*/5 * * * *` in `UTC` |
| Obsidian full rescan of every enabled `OBSIDIAN` connector (an `OBSIDIAN` connector has no `connector-sync` execution of its own) | `add-obsidian-vault` | shared, module `obsidian` | system task `obsidian-vault-rescan` | `*/15 * * * *` in `Europe/Warsaw` |
| Obsidian watcher debounce and sync status file read | `add-obsidian-vault` | local | per instance, event driven or reads into memory | none |
| Chat history, user data and audit log retention | `add-audit-and-gdpr-compliance` | shared | system task `retention` | `0 3 * * *` in `Europe/Warsaw` |
| Export archive cleanup | `add-audit-and-gdpr-compliance` | shared | system task `export-archive-cleanup` | set by that change |
| Retention of old rows of every change below that registers a retention entry (D15) | this change | shared, `core-chat` | system task `record-retention` | `15 * * * *` in `UTC` |
| `ingestion_runs` retention | `add-document-management-api` | shared, `core-chat` (document search, always on) | entry `ingestion-run` of `record-retention` | the schedule of `record-retention` |
| Sweep of ingestion runs whose owner instance died | `add-document-management-api` | shared, `core-chat` (document search, always on) | system task `ingestion-run-orphan-sweep`, and still once at startup | `*/5 * * * *` in `UTC` |
| Ingestion run lease renewal and the pickup poll of the streaming S3 pipeline | `add-document-management-api` | local | per instance | see the local timers table |
| Restart sweep of runs whose owner instance died | `add-agent-subagents` | shared, `core-chat` | system task `run-orphan-sweep`, and still once at startup before readiness | `*/5 * * * *` in `UTC` (default adopted here) |
| Run tree retention | `add-agent-subagents` | shared, `core-chat` | entry `subagent-run` of `record-retention` | the schedule of `record-retention` |
| Run heartbeat renewal and deadline watchdog | `add-agent-subagents` | local | per run, per instance | none |
| Approval expiry sweep | `add-action-approvals` | shared, `core-chat` | system task `approval-expiry-sweep`, and still once at startup before readiness | `* * * * *` (every minute) in `UTC` |
| Decided approval retention | `add-action-approvals` | shared, `core-chat` | entry `approval-request` of `record-retention` | the schedule of `record-retention` |
| Sandbox reaper of expired, orphan and badly labelled containers | `add-agent-sandbox` | local to the sandbox runner service, a separate single instance process with no agent database, never on this scheduler | the runner's own `reaper-interval` | every 60 seconds |
| Close of idle, expiring and orphan chat workspaces, and closing the records of workspaces the runner already expired | `add-agent-sandbox` | shared, `core-chat` | system task `sandbox-chat-idle-sweep` | `*/5 * * * *` in `UTC` (zone adopted here) |
| Sandbox workspace record and archive retention | `add-agent-sandbox` | shared, `core-chat` | entries `sandbox-run-workspaces` and `sandbox-chat-workspaces` of `record-retention`, with an archive cleanup hook | the schedule of `record-retention` |
| Free space check of the coding project area | `add-coding-agent-delegation` | shared, module `coding` | system task `coding-area-free-space-check` | `*/15 * * * *` in `UTC` (zone adopted here) |
| Coding run output and deleted project retention | `add-coding-agent-delegation` | shared, module `coding` | entry `coding-project` of `record-retention` and a cleanup hook on the entry `subagent-run` | the schedule of `record-retention` |
| Plugin host table cleanup | `add-openclaw-plugin-host` | shared, module `channels` | system task `channel-host-cleanup` | `0 4 * * *` in `Europe/Warsaw` |
| Skill folder rescan | `add-agent-skills` | local | per instance memory | `app.skills.rescan-interval` |
| Assistant job firing | `add-scheduled-tasks` | shared, module `scheduler` | `scheduled-job`, one execution per job | the job's own schedule |
| Final job and firing retention | `add-scheduled-tasks` | shared, module `scheduler` | entries `scheduled-job` and `scheduled-job-firing` of `record-retention` | the schedule of `record-retention` |
| Sync run history cap of 50 runs per connector | `add-connector-framework` | shared, `core-chat` (document search, always on) | entry `connector-sync-run` of `record-retention` | the schedule of `record-retention` |
| Delayed review of one conversation | `add-self-improvement` | shared, module `self-improvement` | `self-review`, one execution per review | the review's start time |
| Daily review | `add-self-improvement` | shared, module `self-improvement` | system task `self-improvement-review` | `30 3 * * *` in `Europe/Warsaw` |
| Daily review of one tenant, also started through REST | `add-self-improvement` | shared, module `self-improvement` | `self-improvement-tenant-review`, one execution per tenant | due at once |
| Retry of guard checks that could not run | `add-self-improvement` | shared, module `self-improvement` | system task `self-improvement-check-retry` | `0 * * * *` in `Europe/Warsaw` |
| Self-improvement retention | `add-self-improvement` | shared, module `self-improvement` | entries `self-review` and `self-change` of `record-retention` | the schedule of `record-retention` |
| Reconcile of self-built integration services with the runner | `add-self-built-integrations` | shared, module `self-built-integrations` | system task `integration-reconcile` | `* * * * *` (every minute) in `Europe/Warsaw` |
| Notification retention | this change | shared, `core-chat` | entry `owner-notification` of `record-retention` | the schedule of `record-retention` |

The delivery retry `notification-delivery` of the plan before 2026-10-08 is gone: the one retry layer of a notification is the queue of its channel (D8, owner answer 89.6 of 2026-10-08). The retention system tasks `notification-retention`, `ingestion-run-retention`, `run-retention`, `approval-retention`, `sandbox-workspace-retention`, `coding-run-retention`, `scheduled-job-retention` and `self-improvement-retention` of that plan are gone too: each is now an entry of the one task `record-retention` (D15, owner answer 89.7 of 2026-10-08). The system task `sandbox-destroy-retry` of `add-agent-sandbox` is gone as well (removed by answer 93 of 2026-10-08, the runner's own expiry and the idle sweep cover it).

The home column names the module whose `@ConditionalOnModule` a task bean carries. `core-chat` means always registered: the run table, the run service, `/api/v1/runs` and the run sweeps are `core-chat`, and so are approvals. By owner decision of 2026-10-03 the sandbox is core too, always on and never switchable, so its three tasks are `core-chat`. A row marked `core-chat` (document search, always on) is always registered as well and its bean carries no `@ConditionalOnModule`, because document search (`rag`) is part of the always-on core and not a module (owner decision of 2026-10-03). A row without a module is registered as its owning change decides. Every name in the table, system task or per record task, is a value of the one enum `SchedulerTaskName`, so metric tags stay bounded (D12). This change adds the value of its own one task, `record-retention`. Each owning change adds its own values when it lands, and a value without a registered bean is harmless. A retention entry is not a task and has no value in the enum.

Zones these changes adopt: where an owning change gives a cron but no zone, the default is `UTC` for a sweep and for hourly or more frequent work, and `Europe/Warsaw` for daily work. So `run-orphan-sweep` defaults to `*/5 * * * *` in `UTC` (`add-agent-subagents` gives neither cron nor zone), and the sandbox task and the coding task keep their owners' crons in `UTC`. The same values are written into the owning changes. `record-retention` runs hourly, `15 * * * *` in `UTC`, the shortest interval any of the retention tasks it replaces had (the sandbox workspace retention), so no entry keeps a row longer than its own task did. The `rag` tasks use the values their owners set: `connector-freshness-check` `*/5 * * * *` in `UTC` (`add-connector-framework` D19) and `ingestion-run-orphan-sweep` `*/5 * * * *` in `UTC` (`add-document-management-api` D3). `channel-host-cleanup` (`0 4 * * *` in `Europe/Warsaw`, module `channels`) and `integration-reconcile` (`* * * * *` in `Europe/Warsaw`) use the values their owners set.

Local timers that owning changes asked to be listed here. They run on the instance, never on the shared scheduler, and have no `SchedulerTaskName` value:

| Work | Owning change | Module | Timer | Interval |
| :--- | :--- | :--- | :--- | :--- |
| Background retry of `FAILED` MCP clients (`McpReconnectScheduler`, D19 of that change) | `add-deployment-modules` | `core-chat` | `@Scheduled` on Spring Boot's auto-configured `TaskScheduler` (owner answer 89.3 of 2026-10-08) | `app.mcp.reconnect.interval` (default `60s`) |
| Lease renewal of the ingestion runs this instance runs, and the wake of its run worker | `add-document-management-api` | `core-chat` (document search) | `@Scheduled` on Spring's local `TaskScheduler` | lease renewed every 10 seconds (`app.ingestion.run-worker.lease-renew-interval`), lease length 60 seconds (`app.ingestion.run-worker.lease-duration`), fallback wake every 30 seconds (`app.ingestion.run-worker.fallback-check-interval`), owner answer 98.4 of 2026-10-08 |
| Pickup poll of the streaming S3 pipeline (`IngestionPipelineConfig`), which only starts runs through a Postgres claim | `add-document-management-api` | `core-chat` (document search) | Spring Integration poller on Spring Boot's auto-configured `TaskScheduler` | `app.ingestion.poller.fixed-delay-millis` (default 1 second) |
| Retry of pending capability index entries while no skill rescan runs | `add-agent-skills` | `core-chat` | `CapabilityIndexSync` on Spring's local `TaskScheduler` | `app.capability-index.retry-interval` (default `60s`) |
| Event stream fallback check and redelivery of rows sent without an ack, inside the stream of one `channels` container. The loop guard counters expire through their Redis time to live with no job | `add-openclaw-plugin-host` | `channels` | inside the open event stream | check every 5 seconds, redelivery after 2 minutes |
| Refresh of the integration MCP entries in this instance's `RuntimeMcpClientRegistry` | `add-self-built-integrations` | `self-built-integrations` | Spring's local `TaskScheduler` | `app.integrations.entry-refresh-interval` (default `60s`) |

Registration contract for a system task: a Spring bean built with a small builder of this change from a `SchedulerTaskName`, its configuration and a handler. The schedule comes from `app.scheduler.system-tasks.<name>.cron` with `.time-zone`. A five field cron is the only schedule shape: the shortest step is one minute (`* * * * *`), which the approval expiry sweep and the integration reconcile use, and no task in the inventory needs a shorter one. A bean of a module carries `@ConditionalOnModule` of `add-deployment-modules`, so its task is registered only when its module is active. The starter starts every recurring task bean on boot. The application refuses to start when a registered task has a name outside the enum, no cron, or a cron without a zone, naming the key. Both keys are settings under owner rule 98 of 2026-10-08: `application.yaml` writes `cron: ${APP_SCHEDULER_SYSTEMTASKS_<NAME>_CRON:<default>}` and `time-zone: ${APP_SCHEDULER_SYSTEMTASKS_<NAME>_TIMEZONE:<default>}`, where `<NAME>` is the task name in upper case with its hyphens removed (Spring Boot's canonical environment form, for example `APP_SCHEDULER_SYSTEMTASKS_RECORDRETENTION_CRON`), and the `ascend-agent` service of `compose.yaml` passes the same two variables as `${VAR:-<default>}`. Each owning change adds the two lines and the two compose lines of its own task when it lands, with the defaults of the inventory.

### D3: Per record executions keep their schedule in their own row

Assistant jobs, connector syncs and delayed reviews are custom tasks whose `task_instance` is the record id and whose `task_data` is empty. The handler reads the record, does the work, computes the next time from the record, and returns a completion that reschedules the same execution to that time, or removes it when there is none. A change to the record (new schedule, pause, resume, cancel, disable, delete) reschedules, removes or creates the execution through `SchedulerClient` in the same transaction as the record change (D5).

Why not the library's "recurring task with persistent schedule": it stores the `Schedule` object serialised in `task_data`, which would be a second copy of the record's schedule, in Java serialisation that a library upgrade can break. One source of truth is the record, and the execution row only says when to look next.

Each such execution's next time is the next schedule time after the moment the handler finished, so the collapse of missed times into one run holds for every record task.

A scheduler thread has no request and so no resolved identity. Every handler that acts for a stored row binds the tenant stored on that row with `TenantContext.runAs(tenantId, action)` of `add-keycloak-login` (its D3) before any other step, and every code it calls reads the tenant through `TenantContext.currentTenantId()`, as request code does. A system task that walks rows of several tenants binds each row's tenant for the work on that row. A handler that cannot read the tenant of its row fails the execution and never runs with no tenant or a guessed one, because `TenantContext` throws with nothing bound. This change's own task follows the rule: `record-retention` runs every cleanup hook of an entry with the tenant of the row it acts on bound (D15). Its plain row deletes read no tenant, because they remove rows by age in every tenant alike. Every later change's handler follows it too, so no company change has to add the binding later.

### D4: One cron format, on Spring's cron engine

`scheduler/CronRule` is the one place that validates and evaluates a cron expression for the whole agent: exactly five fields, each turned into Spring Framework's `CronExpression` by putting the seconds field `0` in front, and always evaluated with `next(ZonedDateTime)` in a `ZoneId` from `ZoneId.of`, accepting region ids such as `Europe/Warsaw` and `UTC`. Configuration of system tasks, connector schedules, the job REST API and the agent tools all go through it. `CronRule` also answers "the shortest gap among the next N firings", which the job limit of `add-scheduled-tasks` and the connector freshness invariant both need.

Five fields because the model and the owner write Unix cron far more often than Spring's six field form, and because minute precision is all any job here needs. Spring's engine because it is already on the classpath, it is what db-scheduler's own `Schedules.cron` accepts, and one engine means one daylight saving behaviour.

Daylight saving: the `shared-scheduler` spec fixes the behaviour (a skipped local time fires at the first moment after the gap, a repeated local time fires once). Tests pin both cases for `Europe/Warsaw` on 2027-03-28 and 2026-10-25. Where Spring's engine differs from the spec, `CronRule` adjusts its result, and the tests are the proof.

The deployment default zone is `Europe/Warsaw` (`app.scheduler.default-time-zone`), the owner's zone. A system task with no zone of its own takes it only through its configuration default, never silently in code.

### D5: The execution table, configuration and transactions

- Migration `V<n>__shared_scheduler.sql` creates the library's PostgreSQL table under the name `scheduler_execution`, with the columns of the library's DDL at 16.12.0 and named indexes `scheduler_execution_time_idx`, `scheduler_execution_heartbeat_idx` and `scheduler_execution_priority_time_idx`. A library upgrade that changes the schema (its `UPGRADING.md`) is a new versioned migration.
- `application.yaml`: `db-scheduler.table-name: scheduler_execution`, `db-scheduler.threads: 10`, `db-scheduler.polling-interval: 10s`, `db-scheduler.immediate-execution-enabled: true`, `db-scheduler.shutdown-max-wait: 30s` (the library default is 30 minutes, far longer than a container stop grace), and the starter's delay until the Spring context is ready, so no task runs before Flyway has migrated and the beans are wired. The polling strategy stays the default `fetch`, which the README recommends below 1000 executions per second. The operational values among them are settings (owner rule 98 of 2026-10-08, D10): threads, polling interval, immediate execution, shutdown wait, and the heartbeat interval (library default 5 minutes) and missed heartbeat limit (library default 6) that decide when a running execution counts as dead. The table name, the polling strategy and the startup delay stay fixed values in `application.yaml` (D10). The exact key names are read in the 16.12.0 starter source at implementation time (task 1.2).
- Transactions: the scheduler's data source is wrapped in Spring's `TransactionAwareDataSourceProxy`, so a record change and its execution change commit or roll back together, as the library README requires. Task 1.3 proves it with a test that rolls back a record creation and finds no execution.
- Shutdown: the starter stops the scheduler on context close. Task 1.7 asserts the order (scheduler stops before the data source closes).

### D6: One clock for everything that reads time

A single `java.time.Clock` bean (`Clock.systemUTC()`) in `core-chat` is injected into every service that schedules work or decides by time, in this change and in every change that registers on it. Nothing in `scheduler/` and `service/notification/` calls `Instant.now()` or `LocalDateTime.now()` without the clock, and a test greps for it. Each later change extends the grep to its own packages.

Tests:

- Scheduler level: `ManualScheduler` from the library's `testhelper` package with its `SettableClock`, built through `TestHelper` on a Testcontainers PostgreSQL data source with the real task beans. `tick(Duration)` or `setTime(Instant)` moves time and `runAnyDueExecutions()` fires what is due. The same `SettableClock` instance is exposed as the `Clock` bean of the test context, so handlers and the scheduler agree on the time. This test support is a test fixture of this change that every later change reuses.
- Unit level: services take a fixed `Clock`.
- No test sleeps to wait for a firing.

### D7: The notification tables

Migration `V<n>__owner_notifications.sql`. Every constraint and index has an explicit name. Tenant columns are `tenant_id VARCHAR(64) NOT NULL`, written from `TenantContext.currentTenantId()` of `add-keycloak-login` (or the tenant bound with `runAs` on a scheduler thread, D3), which answers `default` in the personal deployment, with no foreign key. `add-tenant-isolation` (company, build group 5) creates the `tenants` table later and adds the foreign keys to `tenants(id)` in its own migration.

`owner_notification_kind`: `source VARCHAR(32)`, `kind VARCHAR(16)`, primary key `owner_notification_kind_pk (source, kind)`. It holds the allowed pairs of source and kind. This change's migration inserts no row: each later change that writes notifications inserts its own pairs with its own versioned migration, `INSERT ... ON CONFLICT DO NOTHING` (owner answer 93 of 2026-10-08, review item S3-8). A lookup table is used rather than check constraints, because a check constraint listing the values would have to be dropped and written again, with every value of every earlier change, by each change in build order.

`owner_notification`: `id UUID`, `tenant_id`, `user_id VARCHAR(255)`, `source VARCHAR(32)`, `kind VARCHAR(16)`, the foreign key `owner_notification_kind_fk (source, kind)` to `owner_notification_kind`, so a kind is accepted only with its own source, `job_id`, `firing_id`, `run_id` (all `UUID` null, no foreign key, so a notification outlives its job until its own retention), `subject_ids JSONB NOT NULL DEFAULT '[]'` (an array of record ids the notification reports, as the table below lists per source), `actions JSONB NOT NULL DEFAULT '[]'` (the buttons a channel may show with the notification, each `{actionType, subjectId, label}`, owner answer 89.6 of 2026-10-08, D8), `title VARCHAR(100)`, `body TEXT` (check at most 4000 characters), `created_at`, `read_at`. `read_at` is the only seen marker of a notification and of what it reports: no change keeps a second seen flag for the same report (owner answer 89.6 of 2026-10-08). Indexes `(tenant_id, user_id, created_at DESC)`, partial `(tenant_id, user_id) WHERE read_at IS NULL`, `(created_at)`.

`owner_notification_delivery`: `id UUID`, `tenant_id` (copied from its notification), `notification_id` (foreign key `ON DELETE CASCADE`), `channel VARCHAR(32)`, `state` (check in `pending`, `delivered`, `failed`, `unavailable`), `error_code VARCHAR(64)`, `updated_at`. Unique `(notification_id, channel)`. It records where a notification went and how that ended. It holds no attempt counter, because the retries belong to the channel's own queue (D8).

Sources and kinds. This is the one list of the pairs the changes of the build order insert, each with its own migration, so all sides agree on the values:

| Source | Owning change | Kinds | Title | `job_id`, `firing_id`, `run_id` | `subject_ids` |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `scheduled_job` | `add-scheduled-tasks` | `reminder`, `result`, `message`, `failure`, `paused`, `missed` | the job name | the job, the firing and, when there is one, the run | empty |
| `self_improvement` | `add-self-improvement` | `change`, `alert` | fixed by the source | none | the ids of the reported `self_change` records |
| `approval` | `add-action-approvals` | `expired` (a request that expired without a decision, so its action did not run) | fixed by the source | none | the id of the expired approval request |
| `coding_area` | `add-coding-agent-delegation` | `low_space` (the free space warning of the free space check, at most once per notify interval), `cleanup` (a notice about a cleanup of the coding project area through the approval kind `coding_project_cleanup`, category `workspace_cleanup`) | fixed by the source | none | empty for `low_space`, the cleanup approval's id for `cleanup` |
| `integration` | `add-self-built-integrations` | `auto_disabled` (an integration switched off after repeated failures) | fixed by the source | none | the id of the disabled integration |

`add-self-built-integrations` also tells the owner through the finished runs block, its audit events and the change records of `add-self-improvement`, and since owner answer 89.6 of 2026-10-08 it creates the `auto_disabled` notification as well, because every alert is created through `OwnerNotificationService`. A notification has one user, so that change creates one `auto_disabled` notification for every user with the `ADMIN` role in the tenant of the disabled integration (owner answer 98.10 of 2026-10-08). `add-openclaw-plugin-host` asks for no source: it is a channel of the port (D8). A later change that needs a new value inserts its pair into `owner_notification_kind` with its own versioned migration and adds it to the `owner-notifications` spec. This change's migration and tests never depend on a pair of a later change.

Entities follow the agent's Spring Data JDBC style (`@Table`, `@Id`, no JPA) with native `@Query` methods for the conditional updates and cursor pages.

### D8: The notification service and the channel port

- `OwnerNotificationService.create(OwnerNotificationRequest)` takes the tenant, the user, the source, the kind, the title, the body, the optional job, firing and run ids, the subject ids and the actions, cuts a long body with the note of the spec (the note text comes from the source: the run id for a job result, `GET /api/v1/self-improvement/changes` for a self-improvement report, and the record ids in `subject_ids` for the other sources), stores the notification, and then, still in the caller's transaction, calls `deliver` on every channel that is switched on and `canReach` the user, storing one `pending` delivery row for each, and one `unavailable` row for every other switched on channel. Every alert of every change is created through this one method (owner answer 89.6 of 2026-10-08): no change tells the owner about an event through a path of its own that skips the notification store.
- `OwnerNotificationChannel` is the port: `String name()`, `boolean canReach(String tenantId, String userId)`, `void deliver(OwnerNotificationView notification)`. Channels are beans found by type. `deliver` runs inside the caller's transaction and only writes the message into the channel's own durable queue, with no network call, so the queued message commits or rolls back with the notification and a rolled back caller sends nothing. The channel's queue then sends the message in real time (for Discord, the insert into `channel_outbox` wakes the event stream through Postgres `NOTIFY` after commit) and retries it. This change ships no external channel. The stored notification and `GET /api/v1/notifications` are always there, which is what the mobile app reads until it has push.
- One retry layer (owner answer 89.6 of 2026-10-08): the retries of a delivery belong to the channel's own queue, never to this change. The choice was between `owner_notification_delivery` with retries on the shared scheduler and `channel_outbox` of `add-openclaw-plugin-host` with its own attempts, its redelivery after 2 minutes without an ack and its `dead` state. `channel_outbox` is kept as the one layer, because it is the one way the agent sends anything without an inbound message (run status, approval prompts and updates, link confirmations, loop guard notices, purge and owner notifications), so it retries anyway, and a retry layer here would only have retried the insert of an outbox row, which now commits together with the notification. `owner_notification_delivery` stays as the record of where a notification went and how that ended: when the channel's queue reaches its end state it calls `OwnerNotificationService.recordDeliveryOutcome(notificationId, channel, outcome, errorCode)` once, with the outcome `delivered` or `failed`, which moves a `pending` row with a conditional update, so a second report changes nothing. So this change schedules no delivery execution and keeps no backoff or attempt setting.
- One action endpoint (owner answer 89.6 of 2026-10-08): a notification carries its buttons in `actions`, each `{actionType, subjectId, label}`, and an approval prompt of `add-action-approvals` carries its Approve and Deny buttons the same way. Every press on any channel goes through the one action endpoint `POST /api/v1/channel-host/actions` of `add-openclaw-plugin-host`, which reads the action type and the subject id from its outbox row and calls the core port `ChannelActionHandler` of this change: `String actionType()`, `void handle(ChannelAction action)`, where `ChannelAction` holds the tenant, the acting user's identity, the action type, the subject id, the channel and the id of the message the button belonged to. The handler bean of each action type is registered by the change that owns the action: `approval_approve` and `approval_deny` by `add-openclaw-plugin-host` (they call `ApprovalService.decide`), and `self_improvement_undo` by `add-self-improvement`. Each handler checks its own role rule and is safe to run twice. A new button is a new action type and its handler bean, never a new endpoint. The handlers keep no state, so a press that reaches any agent instance works the same (owner answer 87).
- `read_at` is the only seen marker (owner answer 89.6 of 2026-10-08): a report another change keeps records of (for example the change records of `add-self-improvement`) counts as seen exactly when the notification that reported it is read, and the mobile app marks it with `POST /api/v1/notifications/{id}/read`. No change adds a seen flag or a seen endpoint of its own.
- `add-openclaw-plugin-host` (service `ascend-openclaw-host`) implements the channel `discord` (required edit). `add-flutter-chat-app` adds the notification list (required edit). A push channel, when it comes, is one more implementation of the port with its own durable queue.

The service, the port, `ChannelActionHandler` and `ChannelAction` are in `core-chat`, so a change in any module can write a notification or register a button handler without depending on the `scheduler` module of `add-scheduled-tasks` or on the `channels` module.

### D9: REST, errors and security

- `NotificationController` under `/api/v1/notifications`, contract in the `owner-notifications` spec. Cursor pagination encodes `(created_at, id)` as an opaque base64 cursor, the same as the run list.
- New `ApiErrorCode` value, added by this change to the enum of `upgrade-spring-boot-4` D19: `notification_not_found` (404). Validation failures use the existing `validation` code with `errors`.
- `SecurityConfig`: `add-keycloak-login` lands before this change (build group 3, right after `upgrade-spring-boot-4`, split of 2026-10-04, owner rule of 2026-10-04), so this change adds its own row to that change's authorization matrix (its D4): `/api/v1/notifications/**` needs an authenticated caller, with a security slice test, and the controller scopes by tenant and user, also for `ADMIN`. Under the `dev` profile of `add-keycloak-login` the endpoints are open like every other endpoint.
- Tenant: the controller and the service take the tenant from `TenantContext.currentTenantId()` of `add-keycloak-login` (its D3), which lands before this change. In a request that is the tenant of the caller's resolved identity, `default` in the personal deployment. On a scheduler thread it is the tenant the handler bound with `runAs` (D3). Nothing falls back to `default`: with nothing bound the call throws.

### D10: Configuration

`SchedulerProperties` binds `app.scheduler` and `OwnerNotificationProperties` binds `app.notifications`. Every value with a default is a setting (owner rule 98 of 2026-10-08): `application.yaml` writes `key: ${ENV:default}`, the properties record carries the same default in code, and the `ascend-agent` service of `compose.yaml` writes `- ENV=${ENV:-default}`. The `db-scheduler.*` keys are bound by the starter's own properties class, so for them `application.yaml` and the compose line carry the default and no record of this change does.

| Key | Environment variable | Default | Meaning |
| :--- | :--- | :--- | :--- |
| `app.scheduler.default-time-zone` | `APP_SCHEDULER_DEFAULTTIMEZONE` | `Europe/Warsaw` | Zone a configuration default refers to |
| `app.scheduler.overdue-threshold` | `APP_SCHEDULER_OVERDUETHRESHOLD` | `5m` | Lateness that counts an execution as overdue |
| `app.scheduler.system-tasks.<name>.cron` and `.time-zone` | `APP_SCHEDULER_SYSTEMTASKS_<NAME>_CRON` and `_TIMEZONE` (D2) | per task, set by its owning change | Schedule of a system task |
| `app.scheduler.system-tasks.record-retention.cron` and `.time-zone` | `APP_SCHEDULER_SYSTEMTASKS_RECORDRETENTION_CRON` and `APP_SCHEDULER_SYSTEMTASKS_RECORDRETENTION_TIMEZONE` | `15 * * * *` in `UTC` | The one retention task (D15) |
| `app.scheduler.record-retention.batch-size` | `APP_SCHEDULER_RECORDRETENTION_BATCHSIZE` | `100` | Rows `record-retention` selects, cleans up and deletes in one transaction (D15, owner answer 98.4 of 2026-10-08) |
| `app.notifications.retention` | `APP_NOTIFICATIONS_RETENTION` | `30d` | Retention of notifications, the age of this change's retention entry |
| `app.notifications.list.default-limit` | `APP_NOTIFICATIONS_LIST_DEFAULTLIMIT` | `20` | Page size of `GET /api/v1/notifications` when no `limit` is sent |
| `app.notifications.list.max-limit` | `APP_NOTIFICATIONS_LIST_MAXLIMIT` | `100` | Largest `limit` the list accepts |
| `db-scheduler.threads` | `DBSCHEDULER_THREADS` | `10` | Execution threads per agent instance |
| `db-scheduler.polling-interval` | `DBSCHEDULER_POLLINGINTERVAL` | `10s` | How often an instance looks for due executions |
| `db-scheduler.immediate-execution-enabled` | `DBSCHEDULER_IMMEDIATEEXECUTIONENABLED` | `true` | Runs a newly scheduled execution that is already due without waiting for the next poll |
| `db-scheduler.shutdown-max-wait` | `DBSCHEDULER_SHUTDOWNMAXWAIT` | `30s` | Bounded wait for running executions on shutdown |
| `db-scheduler.heartbeat-interval` | `DBSCHEDULER_HEARTBEATINTERVAL` | `5m` (the library default) | How often a running execution renews its heartbeat |
| `db-scheduler.missed-heartbeats-limit` | `DBSCHEDULER_MISSEDHEARTBEATSLIMIT` | `6` (the library default) | Missed heartbeats after which an execution is dead and runs again |

The `db-scheduler.*` key names and their environment forms are confirmed in the 16.12.0 starter source at implementation time (task 1.2). If the starter exposes no key for a value, the fallback wiring of D1 sets it on `SchedulerBuilder` from a key of `SchedulerProperties` with the same default. Values that stay fixed, because they are not operational (owner rule 98 keeps names, formats and schema limits as constants): the table name `scheduler_execution`, the polling strategy `fetch` (an enum value of the library), the starter's delay until the context is ready and the switched off starter statistics and health indicator (both correctness rules of D5 and D13, not tuning), the five field cron shape, the column sizes `title VARCHAR(100)` and the 4000 character body check of D7 (schema constraints that only a migration can change), and the source and kind names.

The application refuses to start when a value is zero or negative, a zone is unknown or a cron expression is invalid, and when `app.notifications.list.default-limit` is greater than `app.notifications.list.max-limit`. The delivery settings `app.notifications.retry-backoff` and `app.notifications.max-attempts` of the plan before 2026-10-08 are gone, because the retries belong to the channel's queue (D8). Keys under `app.scheduler.jobs` and `app.scheduler.notify` belong to `add-scheduled-tasks`, which binds them in its own properties class.

### D11: Erasure and export of notifications

Erasure and export of notifications are company work. `add-audit-and-gdpr-compliance` (company, build group 5) adds them later against the tables of D7: the deletion of a user's or a tenant's notifications with their deliveries, and the export of a user's notifications, called from its erasure and export orchestrator (moved there by the dependency fix of 2026-10-05, formerly task 3.7 of this change). This change does not wait for it. The tables of D7 already make that possible without a schema change: every row carries `tenant_id` and `user_id`, and no delivery execution exists (D8). Changes that write notifications add nothing for it.

### D12: Metrics, logs and traces

Names follow `add-observability` D2 and D5, singular domain first, dotted and lower case, as `add-agent-skills` D14 does:

| Metric | Type | Tags |
| :--- | :--- | :--- |
| `scheduler.executions` | counter | `task`, `outcome` |
| `scheduler.execution.duration` | timer | `task` |
| `scheduler.executions.overdue` | gauge | none |
| `notification.created` | counter | `source`, `kind` |
| `notification.deliveries` | counter | `channel`, `outcome` (`pending` when a channel queued it, `unavailable`, and the end states `delivered` and `failed` its queue reports) |

`task` takes values only from `SchedulerTaskName`. One signal per question (owner answer 93 of 2026-10-08, review item S3-7): `scheduler.executions` and `scheduler.execution.duration` are the per task counter and timer, and `scheduler.executions.overdue` is the one signal that the scheduler stalled. The starter's own Micrometer statistics repeat the counter and its health indicator repeats what the gauge shows after the threshold, so both are switched off through the starter's own settings, whose names task 1.6 reads in the 16.12.0 source. `scheduler.executions.overdue` reads `SELECT count(*) FROM scheduler_execution WHERE picked = false AND execution_time < now - overdue-threshold` at most once per scrape interval, which is the signal for "a scheduler that never fires after a deployment" named in `add-connector-framework` D19.

Logs: the scheduler thread puts `scheduler_task` and `task_instance` into the MDC, and each owning change adds its own keys. Notification titles and bodies only at DEBUG. The startup banner gets one block: scheduler running, threads, polling interval, every registered system task with its cron and zone, and the switched on notification channels.

Traces: each execution is an `Observation` named `scheduler.execution` with the task name, and the work an owning change starts inside it is its child.

### D13: Health

The overdue gauge is the one signal of a stalled scheduler and the alerting signal (owner answer 93 of 2026-10-08, review item S3-7). The starter's health indicator is switched off, so `/actuator/health` and readiness carry no scheduler entry and a scheduler problem never takes the agent out of service. A scheduler that stopped shows on the gauge once its executions are later than the overdue threshold.

### D14: Module placement

The shared scheduler engine and its system tasks (retention, syncs, sweeps) are part of `core-chat` and always on. They are never a switchable module, and nothing in this change carries `@ConditionalOnModule`, except that a system task owned by another module's change carries that module's condition (D2). The owner notification store, the `OwnerNotificationChannel` port, `ChannelActionHandler`, `/api/v1/notifications`, the retention task `record-retention` and its entry for notifications are `core-chat` too, because changes in several modules write notifications and register retention entries.

This change adds the catalog entry `scheduler` to the module catalog of `add-deployment-modules` only as the name for the assistant's own job features, with its title and description, an empty `requires` list, no `uses` entry, no compose service, no agent secret and no code of this change behind it, and adds it to the `personal` preset. `add-scheduled-tasks` fills that entry with its job tools, `owner_notify` and `/api/v1/scheduled-jobs`, and sets `requires: [subagents]` with no `uses` entry, because notification delivery, including the Discord channel of the port, is reached through `core-chat` and the job code never refers to the `channels` module. The entry is added here, before `add-agent-subagents` exists in the build order, so `ASCEND_MODULES` can name `scheduler` from the start without a missing `requires` failure.

### D15: One retention task with registered entries

Owner answer 89.7 of 2026-10-08: the agent has one retention task, and every change that keeps rows for a limited time registers what to delete instead of writing a task of its own.

- `RetentionEntry` (a core record, registered as a bean by the owning change, with that change's `@ConditionalOnModule` when it belongs to a module): `name` (a stable lower case name fixed in code, used in logs, for example `owner-notification`), `table`, `timeColumn`, `age` (a `Duration` bound from the owning change's own property, for example `app.notifications.retention`), `condition` (a fixed SQL condition written in code by the owning change that says which rows are final and may go, for example `decision <> 'pending'`, empty for every row), and optionally `keepNewestPer` (a column and a count: keep the newest rows per value of that column by `timeColumn` and delete the rest, the rule of a history cap such as 50 runs per connector). Table and column names come only from code, never from configuration or input, and the application refuses to start when one does not match the pattern of a plain SQL name or when two entries have the same name.
- `RetentionCleanup` (a core port): `String entryName()`, `void beforeDelete(RetentionRow row)`, where `RetentionRow` holds the row's `id`, its `tenant_id` and the columns the hook names. A change registers it for its own entry or for an entry of another change (for example a coding run's object store prefix on the run entry `subagent-run`). It deletes what lives outside the table (an archive, an object store prefix) and must be safe to run twice.
- The system task `record-retention` (`SchedulerTaskName` value `record-retention`, cron `app.scheduler.system-tasks.record-retention.cron`, default `15 * * * *` in `UTC`) walks every registered entry in name order. For each entry it computes the cutoff from the injected `Clock` (D6) and works in batches, one transaction per batch: select the next batch of rows older than the cutoff that meet the condition (or that fall outside the newest of `keepNewestPer`) with `FOR UPDATE SKIP LOCKED`, run every `RetentionCleanup` of the entry for each row with that row's tenant bound through `TenantContext.runAs` (D3), then delete exactly those rows. A batch whose cleanup throws is rolled back and left for the next run, and the next entry still runs. The batch size is the setting `app.scheduler.record-retention.batch-size` (environment variable `APP_SCHEDULER_RECORDRETENTION_BATCHSIZE`, default 100 rows, owner answer 98.4 of 2026-10-08, D10), named in `docs/SCHEDULING.md`. The task runs once in the cluster on db-scheduler, and running it twice deletes nothing more (owner answer 87).
- Rows that belong to a deleted row (deliveries of a notification, firings of a job, outcome records of a sync run) go with it through their foreign key `ON DELETE CASCADE` or through the entry's cleanup hook, as the owning change decides.
- One INFO line per entry and run names the entry and the number of deleted rows. The task's own executions are counted by `scheduler.executions` (D12).

This change registers the entry `owner-notification`: table `owner_notification`, time column `created_at`, age `app.notifications.retention` (30 days), condition: no delivery of the notification is still `pending`. Its deliveries go with it through their foreign key.

The entries the other changes register, each in its own tasks, replace their own retention tasks (inventory of D2): `ingestion-run` (`add-document-management-api`), `subagent-run` (`add-agent-subagents`), `approval-request` (`add-action-approvals`), `sandbox-run-workspaces` and `sandbox-chat-workspaces` (`add-agent-sandbox`), `coding-project` and a cleanup on `subagent-run` (`add-coding-agent-delegation`), `scheduled-job` and `scheduled-job-firing` (`add-scheduled-tasks`), `self-review` and `self-change` (`add-self-improvement`), and `connector-sync-run` (`add-connector-framework`, its cap of 50 runs per connector as a `keepNewestPer` rule in place of the prune on insert). Where a cap moved from insert time to this task, the owning change's read of that history limits itself to the same count, so the visible history is unchanged. The company tasks `retention` and `export-archive-cleanup` of `add-audit-and-gdpr-compliance` and the cleanup `channel-host-cleanup` of `add-openclaw-plugin-host` are not part of this answer and stay as their changes plan them.

## Required edits to other changes

This change does not edit any other change. Each edit below must be made in the named change by its owner, and the tasks there that depend on it are marked blocked.

### `add-scheduled-tasks`

1. Remove the shared scheduler engine, the system task contract, the inventory, the lock and clock rules, `CronRule`, the missed firing rule of system tasks, the notification store, the `OwnerNotificationChannel` port, `/api/v1/notifications`, notification retention and the `scheduler.*` and `notification.*` metrics, and depend on this change for all of them. Its notifications use source `scheduled_job` with the kinds of D7. Made in that change on 2026-10-02.

### `add-self-improvement`

1. Use this change's scheduler, its registration contract and its notification store and port, not those of `add-scheduled-tasks`. Its reports use source `self_improvement`, kinds `change` and `alert`, and `subject_ids` as D7 defines. Made in that change on 2026-10-02.

### `add-deployment-modules`

1. Its D3 table and the line after it: the shared scheduler engine and its system tasks (retention, syncs, sweeps) are `core-chat` and always on, never a switchable module. The owner notification store, the `OwnerNotificationChannel` port, `/api/v1/notifications` and notification retention are `core-chat` too, because `add-self-improvement` writes notifications without the `scheduler` module.
2. The catalog entry `scheduler` is added by this change only as the name for the assistant's own job features, with an empty `requires` list (D14). `add-scheduled-tasks` fills it with the job tools, `owner_notify` and `/api/v1/scheduled-jobs`, with `requires: [subagents]` and no `uses` entry (D14). Its `uses: [channels]` is removed, because notification delivery is `core-chat`.
3. Its required edit to `add-scheduled-tasks`, item 1, names this change as the owner of the engine and the system tasks.

Edits 1 to 3 are made in that change on 2026-10-03.

### `add-connector-framework` (the framework part of the former `add-document-connectors`, split of 2026-10-04)

1. Design D2, third bullet, and its "Why not Quartz" line: scheduling moves to this shared scheduler. Each enabled connector has one execution `connector-sync/<connectorId>` whose next time comes from the connector's cron and time zone through `CronRule`. Creating, updating, enabling, disabling and deleting a connector creates, reschedules or removes that execution in the same transaction. The one minute `@Scheduled` tick, the `next_run_at` column and the `FOR UPDATE SKIP LOCKED` claim are removed.
2. Design D3 and task 1.1: remove `next_run_at` from `connector`, add `time_zone VARCHAR(64) NOT NULL` (default `Europe/Warsaw`), and keep the index for the freshness check.
3. Design D19 and the `document-connectors` spec "Sync freshness check" and "Scheduled incremental sync runs per enabled connector": "claimed atomically (database row lock)" becomes "run by exactly one agent instance through the shared scheduler". The freshness check is the system task `connector-freshness-check`. The scenario "exactly one sync run is recorded for that tick" stays as written.
4. The configuration invariant (maximum sync age greater than the interval the cron fires on) uses `CronRule`'s shortest gap of the next firings.
5. Spec and API: a connector's cron schedule has five fields and a time zone, validated by the shared rule.
6. Task 1.3 drops "scheduler tick" from `ConnectorProperties`, task 2.6 is rewritten for the shared scheduler, and the Risks line "Scheduler drift with multiple agent instances" points at this change.
7. The manual trigger and its 409 while a run is in progress stay in the connector framework. Overlap of runs of one connector stays the framework's rule.

Edits 1 to 7 are made in that change (its D2, D3, D19 and D20, its `document-connectors` spec and its tasks 1.3, 2.6, 2.11 and 4.1), checked on 2026-10-03. That change also places the framework, `connector-sync` and `connector-freshness-check` in the core document search (`rag`, part of `core-chat`, not a module) with no `@ConditionalOnModule`, and sets the freshness check's default to `*/5 * * * *` in `UTC`, which the inventory of D2 follows.

### `add-obsidian-vault`

1. Design D7: the full rescan of every enabled `OBSIDIAN` connector is the system task `obsidian-vault-rescan` on this scheduler, with the five field cron `*/15 * * * *` in `Europe/Warsaw` (the same zone as `app.obsidian.zone`), registered only when the module `obsidian` is active. An `OBSIDIAN` connector has no cron and no `connector-sync` execution of its own. Its watcher triggered runs and the sync status read stay as designed, on the instance (local). Made in that change on 2026-10-02.

### `add-audit-and-gdpr-compliance`

1. Design D7 and the `data-retention` spec "Retention policy" text: the retention job is the system task `retention`, cron from `app.scheduler.system-tasks.retention.*` (default `0 3 * * *` in `Europe/Warsaw`). "Guarded by a single-owner lock (advisory lock or ShedLock)" becomes "run by exactly one agent instance through the shared scheduler", and task 8.2a's test of two concurrent invocations stays.
2. Task 8b.3: the cleanup of produced export archives is the system task `export-archive-cleanup`.
3. `specs/data-erasure/spec.md` and `specs/data-portability/spec.md`: user and tenant erasure delete `owner_notification` and `owner_notification_delivery` rows (no delivery execution exists since owner answer 89.6 of 2026-10-08, D8), and user export includes the user's notifications. The retention matrix in `docs/COMPLIANCE.md` lists notifications (30 days). Since the dependency fix of 2026-10-05 that change also owns the erasure and export code itself (D11, the former task 3.7 of this change), and it registers it later.

Edits 1 to 3 are made in that change (its design D7, its `data-retention`, `data-erasure` and `data-portability` specs and its erasure task), checked on 2026-10-03.

### `add-document-management-api`

1. Design D9: the `ingestion_runs` retention is the system task `ingestion-run-retention`. The startup sweep of task 3.5 stays a startup action. Since owner answer 89.7 of 2026-10-08 it is the entry `ingestion-run` of `record-retention` (D15), and since owner answer 87 a periodic `ingestion-run-orphan-sweep` joins the startup sweep (that change's D3).

Made in that change (its design D9 and its `ingestion-correctness` spec), checked on 2026-10-03, with the default `15 4 * * *` in `Europe/Warsaw` and no `@ConditionalOnModule`, because the document management API is part of the core document search (`rag`), which is not a module.

### `add-agent-subagents`

1. Design D14 and its retention requirement: the periodic restart sweep is the system task `run-orphan-sweep` and run retention is the system task `run-retention`. The sweep once at startup and the per run heartbeat and watchdog stay local. The run table, the run service, `/api/v1/runs` and both run sweeps are `core-chat` (owner decision of 2026-10-02), so the two task beans carry no `@ConditionalOnModule` and are always registered. Their defaults are `*/5 * * * *` in `UTC` for `run-orphan-sweep` and `45 3 * * *` in `Europe/Warsaw` for `run-retention` (D2). Made in that change on 2026-10-03. Since owner answer 89.7 of 2026-10-08 run retention is the entry `subagent-run` of `record-retention` (D15), sent to that change through the round 93 inbox.

### `add-action-approvals`

1. Design D8 and D10: the periodic expiry sweep is the system task `approval-expiry-sweep` with the cron `* * * * *` (every minute) in `UTC`, with no fixed delay and no `app.approvals.sweep-interval`, and decided request retention is the system task `approval-retention` with `30 3 * * *` in `Europe/Warsaw`. The run once at startup before readiness stays. The expiry notice is an owner notification with source `approval` and kind `expired` (D7). Made in that change on 2026-10-02. Since owner answers 89.7 and 93 of 2026-10-08 retention is the entry `approval-request` of `record-retention` (D15), and that change inserts its pair `approval`, `expired` into `owner_notification_kind` with its own migration (D7).

### `add-agent-sandbox`

1. The close of idle, expiring and orphan chat workspaces is the system task `sandbox-chat-idle-sweep` (`*/5 * * * *`), and the retention of workspace records and archives is `sandbox-workspace-retention` (`15 * * * *`, since owner answer 89.7 of 2026-10-08 the entries `sandbox-run-workspaces` and `sandbox-chat-workspaces` of `record-retention` with an archive cleanup hook, D15), both registered in every deployment with no `@ConditionalOnModule`, because the sandbox is core (owner decision of 2026-10-03), and both in zone `UTC` (D2), and the system task `sandbox-destroy-retry` it named until 2026-10-08 is removed (answer 93 of 2026-10-08). The reaper stays inside the runner service, which has no agent database, and its README states that it is not on the shared scheduler. Made in that change on 2026-10-02, the zone and the core registration on 2026-10-03.

### `add-file-download`

1. A download is deleted 24 hours after its last download (owner answer 47.2 of 2026-10-02): a new download of the same file starts the 24 hours again. Until 2026-10-04 the deletion was the system task `web-download-retention` on this scheduler. Owner instruction of 2026-10-04 (owner rule of the same day, `add-file-download` is web-hunter work of build group 2 and depends on no agent change) moved it into ascend-web-hunter as a sweep of its own (`add-file-download` D7 and task 6.9), so this scheduler has no `web-download-retention` task and the inventory of D2 no longer lists it.

### `add-coding-agent-delegation`

1. Its free space check is the system task `coding-area-free-space-check` (`*/15 * * * *`) and its run output retention is the system task `coding-run-retention` (`30 * * * *`, since owner answer 89.7 of 2026-10-08 the entry `coding-project` of `record-retention` and a cleanup hook on the entry `subagent-run`, D15), both registered only when the module `coding` is active and both in zone `UTC` (D2). Made in that change on 2026-10-02, and the zone on 2026-10-03.
2. Its low space warning and its cleanup notice are owner notifications of this change with source `coding_area` and the kinds `low_space` and `cleanup` (D7), so its required edit for the notification source is addressed to this change, not to `add-scheduled-tasks`, and it needs no wait for `add-scheduled-tasks`. The cleanup approval is kind `coding_project_cleanup` with category `workspace_cleanup`. Made in that change on 2026-10-03. Since owner answer 93 of 2026-10-08 that change inserts its two pairs into `owner_notification_kind` with its own migration (D7).

### `add-tenant-isolation`

1. List `owner_notification.tenant_id` and `owner_notification_delivery.tenant_id` with the other tenant columns, and add their foreign keys to `tenants(id)` in its own migration, with no backfill.
2. Worker threads: a scheduler thread that runs work of one tenant binds that tenant with `TenantContext.runAs` before any other step and fails closed when it cannot. Since the dependency fix of 2026-10-05 this change does that itself (D3), so `add-tenant-isolation` adds nothing for it.

Item 1 is listed for that change in the tables list of the dependency fix of 2026-10-05. It lands last (company, build group 5), and no task of this change waits for it.

### `add-keycloak-login`

1. Its role matrix: `/api/v1/notifications/**` needs an authenticated caller and is scoped by the controller to the caller's own notifications. `add-keycloak-login` lands before this change, so this change adds the row itself (D9, task 3.5), and the D4 table of later changes of `add-keycloak-login` lists it (split of 2026-10-04 from `add-auth-and-identity`).

### `add-self-built-integrations`

1. Its reconciler runs as the system task `integration-reconcile` on this scheduler, with the cron `* * * * *` (every minute) in `Europe/Warsaw`, registered only when the module `self-built-integrations` is active, in place of its `reconcile-interval` loop. It is safe to run twice, because a reconcile compares the wanted state with the runner's state and changes only what differs. Its local refresh of the integration MCP entries is listed in the local timers table of D2. Made in that change on 2026-10-03.

### `add-openclaw-plugin-host`

1. Implement `OwnerNotificationChannel` named `discord`: `canReach` is true when the notification's user has an active Discord link, and `deliver` writes one direct message to that linked account into `channel_outbox`, with the title, the body cut to the platform limit with a visible note, and the run id. Outbox acceptance is delivery from the agent's side. For source `self_improvement` it renders one Undo button per id in `subject_ids` (the edit `add-self-improvement` lists). Since owner answer 89.6 of 2026-10-08: `deliver` runs inside the caller's transaction, `channel_outbox` is the one retry layer and reports the end state through `recordDeliveryOutcome`, the buttons come from the notification's `actions`, and every press goes through `POST /api/v1/channel-host/actions` with an action type (D8, sent through the round 93 inbox).
2. The channel bean is part of its module, so without that module no Discord delivery row is written as `pending`.
3. The cleanup of its tables is the system task `channel-host-cleanup` on this scheduler, `0 4 * * *` in `Europe/Warsaw`, registered only when the module `channels` is active. Its event stream checks and its loop guard are listed in the local timers table of D2.

Edits 1 to 3 are made in that change on 2026-10-03.

### `add-flutter-chat-app`

1. A notification list screen reading `GET /api/v1/notifications` when the app opens, when it returns to the foreground and on pull to refresh, with an unread badge, a detail view, and `POST /api/v1/notifications/{id}/read` when a notification is opened. Push stays out of scope, and a push channel later is one more implementation of the notification port.

Made in that change (its design, the `/notifications` screen, `NotificationsApi` and `OwnerRefreshNotifier`), checked on 2026-10-03.

### Edits of 2026-10-08 (owner answers 89.3, 89.6, 89.7 and 93)

Each edit below is sent to its change through the inbox of the planning round of 2026-10-08 and made there by its owner. No task of this change waits for any of them.

- `add-deployment-modules`: `McpReconnectScheduler` runs as `@Scheduled` on Spring Boot's auto-configured `TaskScheduler`, and that change switches on `@EnableScheduling` (answer 89.3, made in the same worker's folders).
- `add-openclaw-plugin-host`: `channel_outbox` is the one retry layer and reports the end state of an owner notification through `recordDeliveryOutcome`, `deliver` writes its outbox row inside the caller's transaction, every button goes through the one action endpoint `POST /api/v1/channel-host/actions` with an action type and the one host namespace `ascend`, and it registers the handlers `approval_approve` and `approval_deny` (answer 89.6).
- `add-self-improvement`: its reports carry `self_improvement_undo` entries in `actions`, it registers the handler of that action type and drops `ascend-notify` and `POST /api/v1/channel-host/notifications/actions`, the notification `read_at` replaces its seen time and `POST /changes/seen`, its retention is two entries of `record-retention`, and its migration inserts its pairs into `owner_notification_kind` (answers 89.6, 89.7 and 93).
- `add-flutter-chat-app`: the "What I learned" badge counts the changes of unread `self_improvement` notifications, and opening the screen marks them read with `POST /api/v1/notifications/{id}/read` (answer 89.6).
- `add-self-built-integrations`: an automatic disable also creates an owner notification of source `integration` and kind `auto_disabled`, one for every `ADMIN` of the tenant (owner answer 98.10 of 2026-10-08), its credential approval buttons use the one action endpoint, and its migration inserts the pair (answers 89.6 and 93).
- `add-coding-agent-delegation`, `add-action-approvals`, `add-scheduled-tasks`: their migrations insert their pairs into `owner_notification_kind` (answer 93), and their retention tasks become entries of `record-retention` (answer 89.7).
- `add-agent-sandbox`, `add-agent-subagents`, `add-connector-framework`: their retention tasks, and the connector history cap, become entries of `record-retention` (answer 89.7).
- `add-audit-and-gdpr-compliance` (company, build group 5): notification erasure deletes notification and delivery rows, with no delivery execution to delete (answer 89.6, wording only).

### Checked, no edit needed

- `upgrade-spring-boot-4`: its D19 already defines the `errors` field, and this change adds its own code to `ApiErrorCode` the way every sibling change does. Its Flyway setup is used as is.
- `add-agent-skills`: its skill folder rescan is local work (D2) and stays where it is. It reads the tenant through `TenantContext` of `add-keycloak-login`, as this change does.
- `add-observability`: this change follows its naming rules and adds its metrics to `docs/OBSERVABILITY.md` itself.

## Risks / Trade-offs

- [The starter is built against Spring Boot 4.0.6 and the agent runs 4.1.1] → task 1.2 starts the real context and runs an execution. The fallback wiring of D1 keeps the same library if the starter fails.
- [The library's dead execution path runs a handler twice] → every handler must be safe to run twice, the contract of D2 says so, and this change's own task deletes in batches with a conditional delete, so a second run deletes nothing more.
- [A record and its execution drift apart] → both change in one transaction through the transaction aware data source (D5). Each owning change with per record executions adds its own startup consistency check.
- [Polling adds up to 10 seconds of delay] → acceptable for minute precision schedules, including the every minute approval expiry sweep and integration reconcile. Immediate execution covers work that is due at once.
- [Daylight saving behaviour of Spring's cron engine differs from the spec] → tests pin both transitions, and `CronRule` adjusts where needed (D4).
- [Notifications pile up when no channel is switched on] → they are stored, readable and deleted after 30 days.
- [Every other change must register on the shared scheduler] → the inventory and the required edits name each one, and this change is build group 3, position 7 of the owner build order of 2026-10-04, before every change that needs it.
- [The closed source and kind lists must grow with new changes] → a new pair is one row that the owning change inserts with its own versioned migration and one spec line, and the foreign key `owner_notification_kind_fk` refuses a pair no change inserted.
- [A channel's queue never reports an end state] → the delivery stays `pending` and its notification is kept past its retention until the report comes, as before. The channel's own queue has its attempts and its `dead` state, so every message ends.
- [Cleanup hooks of a retention entry fail] → the batch is rolled back and tried again at the next run, and the other entries still run (D15).

## Migration Plan

1. This change lands after `upgrade-spring-boot-4`, `add-keycloak-login` and `add-deployment-modules`, and before every change in the inventory of D2. Flyway creates `scheduler_execution`, `owner_notification` and `owner_notification_delivery`. With no task of another change registered, the scheduler runs only `record-retention`, with its one entry `owner-notification`, on an empty table.
2. Each owning change registers its system tasks, its retention entries and its notification source and kind pairs as it lands.
3. No data to migrate. The owner decided on 2026-10-02 (confirmed by owner answer 73.1 of 2026-10-06) that there is no existing data to keep, which holds only until the first real customer deployment.
4. Rollback: deploy the previous image. Tables stay and are ignored. Executions whose task name no bean resolves fall under the library's unresolved task rule, which task 1.6 reads in the 16.12.0 source and records in `docs/SCHEDULING.md` instead of assuming it. Flyway runs forward only, so removing the tables is a new versioned migration, written only if the owner asks.

## Owner decisions of 2026-10-06

Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores. Its tables start empty, nothing is migrated or backfilled, and it needs none of today's data.

## Owner decisions of 2026-10-07

Answer 75.1: the owner approved the fixes of the review of 2026-10-07. In this change they fix item 16 (the tasks name this change position 6 of build group 3) and item 54 (document search `rag` is called part of the core `core-chat`, never a module, in the D2 inventory, the text after it and the required edits).

## Owner decisions of 2026-10-08

Answer 87 (rule R1): several agent instances run at once. Every mechanism of this change works with several instances: db-scheduler runs each due execution on exactly one instance, the retention task deletes in batches with `FOR UPDATE SKIP LOCKED`, notifications and their deliveries are Postgres rows written in the caller's transaction, the channel's queue (`channel_outbox`) wakes the event stream through Postgres `NOTIFY` with a poll fallback, and the action handlers keep no state. Local work runs on each instance's auto-configured `TaskScheduler` only where every instance must do it for itself (D2).

Answer 88 (rule R2): the company work this change plugs into stays as planned: the erasure and export of notifications by `add-audit-and-gdpr-compliance` (D11), the tenant foreign keys of `add-tenant-isolation`, and that change's company tasks `retention` and `export-archive-cleanup`, which answer 89.7 does not fold into `record-retention`.

Answer 89.3: the agent has two timers, db-scheduler for persistent and cluster-wide work, and Spring Boot's auto-configured `TaskScheduler` with `@Scheduled` for local work. No change builds a private timer thread. `McpReconnectScheduler` of `add-deployment-modules` uses `@Scheduled`, and that change switches on `@EnableScheduling` because it lands first (D2 and its local timers table).

Answer 89.6: one retry layer, the channel's own queue (`channel_outbox` of `add-openclaw-plugin-host` for Discord), chosen because that outbox carries every outbound message and retries anyway. `owner_notification_delivery` loses its attempt counter and only records where a notification went and the end state the channel reports. The delivery retry task, `OwnerNotificationCreatedEvent` and the settings `retry-backoff` and `max-attempts` are gone. Every button is an `actions` entry with an action type, pressed through the one action endpoint `POST /api/v1/channel-host/actions` and handled by the `ChannelActionHandler` of its action type. The notification `read_at` is the only seen marker. Every alert of every change is created through `OwnerNotificationService` (D7, D8, D10, D11, D12, D14).

Answer 89.7: one retention task, `record-retention`, with entries registered by the owning changes (table, time column, age, condition, optionally a keep-newest rule and cleanup hooks). It replaces eight retention tasks and the connector history prune on insert (D2, D15).

Answer 93: review item S3-8, the allowed source and kind pairs live in `owner_notification_kind`, this change's migration inserts none, and each later change inserts its own pairs with its own migration (D7). Review item S3-7, one signal per question: the starter's Micrometer statistics and health indicator are switched off, and the overdue gauge is the one stall signal (D12, D13). Review item group 3 S2-5 (delivery rows before any channel exists) is applied only as far as answer 89.6 goes: the delivery table stays, without retries, because it records the end state the Discord channel reports.

Answer 91.3: the stack changing retention spec of task 5.5 is removed, because the `ManualScheduler` tests of tasks 2.8 and 3.6 prove the same rule without restarting the agent and without a test-only schedule override. The notifications API spec (task 5.3) and the scheduler state spec (task 5.4) stay as the one deterministic spec of each capability.

Answer 93 (received from `add-agent-sandbox`): `add-agent-sandbox` removes its system task `sandbox-destroy-retry`, because the runner removes a workspace container itself at its expiry and `sandbox-chat-idle-sweep` now also closes the records of workspaces the runner already expired. Its one agent side system task is `sandbox-chat-idle-sweep`, next to its two retention entries (D2 inventory and the required edits to `add-agent-sandbox`).

Answer 94.5: the new change `scale-ocr-and-audio-across-containers` takes build group 3, position 5, directly after `harden-cloud-deployment`, so this change moves from position 6 to position 7 (`openspec/BUILD_ORDER.md`), and the positions of the other moved changes it names were moved by one too. Its dependencies and its tasks do not change.

Answer 98: every value with a default is a setting read from an environment variable, passed by the `ascend-agent` service of `compose.yaml` as `${VAR:-default}`, with the same default in code, and listed in `apps/ascend-agent/docs/CONFIGURATION.md` with "Added by `add-shared-scheduler`." (D10, tasks 1.2, 1.9, 1.10, 2.8, 3.9 and 3.11). Made external: `APP_SCHEDULER_DEFAULTTIMEZONE` (`Europe/Warsaw`), `APP_SCHEDULER_OVERDUETHRESHOLD` (`5m`), `APP_SCHEDULER_SYSTEMTASKS_RECORDRETENTION_CRON` (`15 * * * *`), `APP_SCHEDULER_SYSTEMTASKS_RECORDRETENTION_TIMEZONE` (`UTC`), `APP_SCHEDULER_RECORDRETENTION_BATCHSIZE` (`100`), `APP_NOTIFICATIONS_RETENTION` (`30d`), `APP_NOTIFICATIONS_LIST_DEFAULTLIMIT` (`20`), `APP_NOTIFICATIONS_LIST_MAXLIMIT` (`100`), `DBSCHEDULER_THREADS` (`10`), `DBSCHEDULER_POLLINGINTERVAL` (`10s`), `DBSCHEDULER_IMMEDIATEEXECUTIONENABLED` (`true`), `DBSCHEDULER_SHUTDOWNMAXWAIT` (`30s`), `DBSCHEDULER_HEARTBEATINTERVAL` (`5m`, the library default) and `DBSCHEDULER_MISSEDHEARTBEATSLIMIT` (`6`, the library default). The cron and zone of every other system task follow the same form, `APP_SCHEDULER_SYSTEMTASKS_<NAME>_CRON` and `_TIMEZONE`, added by its owning change (D2). The key names of the db-scheduler starter stay a read of its 16.12.0 source at implementation time (task 1.2), never a guess. Kept as constants, because they are not operational: the table name `scheduler_execution`, the polling strategy `fetch` (a library enum value), the starter's startup delay and its switched off statistics and health indicator (correctness rules of D5, D12 and D13), the five field cron shape and the one minute shortest step (the format of D4), the column sizes and the 4000 character body check of D7 (schema constraints a migration changes), and every task, source, kind, metric and error code name.

Answer 98.4: the batch of `record-retention` is 100 rows, the setting `app.scheduler.record-retention.batch-size` (`APP_SCHEDULER_RECORDRETENTION_BATCHSIZE`, D10, D15, task 2.8, the `shared-scheduler` scenario "Batches of the configured size"). The batch size is no longer a constant chosen at implementation.

Answer 98.10: every user with the `ADMIN` role in the tenant of a disabled integration gets its own `auto_disabled` owner notification of source `integration`, because a notification has one user. `add-self-built-integrations` creates them (D7 and its sources table, the edits of 2026-10-08, the `owner-notifications` spec).
