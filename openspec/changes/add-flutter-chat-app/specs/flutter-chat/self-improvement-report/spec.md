## Purpose

Provides the "What I learned" screen where the owner reads what the agent changed about itself (`add-self-improvement`), why, what triggered it and how the check went, sees which changes came from an untrusted source, and undoes a change in one step.

## ADDED Requirements

### Requirement: "What I learned" lists the change records
The app SHALL offer a "What I learned" screen reachable from the conversation list, filled from `GET /api/v1/self-improvement/changes`, newest first, with cursor paging. Each item SHALL show what changed (type, name and operation), why, the trigger, the check outcome, a visible "untrusted source" mark when the record came from a source that was not clean, and an Undo button. Tapping an item SHALL show its detail from `GET /api/v1/self-improvement/changes/{id}` with the diff. The screen SHALL be shown only when `GET /api/v1/modules` lists the module `self-improvement` as active, or when that call fails.

#### Scenario: Untrusted mark
- **WHEN** a change record was made from a source that was not clean
- **THEN** its item SHALL show the "untrusted source" mark

#### Scenario: Detail with diff
- **WHEN** the owner taps a skill change
- **THEN** the app SHALL show the diff returned by `GET /api/v1/self-improvement/changes/{id}`

### Requirement: Undo in one step
Pressing Undo SHALL ask for a confirmation and then send `POST /api/v1/self-improvement/changes/{id}/undo`. On success the item SHALL be read again and show its new status. A refusal, for example for a caller who is not an `ADMIN`, SHALL show the `detail` of its problem detail and SHALL leave the item unchanged.

#### Scenario: Undo a change
- **WHEN** the owner presses Undo on a kept change and confirms
- **THEN** the app SHALL send `POST /api/v1/self-improvement/changes/{id}/undo` and the item SHALL show the status `undone` after the reload

#### Scenario: Undo refused
- **WHEN** the agent answers the undo with 403
- **THEN** the app SHALL show the `detail` of the problem detail and the item SHALL stay as it was

### Requirement: Unseen changes badge
The conversation list app bar SHALL show a badge with the number of change ids in `subjectIds` of the first page of the caller's unread notifications of source `self_improvement` (`GET /api/v1/notifications?unread=true&source=self_improvement`), with a plus sign when the page says more exist, because the notification read time is the only seen marker. Opening the "What I learned" screen SHALL send `POST /api/v1/notifications/{id}/read` for each of those unread notifications, and the badge SHALL then be read again. The app SHALL NOT call a seen endpoint of the self-improvement API.

#### Scenario: Opening clears the badge
- **WHEN** the badge shows 2 from one unread `self_improvement` notification that names two changes, and the owner opens the "What I learned" screen
- **THEN** the app SHALL send `POST /api/v1/notifications/{id}/read` for that notification and the badge SHALL disappear after the reload
