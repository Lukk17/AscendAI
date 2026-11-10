## Purpose

Provides the scheduled jobs screens where the owner sees the reminders and tasks of `add-scheduled-tasks`, their firing history, and pauses, resumes, runs or cancels them. Jobs are created by asking the agent in chat, so the app does not create or edit them.

## ADDED Requirements

### Requirement: Scheduled jobs list
The app SHALL offer a scheduled jobs screen reachable from the conversation list, filled from `GET /api/v1/scheduled-jobs`, showing for each job its name, kind (`reminder` or `task`), state and next firing time in the job's time zone. The screen SHALL be shown only when `GET /api/v1/modules` lists the module `scheduler` as active, or when that call fails.

#### Scenario: Reminder and task listed
- **WHEN** the owner has one `reminder` and one `task` job
- **THEN** the list SHALL show both with their kind, state and next firing time

#### Scenario: Module off
- **WHEN** `GET /api/v1/modules` does not list `scheduler`
- **THEN** the app SHALL show no entry for the scheduled jobs screen

### Requirement: Scheduled job detail and actions
The job detail SHALL show the job from `GET /api/v1/scheduled-jobs/{id}` and its firing history from `GET /api/v1/scheduled-jobs/{id}/firings`, and SHALL offer Pause (`POST /api/v1/scheduled-jobs/{id}/pause`) for an active job, Resume (`POST /api/v1/scheduled-jobs/{id}/resume`) for a paused job, Run now (`POST /api/v1/scheduled-jobs/{id}/trigger`), and Cancel (`DELETE /api/v1/scheduled-jobs/{id}`) after a confirmation. After each action the detail SHALL be read again. A refusal SHALL show the `detail` of its problem detail. A firing that started a run SHALL open that run's detail when tapped.

#### Scenario: Pause an active job
- **WHEN** the owner presses Pause on an active job
- **THEN** the app SHALL send `POST /api/v1/scheduled-jobs/{id}/pause` and show the job as paused with a Resume button

#### Scenario: Run now
- **WHEN** the owner presses Run now
- **THEN** the app SHALL send `POST /api/v1/scheduled-jobs/{id}/trigger` and the firing history SHALL show the new firing after the reload

#### Scenario: Cancel needs confirmation
- **WHEN** the owner presses Cancel and then dismisses the confirmation
- **THEN** the app SHALL send no request
