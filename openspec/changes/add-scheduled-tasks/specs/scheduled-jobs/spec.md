## Purpose

Lets the owner and the assistant keep jobs that the assistant runs on its own at a given time or on a repeating schedule, such as a reminder, a morning briefing, a calendar check or a price watch, each with its own text, time zone and, for a job that thinks, its own tools and cost limit, managed through a REST API and kept inside the caller's tenant.

## ADDED Requirements

### Requirement: A scheduled job is a stored record

The agent SHALL store each scheduled job in PostgreSQL in a table created by a Flyway versioned SQL migration, with every constraint and index named explicitly. A job SHALL hold: id, tenant id, user id (the user the job acts for and notifies), the job kind, origin (`owner` or `agent`), the user who created it, the conversation and request it was created in when it was created in a chat, a name (1 to 100 characters, unique among the user's jobs that are not final), the prompt, the schedule type and its values, the time zone, an optional start time, an optional end time, an optional maximum number of firings, the state and the reason for a pause, the number of firings so far, the number of failed firings in a row, the time of the last firing, the creation and update times and a version that changes on every update. A job of kind `task` SHALL also hold the tools the run may use, an optional model, the cost limit and the token limit of one firing, and the delivery mode. An applied migration file SHALL NOT be edited.

#### Scenario: Deleting a conversation keeps its scheduled jobs

- **WHEN** the owner deletes a conversation that started a scheduled job
- **THEN** the job keeps running with `origin_conversation_id` null

#### Scenario: Job is stored with its schedule

- **WHEN** the owner creates a `task` job named `morning-briefing` with a cron schedule `0 7 * * 1-5` in `Europe/Warsaw`
- **THEN** reading the job returns the name, the kind `task`, the cron expression, the time zone, the state `active` and the next firing time 07:00 Warsaw time of the next weekday, given in UTC

### Requirement: Two job kinds

A job SHALL have the kind `reminder` or `task`. A `reminder` SHALL hold a text of 1 to 4000 characters that is sent to the user as it is, and SHALL NOT hold tools, a model, limits or a delivery mode. A `task` SHALL hold a prompt of 1 to 8000 characters for a background run, its tools, its limits and its delivery mode, and MAY hold a model. A request that gives a `reminder` tools, a model, limits or a delivery mode SHALL be refused with a validation error that names the field.

#### Scenario: Reminder with tools refused

- **WHEN** a `reminder` job is submitted with the tool `web_search`
- **THEN** the request is refused with a validation error naming `tools`

#### Scenario: Plain reminder stored

- **WHEN** the owner creates a `reminder` job with the text "Call the bank" for tomorrow at 15:00
- **THEN** the job is `active`, of kind `reminder`, with no tools, no model and no limits

### Requirement: Three kinds of schedule

A job SHALL have exactly one schedule type:

- `once`: a single firing at a given date and time. The time SHALL be given either as a local date and time without an offset, read in the job's time zone, or as an instant with an offset.
- `cron`: firings at the times a five field cron expression matches in the job's time zone, under the cron rules of the shared scheduler.
- `interval`: firings every fixed duration, measured in elapsed time from the job's start time (or its creation time when it has no start time), whatever the time zone and daylight saving.

A schedule SHALL be refused when it has no firing in the future, when its first firing is more than the configured horizon away (default 366 days), when two of its next 50 firings are closer together than the configured shortest interval (default 15 minutes), when an `interval` is shorter than that shortest interval, or when its end time is not after its start time. A job SHALL stop firing after its end time or after its maximum number of firings, and then SHALL move to `completed`.

#### Scenario: One time reminder in local time

- **WHEN** the owner creates a `once` job for local time `2026-10-05T15:00` without an offset and no time zone
- **THEN** the job fires once at 15:00 Warsaw time on 2026-10-05, which is 13:00 UTC
- **AND** then the job is `completed`

#### Scenario: Too frequent cron refused

- **WHEN** a job with the cron expression `*/5 * * * *` is submitted and the shortest interval is 15 minutes
- **THEN** the request is refused with a validation error that names the shortest interval

#### Scenario: Interval ignores daylight saving

- **WHEN** a job fires every 6 hours and a daylight saving change happens in its time zone between two firings
- **THEN** the two firings are exactly 6 hours of elapsed time apart

#### Scenario: Maximum number of firings

- **WHEN** a job with a maximum of 3 firings has fired 3 times
- **THEN** it is `completed` and fires no more

### Requirement: Every job has its own time zone

Each job SHALL store an IANA time zone. A job created without a time zone SHALL get the configured default (`Europe/Warsaw`). A `cron` time and a local `once` time SHALL be read in that zone, and a local time that is skipped or repeated by a daylight saving change SHALL follow the daylight saving rule of the shared scheduler. All times in the API and the database SHALL be stored and returned as UTC instants, and the job view SHALL also show the next firing as a local time in the job's zone.

#### Scenario: Default zone

- **WHEN** the owner creates a job without a time zone
- **THEN** the job view shows the time zone `Europe/Warsaw`

#### Scenario: Spring forward

- **WHEN** a job runs daily at 02:30 in `Europe/Warsaw` and on 2027-03-28 the clock moves from 02:00 to 03:00
- **THEN** on 2027-03-28 the job fires at 03:00 Warsaw time

### Requirement: Job states move in one direction to a final state

A job SHALL be in one of `active`, `paused`, `completed` or `cancelled`. The allowed moves SHALL be `active` to `paused`, `paused` to `active`, `active` to `completed`, `active` to `cancelled` and `paused` to `cancelled`. `completed` and `cancelled` SHALL be final. A paused job SHALL keep its schedule and SHALL NOT fire. A paused job SHALL record why it was paused: `owner`, `agent`, `failures`, `owner_unavailable` or `policy`. Resuming a job SHALL continue from the next firing time after the moment it was resumed and SHALL NOT fire for times passed while it was paused. A change of state that is not allowed SHALL be refused and SHALL NOT change the job.

#### Scenario: Paused job does not fire

- **WHEN** a job is paused before its firing time and resumed after it
- **THEN** no firing happens for that time
- **AND** the next firing is the first scheduled time after the resume

#### Scenario: Cancelled job cannot be resumed

- **WHEN** the owner resumes a `cancelled` job
- **THEN** the request answers 409 and the job stays `cancelled`

### Requirement: Limits keep jobs bounded

The agent SHALL refuse to create or resume a job when the user already has the configured number of `active` and `paused` jobs (default 20) or the tenant has the configured number (default 100). For a `task`, the cost limit of one firing SHALL default to 0.25 US dollars and the token limit to 100000, and neither SHALL be above the per run limit of background runs. A job SHALL NOT have a time limit of its own. A run started by a firing SHALL keep the general run deadline of background runs. A value of zero or below SHALL be refused. Every limit SHALL be a configuration value, except the size of a reminder text, which SHALL be the body limit of an owner notification (4000 characters), and the agent SHALL refuse to start when a configured limit is zero or negative. The counted limits SHALL hold when several agent instances serve the same tenant at once.

#### Scenario: Too many jobs

- **WHEN** a user with 20 jobs that are not final creates another job
- **THEN** the request is refused with the code `scheduled_job_limit_reached`, which names the limit

#### Scenario: Cost limit above the run limit

- **WHEN** a `task` job is submitted with a cost limit of 5.00 US dollars and the per run limit is 1.00
- **THEN** the request is refused with a validation error naming both values

#### Scenario: Two instances cannot pass one limit together

- **WHEN** a user has 19 jobs that are not final and two agent instances create a job for that user at the same moment
- **THEN** exactly one create succeeds and the other is refused with the code `scheduled_job_limit_reached`

#### Scenario: Time limit not accepted

- **WHEN** a job is submitted with a time limit
- **THEN** the request is refused with a validation error naming the unknown field

### Requirement: The owner manages jobs through REST

The agent SHALL expose:

- `POST /api/v1/scheduled-jobs`: create a job, answering 201 with the job view and a `Location` header.
- `GET /api/v1/scheduled-jobs`: list jobs, newest first, with optional filters `state` (repeatable), `kind` and `origin`, and cursor pagination (`limit` at most the configured maximum, default 100, a configured page size when `limit` is absent, default 20, and an opaque `cursor`).
- `GET /api/v1/scheduled-jobs/{id}`: one job, with an `ETag` that changes on every update, answering 304 to a matching `If-None-Match`.
- `PATCH /api/v1/scheduled-jobs/{id}`: change the name, prompt, schedule, time zone, start, end, maximum firings, and for a `task` the tools, model, limits or delivery mode. The kind SHALL NOT change. It SHALL require `If-Match` and SHALL answer 412 when the version has changed. A changed schedule SHALL replace the pending firing.
- `POST /api/v1/scheduled-jobs/{id}/pause` and `POST /api/v1/scheduled-jobs/{id}/resume`.
- `POST /api/v1/scheduled-jobs/{id}/trigger`: fire the job once now, without changing its schedule, answering 202 with the firing. It SHALL be refused with 409 and the code `scheduled_job_state_conflict` for a `paused` job and for a final job, recording no firing, and counts against the daily firing limit.
- `DELETE /api/v1/scheduled-jobs/{id}`: cancel the job, answering 204. Cancelling a cancelled job SHALL answer 204 again without change.
- `GET /api/v1/scheduled-jobs/{id}/firings`: the firing history of a job, newest first, with cursor pagination.

Every error SHALL be the agent's RFC 7807 problem detail with a stable `code`: `scheduled_job_not_found` (404), `scheduled_job_limit_reached` (409), `scheduled_job_state_conflict` (409), `scheduled_job_version_mismatch` (412) and `validation` (400) with the `errors` field for a refused field. When the caller's tenant has no grant for the module `scheduler`, every job endpoint SHALL answer 403 with the code `module_denied`.

#### Scenario: Create, read and cancel

- **WHEN** the owner creates a job, reads it, then deletes it
- **THEN** the create answers 201, the read answers 200 with state `active`, the delete answers 204, and a later read answers 200 with state `cancelled` and no next firing time

#### Scenario: Stale update refused

- **WHEN** the owner sends a `PATCH` with an `If-Match` value of an older version
- **THEN** the request answers 412 with the code `scheduled_job_version_mismatch` and the job is unchanged

#### Scenario: Run now

- **WHEN** the owner triggers an `active` job whose next firing is tomorrow
- **THEN** the request answers 202, a firing starts at once, and the next firing is still tomorrow

#### Scenario: Run now of a paused job is refused

- **WHEN** the owner triggers a `paused` job
- **THEN** the request answers 409 with the code `scheduled_job_state_conflict`
- **AND** no firing is recorded and the job stays `paused`

### Requirement: Jobs stay inside the caller's tenant and user

Every read and write of a job SHALL be limited to the caller's tenant. A personal deployment SHALL run as the tenant `default`. A caller SHALL see and change only the jobs of their own user id, and a caller with the `ADMIN` role SHALL see and change every job of their own tenant. A job id that does not exist or that the caller may not see SHALL answer 404, never 403. A job SHALL always act for and notify its own user, never the caller who changed it.

#### Scenario: Personal deployment runs as tenant default

- **WHEN** the owner creates a job in the personal deployment
- **THEN** the stored job carries the tenant `default`

#### Scenario: Another user's job is hidden

- **WHEN** a user without the `ADMIN` role reads a job of another user of the same tenant
- **THEN** the response is 404

### Requirement: The job view is the same everywhere

The JSON view of a job SHALL be the same in the list, the single read, the create and update responses and the agent tool results, and SHALL use these fields: `id`, `name`, `kind`, `origin`, `state`, `pausedReason`, `prompt`, `schedule` (`type`, `cron`, `runAt`, `intervalSeconds`), `timeZone`, `startsAt`, `endsAt`, `maxFirings`, `firingCount`, `consecutiveFailures`, `tools`, `model`, `limits` (`costUsd`, `tokens`), `deliveryMode`, `nextFireAt`, `nextFireAtLocal`, `lastFiredAt`, `createdAt`, `updatedAt` and `version`. The task fields SHALL be null for a `reminder`. Times SHALL be ISO 8601. Adding a field later SHALL NOT rename or remove an existing one.

#### Scenario: Same view in REST and tool

- **WHEN** the agent lists a job with `scheduled_job_list` and the owner reads it through REST at the same moment
- **THEN** both views have the same fields with the same values

### Requirement: Final jobs are kept for a configured time

A job in `completed` or `cancelled` SHALL be deleted with its firing history after a configured retention period (default 30 days) from the moment it became final, by the one retention task of the shared scheduler. A job that is not final SHALL never be deleted by retention. The runs its firings started SHALL follow the retention of runs, and its notifications the retention of notifications, not of jobs.

#### Scenario: Old cancelled job is removed

- **WHEN** a job was cancelled more than 30 days ago and the retention task runs
- **THEN** reading the job answers 404

### Requirement: Job changes are audited, measured and logged

Every create, update, pause, resume, trigger and cancel of a job, by the owner, by the agent or by the system, SHALL be recorded as an audit event through the audit event port of the deployment modules capability, with the job id, the kind, the origin, the actor and the outcome, and never the prompt. Where the events are stored is decided by the port's registered implementation. The agent SHALL publish a gauge of jobs by kind, state and origin and a counter of job changes by source (`rest`, `tool`, `system`), action and outcome. Metric tags SHALL NOT include a job id, a job name, a user id, a tenant id or the prompt. One INFO log line SHALL be written per job change with the job id, tenant id, kind, origin, action and outcome. The prompt SHALL NOT be logged at INFO level or above.

#### Scenario: Agent creation is audited

- **WHEN** the agent creates a job through its tool
- **THEN** one audit event records the creation with origin `agent`
- **AND** the event holds no prompt text

### Requirement: Scheduled jobs are covered by end-to-end tests

The repository SHALL hold end-to-end tests for scheduled jobs against the live stack in `apps/ascend-agent/e2e/`. Job management and a `reminder` firing from its schedule and from a trigger through to its notification SHALL be checked by a deterministic spec whose Bruno requests call no AI model, because a reminder never calls a model. A behaviour that a unit or integration test already proves, such as the automatic pause after three failed firings, `owner_notify`, a disabled owner or another user's job, SHALL NOT be repeated by an end-to-end spec. The AI-run spec SHALL run against the agent with its shipped configuration. Only the behaviours that need a real model, a `task` firing that starts a run and delivers its result and the agent's job tools in chat, SHALL be checked by an AI-run spec. Pass criteria SHALL be HTTP status, response bodies, the job, firing and run rows, the notifications and Keycloak state only, never log lines. Every spec SHALL be listed in the full-stack run scenarios and the ascend-agent service suite of `docs/E2E_RUN_SCENARIOS.md`, and the owner SHALL be asked which scenario to run before any run.

#### Scenario: Job management is checked without a model

- **WHEN** the deterministic scheduled jobs spec runs against the live stack
- **THEN** every request of `docs/api/request/AscendAI/ascend-agent/testing/scheduled-jobs-api/` passes its status and body assertions

#### Scenario: A timed reminder fires end to end without a model

- **WHEN** the deterministic spec creates a `reminder` two minutes ahead and waits
- **THEN** the job's firing history holds one firing with trigger `schedule` and outcome `delivered`
- **AND** one `reminder` notification names the job, and no run of that job exists

#### Scenario: A timed task delivers its result end to end

- **WHEN** the AI-run spec creates a `task` job two minutes ahead that asks for the weather with the tool `weather_current`
- **THEN** its firing starts one run of kind `scheduled` that ends `done`
- **AND** one `result` notification names the job and the run
