## Purpose

Gives ascend-agent one persistent, cluster safe scheduler that runs every piece of timed and periodic work that changes shared state, so connector syncs, the Obsidian vault rescan, retention and sweep jobs, integration reconciles, self-improvement work and the assistant's own jobs all fire once per due time, survive a restart, and are tested and measured the same way.

## ADDED Requirements

### Requirement: One persistent scheduler runs all shared timed work

The agent SHALL run every timed or periodic task that writes shared state (PostgreSQL, Redis, the object store, Qdrant, notifications, a connector source or another service of the deployment) on one shared scheduler whose pending executions are stored in PostgreSQL in one table created by a Flyway versioned SQL migration, with every constraint and index named explicitly. The shared scheduler SHALL be part of the always active `core-chat` module, so it runs whatever modules are switched on. A due execution SHALL be run by exactly one agent instance, even when several instances run against the same database. A pending execution SHALL survive a restart of every agent instance. No change SHALL add a second persistent scheduler, a second scheduling lock table or a hand written lock (such as `FOR UPDATE SKIP LOCKED` on its own rows, a Postgres advisory lock or ShedLock) for periodic work.

#### Scenario: Two instances, one execution

- **WHEN** two agent instances run against one database and a periodic task comes due
- **THEN** the task's work runs exactly once for that due time

#### Scenario: Pending execution survives a restart

- **WHEN** a one time execution is due in 10 minutes and every agent instance is stopped and started again within those 10 minutes
- **THEN** the execution runs at its due time

#### Scenario: Schema created by Flyway

- **WHEN** the agent starts against an empty PostgreSQL database
- **THEN** Flyway applies the migration and the execution table with its named indexes exists
- **AND** Flyway validation of the applied migrations passes

### Requirement: Work that only concerns one instance stays local

A periodic task whose only effect is to refresh the memory of one agent instance, or to prove that one instance is alive (for example a skill folder rescan, a run heartbeat renewal or a status file read into memory), SHALL run on each instance's local task scheduler and SHALL NOT be stored on the shared scheduler. The local task scheduler SHALL be the one task scheduler that the application framework configures for the agent, used through scheduled methods, so the agent has two timers only: the shared scheduler and that one local task scheduler. No change SHALL create a private timer thread or thread pool for timed work. A task that writes shared state SHALL NOT run on the local task scheduler.

#### Scenario: Heartbeat stays local

- **WHEN** two agent instances each own a running background run
- **THEN** each instance renews its own runs' heartbeats on its own schedule, and no shared execution exists for heartbeat renewal

#### Scenario: One local timer

- **WHEN** the agent runs with every module of the `personal` preset
- **THEN** every local periodic task runs on the one task scheduler that the application framework configures, and no other scheduler thread pool exists

### Requirement: System tasks are registered through one contract

A change SHALL add a periodic task to the shared scheduler only as a system task with a name from one closed set fixed in code, a schedule read from configuration under the task's name, and a handler that is safe to run twice. The schedule SHALL be a five field cron expression with a time zone, so the shortest step between two runs is one minute, and no other schedule shape SHALL be accepted. A system task that belongs to a module SHALL be registered only when that module is active. The agent SHALL refuse to start when a registered system task has a name outside the closed set, has no configured cron expression, or has a cron expression without a time zone, and the refusal SHALL name the key. Work that belongs to one record (a delayed review, one connector's sync) SHALL be a one time execution keyed by that record's id, created, moved and removed in the same transaction as the record.

#### Scenario: Missing schedule refuses startup

- **WHEN** a system task is registered and its cron expression is not configured
- **THEN** the agent does not start and the failure report names the missing configuration key

#### Scenario: Sweep every minute

- **WHEN** a system task is configured with the cron expression `* * * * *` in `UTC`
- **THEN** it runs once per minute on exactly one instance

#### Scenario: Record and execution commit together

- **WHEN** a record and its one time execution are created in one transaction and the transaction rolls back
- **THEN** neither the record nor the execution exists

### Requirement: One cron format and an explicit time zone

Every cron expression the agent accepts, from configuration, from a connector, from the REST API or from an agent tool, SHALL have exactly five fields (minute, hour, day of month, month, day of week) and SHALL be validated by one shared rule. Every cron expression SHALL be evaluated in a named IANA time zone (for example `Europe/Warsaw` or `UTC`). An expression with another number of fields, an unknown field value or an unknown time zone SHALL be refused with a message that names the expression or the zone and what is wrong with it. When a local time a cron expression names does not exist on a day because the clock moves forward, the firing SHALL happen at the first moment after the gap. When a local time happens twice on a day because the clock moves back, the expression SHALL fire once, at the first of the two moments. All times SHALL be stored and returned as UTC instants.

#### Scenario: Six fields refused

- **WHEN** a cron expression `0 0 7 * * *` is submitted
- **THEN** it is refused with a message stating that a cron expression has five fields

#### Scenario: Unknown zone refused

- **WHEN** a schedule with the time zone `Europe/Warsow` is submitted
- **THEN** it is refused with a message naming `Europe/Warsow` as an unknown time zone

#### Scenario: Spring forward

- **WHEN** a cron expression `30 2 * * *` runs in `Europe/Warsaw` and on 2027-03-28 the clock moves from 02:00 to 03:00
- **THEN** on 2027-03-28 it fires at 03:00 Warsaw time

#### Scenario: Fall back

- **WHEN** a cron expression `30 2 * * *` runs in `Europe/Warsaw` and on 2026-10-25 the clock moves from 03:00 back to 02:00
- **THEN** on 2026-10-25 it fires exactly once

### Requirement: An overdue system task runs once

When a periodic system task is overdue because no agent instance was running at its due times, it SHALL run once as soon as an instance starts, never once for every missed due time, and its next due time SHALL then follow its schedule from the time it finished.

#### Scenario: Retention after a long stop

- **WHEN** a daily retention task missed three due times while the agent was stopped, and the agent starts
- **THEN** the retention task runs once
- **AND** its next due time is the next scheduled time after that run

### Requirement: Time is read from one clock

Every part of the agent that schedules work or decides by time SHALL read the time from one injected clock, so tests can move time without waiting. No test of timed work SHALL wait for real time to pass.

#### Scenario: Time moved in a test

- **WHEN** a test moves the injected clock one day forward and runs the due executions
- **THEN** a daily system task runs once, with no wait for real time

### Requirement: Shutdown stops the scheduler first, and an interrupted execution runs again

On a graceful shutdown the agent SHALL stop picking new executions, SHALL wait a bounded time (default 30 seconds) for running executions, and SHALL stop the scheduler before the database connection pool closes. An execution that was running when its instance stopped or died SHALL be detected and run again by a live instance, so every task handler SHALL be safe to run twice for the same due time.

#### Scenario: Killed instance

- **WHEN** an agent instance is killed while it runs a system task
- **THEN** a live instance runs that task again after the dead execution is detected
- **AND** the task's effect is the same as one complete run

### Requirement: The scheduler is visible

The agent SHALL log at startup whether the scheduler is running and the names of the registered system tasks with their schedules and time zones, and SHALL publish: a counter of executions by task name and outcome (`succeeded`, `failed`), a timer of execution duration by task name, and a gauge of executions that are due for longer than a configured threshold (default 5 minutes) and not picked. The gauge SHALL be the one signal of a stalled scheduler: the agent SHALL NOT publish a second set of execution statistics or a scheduler health entry that repeat what the counter and the gauge show. Task names in metric tags SHALL come from the closed set fixed in code, never from user input, a record id or a tenant id. One log line SHALL be written per failed execution with the task name, the task instance and the error.

#### Scenario: A stalled scheduler shows

- **WHEN** executions stay due and unpicked for longer than the threshold
- **THEN** the overdue gauge is greater than zero

#### Scenario: A healthy scheduler shows no overdue execution

- **WHEN** the agent has run for longer than the overdue threshold and every due execution was picked
- **THEN** the overdue gauge reads zero

#### Scenario: Failed execution is counted

- **WHEN** a system task throws an exception
- **THEN** the execution counter with that task name and outcome `failed` grows by one
- **AND** one log line names the task and the error

### Requirement: A handler acts with the tenant of its row

A scheduler handler that acts for a stored row SHALL bind the tenant stored on that row through `TenantContext.runAs` before any other step, and the code it calls SHALL read the tenant only through `TenantContext.currentTenantId()`. A system task that walks rows of several tenants SHALL bind each row's tenant for the work on that row. A handler that cannot read the tenant of its row SHALL fail the execution and SHALL NOT run with no tenant or a guessed one.

#### Scenario: A per record execution runs with its row's tenant

- **WHEN** a per record execution whose row carries tenant `default` runs on a scheduler thread
- **THEN** the code it calls reads tenant `default` through `TenantContext.currentTenantId()`
- **AND** after the handler returns, nothing is bound on that thread

#### Scenario: A row without a tenant fails closed

- **WHEN** a per record execution runs for a row whose tenant cannot be read
- **THEN** the execution fails and the handler body does not run

### Requirement: One retention task deletes old rows of every change

The agent SHALL have exactly one system task that deletes rows a change keeps for a limited time. Each change SHALL register what it keeps as a retention entry fixed in code: a table, a time column, an age bound from that change's own configuration, a condition that says which rows are final, and optionally a rule that keeps the newest rows per value of a column. A change MAY register a cleanup for an entry that deletes what lives outside the table, which SHALL run with the row's tenant bound before the row is deleted. No change SHALL add a retention task of its own. The task SHALL delete in batches of a configured size (default 100 rows), SHALL leave a batch whose cleanup fails for the next run without stopping the other entries, and SHALL be safe to run twice. An entry of a module SHALL be registered only when that module is active.

#### Scenario: Old final rows go, others stay

- **WHEN** an entry keeps rows for 30 days with the condition that the row is final, and the task runs with one final row 31 days old, one final row 29 days old and one row 40 days old that is not final
- **THEN** only the first row is deleted, and a second run deletes nothing more

#### Scenario: Batches of the configured size

- **WHEN** the batch size is set to 2 and an entry has 5 final rows older than its age
- **THEN** one run of the task deletes all 5 rows, in batches of at most 2 rows each

#### Scenario: History cap

- **WHEN** an entry keeps the newest 50 rows per connector and one connector has 52 rows
- **THEN** after the task runs that connector has the newest 50 rows

#### Scenario: Cleanup before the row

- **WHEN** an entry has a cleanup that deletes an archive and the cleanup of one row fails
- **THEN** that batch keeps its rows and archives for the next run, and the next entry still runs
