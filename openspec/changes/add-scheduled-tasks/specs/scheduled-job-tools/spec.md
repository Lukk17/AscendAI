## Purpose

Lets the assistant create, list, change and cancel its own scheduled jobs from a chat without asking for approval, inside rules that stop a job from gaining tools the conversation did not have, and lets a scheduled run tell the owner something only when it matters.

## ADDED Requirements

### Requirement: Four job tools are offered in the main chat

The main chat SHALL offer the tools `scheduled_job_create`, `scheduled_job_list`, `scheduled_job_update` and `scheduled_job_cancel` when the module `scheduler` is active and the tenant has its grant. They SHALL NOT be offered to a subagent run, to a run of kind `scheduled` or to any other background run. They SHALL be governed by the tool policy like every other agent tool, through the tool policy port whose default allows every tool, so the personal deployment offers them. A tool error (a refused schedule, a limit, an unknown job) SHALL be a tool result for the model, never an HTTP error of the chat request.

#### Scenario: Tools in the main chat only

- **WHEN** the tenant policy allows the job tools and a subagent run starts
- **THEN** the main chat's tool list holds the four job tools and the subagent run's tool list holds none of them

#### Scenario: Module off

- **WHEN** the module `scheduler` is not active
- **THEN** none of the four job tools is in the main chat's tool list

#### Scenario: Refused schedule is a tool result

- **WHEN** the model calls `scheduled_job_create` with the cron expression `*/5 * * * *`
- **THEN** the chat request answers normally and the tool result states that the schedule fires more often than the shortest interval

### Requirement: The agent creates jobs without approval, within the conversation's power

`scheduled_job_create` SHALL take the job's kind, name, prompt, schedule, optional time zone, start, end and maximum firings, and for a `task` the tools, an optional model, optional cost and token limits and the delivery mode, and SHALL create the job for the tenant and user of the chat request with origin `agent`, the conversation id and the request id, set by the server and never by the model. The job SHALL be `active` at once, with no approval step. A `reminder` SHALL be refused when it names tools, a model, limits or a delivery mode. For a `task`, the tools SHALL be given explicitly, and every tool SHALL be in the tool list of the chat request that calls the tool. A tool that is not in that list, one of the four job tools, `owner_notify`, or a tool that writes the agent's own configuration SHALL be refused, naming the tool. The model SHALL be on the run model allowlist. Every limit and validation rule of scheduled jobs SHALL apply. One chat request SHALL create at most the configured number of jobs (default 5). When a stored tool is in the "requires approval" mode for the tenant, the tool result SHALL say that each firing which calls that tool will wait for the owner's approval. The tool description SHALL tell the model to use a `reminder` when the job only has to say something at a time, and that a `task` run will not see the user facts file, so every fact the job needs must be written into its prompt.

#### Scenario: Reminder created from chat

- **WHEN** the user writes "remind me at 15:00 tomorrow to call the bank" and the model calls `scheduled_job_create` with kind `reminder`, a `once` schedule and the text "Call the bank"
- **THEN** an `active` `reminder` job with origin `agent` exists for the user, and the tool result holds the job view with the next firing time in the user's time zone

#### Scenario: Facts written into the prompt

- **WHEN** the user asks for a daily weather briefing for the city in their user facts and the model creates a `task` job
- **THEN** the stored prompt names the city

#### Scenario: Tool the conversation does not have

- **WHEN** the model calls `scheduled_job_create` for a `task` naming a tool that is not in the chat request's tool list
- **THEN** no job is created and the tool result names the refused tool

#### Scenario: Too many creations in one request

- **WHEN** the model has created 5 jobs in one chat request and calls `scheduled_job_create` again
- **THEN** no job is created and the tool result states the limit

#### Scenario: Gated tool is announced

- **WHEN** the model creates a `task` job whose tools include a tool in the "requires approval" mode
- **THEN** the job is created and the tool result says that firings calling that tool wait for approval

### Requirement: The agent lists every job of the user and changes only its own

`scheduled_job_list` SHALL return the jobs of the chat request's user in the request's tenant, with optional filters by state, kind and origin, as job views. `scheduled_job_update` and `scheduled_job_cancel` SHALL act only on jobs of that user with origin `agent`. A job with origin `owner` SHALL be refused with a tool result that says the owner manages that job. `scheduled_job_update` SHALL accept the same fields as the REST update plus a state change to `paused` or `active`, SHALL NOT change the kind, and SHALL apply the same tool rule as creation to a changed tool list. A job is found by id or by its exact name.

#### Scenario: Agent cannot cancel an owner job

- **WHEN** the model calls `scheduled_job_cancel` for a job the owner created through REST
- **THEN** the job stays `active` and the tool result says the owner manages it

#### Scenario: Agent pauses its own job

- **WHEN** the user asks to stop the morning briefing for a week and the model calls `scheduled_job_update` with state `paused` on that agent job
- **THEN** the job is `paused` with reason `agent`

### Requirement: A scheduled run can notify the owner and end its own job

A run of kind `scheduled` SHALL be offered the tool `owner_notify` with a message (1 to 4000 characters) and an optional `stop_job` flag. The message SHALL become an owner notification of source `scheduled_job` and kind `message` for the job's user, carrying the job id, the firing id and the run id. With `stop_job` set, the run's own job SHALL move to `completed` after the notification is stored, and the tool SHALL never change any other job. A run SHALL send at most the configured number of messages (default 3). `owner_notify` SHALL NOT be offered to the main chat or to any other run kind. Sending a message to the job's own user SHALL NOT need approval.

#### Scenario: Price watch tells the owner once

- **WHEN** a price watch run finds the price below the owner's threshold and calls `owner_notify` with the message and `stop_job: true`
- **THEN** the owner receives one notification of kind `message`
- **AND** the job is `completed` and does not fire again

#### Scenario: Message limit

- **WHEN** a scheduled run has sent 3 messages and calls `owner_notify` again
- **THEN** no notification is created and the tool result states the limit
