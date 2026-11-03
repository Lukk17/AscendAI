## Purpose

Provides the notification list where the owner reads the owner notifications of `add-shared-scheduler` (reminders, job results, self-improvement reports, expired approvals, coding area warnings), marks them as read and goes to their subject. The app reads them while it is open. Push is not part of this change.

## ADDED Requirements

### Requirement: Notification list shows the owner's notifications
The app SHALL offer a notification list screen filled from `GET /api/v1/notifications`, newest first, with cursor paging, showing for each notification its title, the first part of its body, its time in the device's local time, and an unread mark when `readAt` is empty. Opening a notification SHALL show its full title and body and SHALL send `POST /api/v1/notifications/{id}/read` when it was unread. A 404 with `code` `notification_not_found` SHALL remove the item from the list and show the `detail` of the problem detail.

#### Scenario: Opening an unread notification
- **WHEN** the owner opens an unread notification
- **THEN** the app SHALL show its title and body, send `POST /api/v1/notifications/{id}/read`, and remove its unread mark

#### Scenario: Next page
- **WHEN** the owner scrolls to the end of the list and the page says more exist
- **THEN** the app SHALL load the next page and append it

### Requirement: A notification leads to its subject
From a notification's detail view the app SHALL offer one action that opens the screen of its subject: source `approval`, and source `coding_area` with kind `cleanup`, open the pending approvals screen, source `self_improvement` opens the "What I learned" screen, and source `scheduled_job` opens the run detail of `runId` when it is set and otherwise the scheduled job detail of `jobId`. A notification with no such subject SHALL offer no action.

#### Scenario: Self-improvement report
- **WHEN** the owner opens a notification of source `self_improvement`
- **THEN** the detail view SHALL offer an action that opens the "What I learned" screen

#### Scenario: Scheduled job result
- **WHEN** the owner opens a notification of source `scheduled_job` that has a `runId`
- **THEN** the detail view SHALL offer an action that opens that run's detail

### Requirement: Notifications are refreshed while the app is open
The app SHALL read the unread notifications when it starts, when its lifecycle returns to `resumed`, on pull to refresh, and every `ASCEND_OWNER_REFRESH_SECONDS` seconds (a build-time setting, default 60) while its lifecycle is `resumed`. The timer SHALL stop when the lifecycle moves to `paused` or `hidden`. The conversation list app bar SHALL show a badge with the number of unread notifications on the first page of `GET /api/v1/notifications?unread=true`, with a plus sign when the page says more exist. The app SHALL NOT register for push notifications and SHALL NOT read notifications while it is in the background.

#### Scenario: Return to the foreground
- **WHEN** the app returns to the foreground after a reminder fired
- **THEN** the app SHALL read `GET /api/v1/notifications?unread=true` and the badge SHALL count the reminder

#### Scenario: No polling in the background
- **WHEN** the app lifecycle is `paused`
- **THEN** the app SHALL send no notification request until it is `resumed` again
