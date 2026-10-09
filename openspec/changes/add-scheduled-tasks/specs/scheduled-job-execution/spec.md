## Purpose

Defines what happens when a scheduled job fires: a reminder is sent with no model call, a task starts one background run with the job's stored prompt, tools, model and cost and token limits, no task overlaps its previous firing, a fixed rule covers firings missed while the agent was down, gated tools wait for approval, the result reaches the owner, and a job that keeps failing pauses itself.

## ADDED Requirements

### Requirement: A reminder sends its text with no model call

When a job of kind `reminder` fires, the agent SHALL create one owner notification of source `scheduled_job` and kind `reminder` for the job's user, with the job name as title and the stored text as body, and SHALL NOT call any model and SHALL NOT start a run. When the firing is late within its grace period, the body SHALL also name the scheduled time in the job's time zone and how late it is. The firing SHALL be recorded with outcome `delivered` and the notification id.

#### Scenario: Reminder delivered without a model

- **WHEN** a `reminder` job with the text "Call the bank" reaches its firing time
- **THEN** one notification of kind `reminder` with the text "Call the bank" exists for the job's user
- **AND** no run exists for that firing and no model call was made

### Requirement: Each task firing starts one background run

When a job of kind `task` fires, the agent SHALL start one background run of the run kind `scheduled` for the job's tenant and user, with no parent run, at depth 1, with the job's stored prompt as its task, the job's model or the deployment's default chat model when the job names none, and the job's cost and token limit. The run SHALL keep the general run deadline of background runs, and the job SHALL add no time limit of its own. The run SHALL receive the tenant's personality file first, as every run does, and SHALL be told in its instructions the job name, the scheduled time in the job's time zone, the actual start time, how late the firing is when it is late, and how its result is delivered. The run SHALL use the worker slots, the waiting queue, the limits, the cancel path, the status API and the change events of background runs. The run view SHALL carry the job id.

#### Scenario: Firing creates a run

- **WHEN** an `active` `task` job with the prompt "Summarise today's weather in Warsaw" reaches its firing time
- **THEN** one run of kind `scheduled` exists for the job's tenant and user, carrying the job id, with no parent run
- **AND** the job's firing history has one firing with that run id and outcome `started`

#### Scenario: Run follows the job's cost limit

- **WHEN** a job's cost limit is 0.10 US dollars and its run reaches that cost
- **THEN** the run ends `failed` with reason `COST_LIMIT`

### Requirement: A scheduled run does not see the user facts file

A run of kind `scheduled` SHALL NOT receive the user facts file of the job's user. The facts a job needs SHALL be in its stored prompt, and the agent tool that creates a job SHALL tell the model to write them there.

#### Scenario: Facts come from the prompt

- **WHEN** the user facts file says the user lives in Krakow and a job's prompt says "weather for Krakow", and the job fires
- **THEN** the run's model input holds the prompt with Krakow and no text of the user facts file

### Requirement: A firing checks the module grant and the owner first

A firing SHALL resolve, before it does anything else, whether the job's tenant has the grant for the module `scheduler`. When it does not, the firing SHALL NOT start a run or send a notification, SHALL be recorded as `refused_module_denied`, and the job SHALL keep its schedule. A firing SHALL then resolve the job's user: when the user no longer exists or is disabled, the firing SHALL NOT start a run or send a notification, SHALL be recorded as `refused_owner_unavailable`, and the job SHALL be paused with the reason `owner_unavailable`.

#### Scenario: Tenant without the module

- **WHEN** a job fires and its tenant has no grant for the module `scheduler`
- **THEN** nothing is sent, no run starts, the firing is `refused_module_denied` and the job stays `active`

#### Scenario: Disabled user

- **WHEN** a job fires after its user was disabled by an erasure
- **THEN** no run starts, the firing is `refused_owner_unavailable`, and the job is `paused` with reason `owner_unavailable`

### Requirement: A scheduled run gets only the job's tools

The tools of a scheduled run SHALL be the job's stored tool names, kept only where the tool is available to the tenant at firing time and allowed by the tenant's tool policy, plus the tool `owner_notify`. The scheduling tools (`scheduled_job_create`, `scheduled_job_list`, `scheduled_job_update`, `scheduled_job_cancel`) and the tools that write the agent's own configuration (subagent definition writes, personality proposals and user facts updates) SHALL never be offered to a scheduled run. A stored tool name that is not available at firing time SHALL be left out with one WARN log line naming the tool and the job, and SHALL NOT fail the firing. A tool in the "requires approval" mode SHALL stay in the run's tool list, and a call to it SHALL pause the run for the owner's approval exactly as it pauses any background run.

#### Scenario: Policy narrowed after creation

- **WHEN** a job stores the tools `web_search` and `weather_current`, and the tenant policy no longer allows `web_search` at firing time
- **THEN** the run is offered `weather_current` and `owner_notify` only

#### Scenario: Gated tool waits for the owner

- **WHEN** a scheduled run calls a tool whose mode is "requires approval"
- **THEN** the run moves to `awaiting_approval`, a pending approval exists for that call, and the tool does not run before the owner approves it

#### Scenario: No scheduling tools in a scheduled run

- **WHEN** a scheduled run starts
- **THEN** none of the four scheduling tools is in its tool list

### Requirement: A job fires at most once per scheduled time and a task never overlaps itself

A job SHALL produce at most one firing for each scheduled time, also when the scheduler runs the same execution twice after an instance died. When a `task` job's previous firing still has a run that is not final (waiting, running or awaiting approval) at the next scheduled time, the new firing SHALL NOT start a run and SHALL be recorded as `skipped_overlap`, and the job SHALL continue with its next scheduled time.

#### Scenario: Duplicate execution

- **WHEN** the scheduler runs the execution of one scheduled time twice
- **THEN** the job has one firing for that time and at most one run or one reminder notification

#### Scenario: Slow previous firing

- **WHEN** a `task` job fires every 15 minutes and its previous run is still `awaiting_approval` at the next firing time
- **THEN** the new firing is `skipped_overlap` and no second run starts

### Requirement: Missed firings collapse into one decision

When a job missed one or more scheduled times because no agent instance was running, the agent SHALL make one decision for all of them when it starts: when the latest missed time is no older than the job's grace period, the job SHALL fire once, late, and a run SHALL be told the scheduled time and how late it is. Otherwise nothing SHALL be sent and no run SHALL start, one firing SHALL be recorded as `skipped_missed` with the latest missed time, and for a `once` job the owner SHALL receive one notification of kind `missed` that names the job and its scheduled time, and the job SHALL be `completed`. The grace period SHALL be one configured value for every `cron` and `interval` job (default 1 hour) and one configured value for every `once` job (default 24 hours), each at most 7 days. A job SHALL NOT carry a grace period of its own. After the decision, a recurring job SHALL continue with its next scheduled time after the moment of the decision, and SHALL NOT fire once for every missed time.

#### Scenario: Short outage, late briefing

- **WHEN** a daily 07:00 `task` job's agent was down from 06:50 to 07:40 and the grace period is 1 hour
- **THEN** the job fires once at about 07:40 and the run is told it is 40 minutes late

#### Scenario: Long outage, briefing skipped

- **WHEN** a daily 07:00 job's agent was down from 06:50 to 09:30 and the grace period is 1 hour
- **THEN** nothing is sent, one firing is `skipped_missed`, and the next firing is 07:00 the next day

#### Scenario: Missed reminder is not lost silently

- **WHEN** a `once` reminder for 15:00 was missed because the agent was down until 16:00 the next day
- **THEN** no reminder text is sent, the owner receives one `missed` notification naming the reminder and its time, and the job is `completed`

#### Scenario: Many missed times, one decision

- **WHEN** a job that fires every 15 minutes missed 12 times during a 3 hour outage
- **THEN** exactly one firing is recorded for the outage

### Requirement: Firings per tenant per day are limited

The agent SHALL count firings that started a run or delivered a reminder per tenant per calendar day in UTC, from the stored firings, so that the limit holds when several agent instances fire jobs of the same tenant at once. When the configured limit (default 200) is reached, a further firing that day SHALL NOT start a run or send a reminder and SHALL be recorded as `refused_limit`, and the owner SHALL receive at most one notification of kind `failure` per tenant per day that names the limit.

#### Scenario: Daily limit reached

- **WHEN** a tenant has had 200 firings that started a run or delivered a reminder today and another job fires
- **THEN** the firing is `refused_limit`, nothing is sent and no run starts

#### Scenario: Two instances fire at the limit

- **WHEN** a tenant has had 199 firings that started a run or delivered a reminder today and two agent instances fire two of its jobs at the same moment
- **THEN** exactly one of the two firings starts a run or delivers a reminder and the other is `refused_limit`

### Requirement: Failing jobs pause themselves

A firing of a `task` SHALL count as failed when it could not start its run (outcome `failed_to_start`), or when its run ended `failed` or `cancelled` by anyone other than the owner. A successful run SHALL reset the count of failed firings in a row. When the count reaches the configured number (default 3), the job SHALL be paused with the reason `failures`, and the owner SHALL receive one notification of kind `paused` that names the job and the last failure reason. Each failed firing SHALL send the owner one notification of kind `failure` with the job name and the failure reason, unless the job was just paused for failures, in which case the `paused` notification replaces it.

#### Scenario: Third failure pauses the job

- **WHEN** a job's runs end `failed` with reason `TOOL_ERROR` three times in a row
- **THEN** the job is `paused` with reason `failures`
- **AND** the owner receives a `paused` notification for that job

### Requirement: The result of a task reaches the owner

When a scheduled run reaches a final state, the agent SHALL deliver to the job's user, as an owner notification of source `scheduled_job`: in delivery mode `every_run`, the run's result as a notification of kind `result` when the run is `done`. In delivery mode `on_notify`, only the messages the run sent with `owner_notify`. A failed run SHALL produce a `failure` notification under the rule for failing jobs in both modes. A notification SHALL carry the job id, the firing id and the run id.

#### Scenario: Morning briefing delivered

- **WHEN** a job in mode `every_run` fires and its run ends `done` with a result text
- **THEN** one notification of kind `result` with that text exists for the job's user

#### Scenario: Quiet price watch

- **WHEN** a job in mode `on_notify` fires and its run ends `done` without calling `owner_notify`
- **THEN** no notification is created for that firing

### Requirement: Every firing is recorded

Each firing SHALL be stored with: id, job id, tenant id, the scheduled time, the actual time, the lateness, the trigger (`schedule`, `manual` or `catch_up`), the outcome (`started`, `delivered`, `skipped_overlap`, `skipped_missed`, `refused_limit`, `refused_owner_unavailable`, `refused_module_denied` or `failed_to_start`), the run id when a run started, the notification id when a reminder or a missed notice was sent, the final run state once known, and a short failure reason. The agent SHALL keep the newest 50 firings per job: the one retention task of the shared scheduler deletes older ones, and a read of the firing history SHALL return at most the newest 50, also before that task ran.

#### Scenario: History is capped

- **WHEN** a job has fired 51 times
- **THEN** a read of its firing history returns the newest 50 firings
- **AND** after the retention task ran, 50 firings of the job are stored

### Requirement: Firings are measured and logged

The agent SHALL publish a counter of firings by job kind, trigger and outcome, a timer of firing lateness (the time between the scheduled time and the actual start), and a counter of jobs paused by reason. Metric tags SHALL NOT include a job id, a job name, a user id or a tenant id. One INFO log line SHALL be written per firing with the job id, firing id, run id or notification id, tenant id, scheduled time, lateness and outcome. Each run SHALL be one trace span whose parent is a span for the firing.

#### Scenario: Skipped firing is visible

- **WHEN** a firing is `skipped_overlap`
- **THEN** the firing counter with outcome `skipped_overlap` grows by one and one log line records it
