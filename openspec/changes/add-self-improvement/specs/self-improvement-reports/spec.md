## Purpose

Tells the owner after the fact what the agent changed about itself, why, which conversation taught it, how the check went, and how to undo it in one step. Covers the change record, the report content, the report sent at once as an owner notification of `add-shared-scheduler`, undo, the REST surface, audit, erasure, export, retention, metrics and logs.

## ADDED Requirements

### Requirement: Every self-written change is recorded

The agent SHALL record one change record for every change the agent made to a skill, a subagent definition, a user facts file or a semantic memory, every personality proposal, every staged change, every guard revert, every change a review tried and the gate refused, and, once `add-self-built-integrations` is applied, every integration that is registered, activated, updated, disabled by the model or disabled automatically. A record SHALL hold the type, the operation, the item's name, the commit, memory or proposal it produced, the reason the agent gave, the trigger kinds, the conversation and request it came from, the provenance, the guard outcome, the status (`kept`, `staged`, `reverted_by_guard`, `undone`, `refused`), the size before and after, and when it was created and reported. A record SHALL hold no seen marker of its own: whether the owner has seen a change SHALL be the read time of the owner notification that reported it to him. A record SHALL never hold the evidence of the review.

#### Scenario: Chat write is recorded

- **WHEN** the model writes a skill during a clean chat request
- **THEN** a change record with type `skill`, operation `create`, status `kept` and that request id exists

#### Scenario: Automatic disable of an integration is recorded

- **WHEN** an integration is disabled automatically by its failure rule
- **THEN** a change record with type `integration` and operation `auto_disable` exists and an `alert` notification reports it at once

### Requirement: The report says what, why, which conversation, the check and how to undo

The report of a change SHALL show the type, name and operation, the size before and after, a unified diff for skills, definitions and user facts, the reason, the trigger kinds with the conversation id and time, the guard outcome with the failed rubric lines when it failed, a mark when the source was not clean, an undo button and the undo command for the change. The report SHALL never show the review's evidence, a tool result or a retrieved document.

#### Scenario: Report of a patch

- **WHEN** the owner reads the report of a kept patch of `invoice-checks`
- **THEN** it shows the diff, the reason, the conversation id, outcome `passed` and the undo command `curl -X POST <base>/api/v1/self-improvement/changes/<id>/undo`

### Requirement: Every report is sent at once, when the change happens

The agent SHALL create and send a report at the moment the event it reports happens, never at a fixed hour and never as a daily digest. It SHALL send one report for each change record that reaches `kept`, `staged` or `reverted_by_guard`, for a chat change whose check ends `unchecked`, for a freeze, and for the first limit refusal of a day. A change a review tried and the gate refused SHALL send no report and SHALL stay readable through REST. Every report SHALL be an owner notification of `add-shared-scheduler`, one per `ADMIN` of the tenant, with source `self_improvement`, kind `alert` for a staged change, a guard revert, a change from a source that is not clean, an `unchecked` change, a freeze or a limit refusal, and kind `change` for every other kept change, and with the id of the reported change in `subject_ids`. This change SHALL NOT have a report port, a channel adapter, a delivery table, a delivery retry or a report system task of its own: storage, the notification API, delivery to every channel of the `OwnerNotificationChannel` port and retries SHALL be those of `add-shared-scheduler`. When the Discord channel of that port is applied, a self-improvement report SHALL carry one undo button per id in `subject_ids`. Reporting a change SHALL be part of the transaction that records it, so a change is reported exactly once.

#### Scenario: Kept change is reported at once

- **WHEN** a review keeps a new skill at 11:00
- **THEN** a `change` notification of that skill with its change id in `subject_ids` is stored at 11:00 and readable through `GET /api/v1/notifications`

#### Scenario: Guard revert is an alert

- **WHEN** the guard reverts a chat write
- **THEN** an `alert` notification of that revert is stored at once

#### Scenario: No digest

- **WHEN** a day passes with three kept changes
- **THEN** exactly three report notifications exist for each `ADMIN`, one per change, and no other self-improvement notification is stored that day

#### Scenario: Report reaches every channel of the port

- **WHEN** a notification channel that can reach the owner is switched on and a report is stored
- **THEN** the notification service of `add-shared-scheduler` delivers it on that channel and records the delivery

### Requirement: The owner can undo any change in one step

The agent SHALL offer `POST /api/v1/self-improvement/changes/{id}/undo` to an `ADMIN` of the change's tenant, and the same undo in process for a deciding identity and a channel, which the REST endpoint uses with channel `rest` and the plugin host uses for a Discord Undo press with the linked owner's identity and channel `discord`. The in process undo SHALL check that the identity is an `ADMIN` of the change's tenant before anything else, and the channel SHALL be part of the undo's audit event. Undo of an integration change SHALL disable the integration for a registration or an activation, roll it back for an update, and enable it for a disable, and SHALL be refused with 409 and code `newer_change_exists` when a newer change record of the same integration exists. Undo SHALL restore a skill, definition or user facts file to the version before the change through its own revert path with origin `owner`, delete an added memory, insert a removed memory again, deny a pending personality proposal or revert an applied one, and deny a pending staged change. Undo of a skill, definition or user facts change SHALL be refused with 409 and code `newer_change_exists`, naming the newer changes newest first, when the item changed after this change. A second undo of the same change SHALL be refused with 409 and code `already_undone`. After undo the record SHALL be `undone`.

#### Scenario: Undo a patch

- **WHEN** the owner sends undo for the newest change of `invoice-checks`
- **THEN** the skill holds the version before the patch, a new commit with origin `owner` exists, and the record is `undone`
- **AND** a later agent patch of `invoice-checks` is refused with reason `protected`

#### Scenario: Undo an older change

- **WHEN** the owner sends undo for a change of `invoice-checks` that a later patch followed
- **THEN** the response is 409 with code `newer_change_exists` naming the later change

#### Scenario: Undo from Discord

- **WHEN** the linked owner presses the Undo button of a kept skill change on Discord
- **THEN** the change is undone as that owner, and its audit event names the channel `discord`

#### Scenario: Undo a memory removal

- **WHEN** a review removed the memory "User works at Acme" and the owner sends undo
- **THEN** that memory exists again for the same user

### Requirement: A self-improvement report on Discord carries Undo buttons

When the `discord` owner notification channel of the plugin host delivers a notification of source `self_improvement`, the message SHALL carry one Undo button per change id the notification names, each an entry of action type `self_improvement_undo` in the notification's actions. A press SHALL reach the agent through the one channel action endpoint of the plugin host, and this capability SHALL add no endpoint of its own for it. The handler of the action type `self_improvement_undo` SHALL undo that change as the linked user with channel `discord` only when the presser has an active link and the linked user holds `ADMIN` of the change's tenant, and SHALL refuse it with `channel_forbidden` otherwise.

#### Scenario: Undo button press from Discord

- **WHEN** the owner presses Undo on a self-improvement report for change `c1`
- **THEN** change `c1` is undone as the owner's user with channel `discord`

#### Scenario: Presser without ADMIN

- **WHEN** an account linked to a user without `ADMIN` presses Undo
- **THEN** the answer is 403 with `channel_forbidden` and the change is unchanged

### Requirement: The owner reads changes, reviews, cases and statistics through REST

The agent SHALL offer, under `/api/v1/self-improvement` and only to an `ADMIN` of the caller's tenant, through rows this change adds to the authorization matrix of `add-keycloak-login`, listing changes with filters for time, type, status and unseen with a cursor page, where a change is unseen while the caller's report notification of it has no read time, reading one change with its diff, listing and reading reviews with status, triggers, provenance, cost and skip reason but never the evidence, starting the daily review of the own tenant now, listing, adding, changing and deleting test cases, and statistics per type of written, kept, reverted by the guard, undone, used afterwards and unused for the configured period (default 30 days), with the names of the unused self-written items and a delete link for each. Every error SHALL be an RFC 7807 problem detail with a code.

#### Scenario: Non admin is refused

- **WHEN** a caller with a valid token but without `ADMIN` lists changes, undoes a change or starts the daily review
- **THEN** the response is 403
- **AND** a call with no token is answered 401

#### Scenario: Unused skill is listed

- **WHEN** a self-written skill was not loaded for 31 days
- **THEN** the statistics list it as unused with a delete link
- **AND** the skill still exists

#### Scenario: Statistics count use afterwards

- **WHEN** a self-written skill was loaded three times after it was written
- **THEN** the statistics count it as used and the use count of the item is 3

### Requirement: Self-improvement is audited and kept for a bounded time

Every review, change, staging, guard revert, freeze, undo and case write SHALL be recorded through the audit event port of the deployment modules capability with the actions `SELF_IMPROVEMENT_REVIEWED`, `SELF_IMPROVEMENT_CHANGED`, `SELF_IMPROVEMENT_STAGED`, `SELF_IMPROVEMENT_GUARD_REVERTED`, `SELF_IMPROVEMENT_FROZEN`, `SELF_IMPROVEMENT_UNDONE` and `SELF_IMPROVEMENT_CASE_WRITTEN`, with actor, tenant, action, resource, outcome, review id and request id, and never with content. Where the events are stored is decided by the port's registered implementation. Reviews SHALL be deleted after the configured retention (default 90 days) and change records after theirs (default 365 days), by entries of the one retention task of the shared scheduler of `add-shared-scheduler`, so this change has no retention task of its own. The report notifications SHALL follow the notification retention, erasure and export of `add-shared-scheduler`.

#### Scenario: Old review is removed

- **WHEN** the retention task runs and one review is 91 days old and another 89 days old
- **THEN** the 91 day old review is deleted and the 89 day old review stays

#### Scenario: Undo reaches the audit port

- **WHEN** the owner undoes a change through REST while a test audit event port replaces the default
- **THEN** that port receives one `SELF_IMPROVEMENT_UNDONE` event naming the channel `rest` and no content

### Requirement: Self-improvement is visible in metrics and logs

The agent SHALL count triggers by kind, time reviews by outcome, count changes by type, operation and status, time checks by path and outcome, count undos by type, count uses of self-written items by type, and count the cost of the guard checks in dollars as a measurement that never limits anything, with no tenant tag. The cost of a review run SHALL be counted once, by the run cost counter of background runs, and not again by this capability. Every metric name SHALL start with the one word domain `improvement`. It SHALL log one INFO line per trigger and review end, and one WARN line per guard revert, freeze and limit refusal. A change and an undo SHALL write no log line of their own, because their audit event, which the default audit event port writes as one structured INFO line, already records them, with the change id, type, name, status and provenance. No log line or metric SHALL hold evidence, item content, a reason or a diff. When the module is active, the startup log SHALL show the review model per provider, the limits and the zone, and the shared scheduler's startup block SHALL show the schedules of the self-improvement system tasks.

#### Scenario: Reasons stay out of logs

- **WHEN** a review writes a change with a reason
- **THEN** the change's audit event names the change id, type, name, status and provenance and does not contain the reason
- **AND** no other log line is written for that change

### Requirement: Self-improvement is covered by end-to-end tests

The repository SHALL hold end-to-end tests for self-improvement against the live stack in `apps/ascend-agent/e2e/`. Every behaviour that an HTTP status, a response body or persisted state can prove without a change record SHALL be checked by a deterministic spec whose Bruno requests call no AI model, including the test cases, the statistics and the refusals of the endpoints. A behaviour that a unit or integration test already proves, such as the regression guard reverting a chat write and the freeze after two reverts, SHALL NOT be repeated by an end-to-end spec. The AI-run spec SHALL run against the agent with its shipped configuration. The behaviours that need a real model to judge, a correction that leads to a kept skill with a reason, its report, its undo and a chat write after web content that waits for approval, SHALL be checked by an AI-run spec. Pass criteria SHALL be HTTP status, response bodies, the change and review rows, the notifications and the skill history only, never log lines. Every spec SHALL be listed in the full-stack run scenarios and the ascend-agent service suite of `docs/E2E_RUN_SCENARIOS.md`, and the owner SHALL be asked which scenario to run before any run.

#### Scenario: Self-improvement endpoints are checked without a model

- **WHEN** the deterministic self-improvement spec runs against the live stack
- **THEN** every request of `docs/api/request/AscendAI/ascend-agent/testing/self-improvement-api/` passes its status and body assertions
- **AND** the number of `self_change` rows of the tenant is the same before and after the run

#### Scenario: A correction becomes a kept and undoable skill end to end

- **WHEN** the AI-run spec corrects the agent in chat and waits for the review of that conversation to end
- **THEN** the change list holds a kept skill change with a reason, and one notification of kind `change` names it
- **AND** an undo answers 200, the change reads `undone`, and a second undo answers 409 with code `already_undone`
