## Purpose

Gives the agent one way to tell a user something when no chat request is open: every reminder, job result, message, failure notice, missed reminder, self-improvement report, expired approval notice and coding area warning becomes a stored notification the user can always read, and is delivered to every channel that can reach the user, such as Discord through the plugin host and the mobile app, through the channel's own queue, with the end state of each delivery recorded.

## ADDED Requirements

### Requirement: A notification is a stored record

The agent SHALL store each owner notification in PostgreSQL in a table created by a Flyway versioned SQL migration, with every constraint and index named explicitly. A notification SHALL hold: id, tenant id, user id, source, kind, the job id, the firing id and the run id when they exist, the ids of the records it reports (`subject_ids`, a list, empty when it reports none), the buttons a channel may show with it (`actions`, a list of action type, subject id and label, empty when it has none), a title, a body of at most 4000 characters, the creation time and the time it was read. The pair of source and kind SHALL be one of the allowed pairs stored in a lookup table, which this change's migration leaves empty and which each later change fills with its own pairs through its own versioned migration. The pairs of the build order are:

- source `scheduled_job` (from `add-scheduled-tasks`) with kind `reminder`, `result`, `message`, `failure`, `paused` or `missed`, and the job name as its title,
- source `self_improvement` (from `add-self-improvement`) with kind `change` or `alert`, a fixed title of that source, and the ids of the reported change records in `subject_ids`,
- source `approval` (from `add-action-approvals`) with kind `expired`, a fixed title of that source, and the id of the expired approval request in `subject_ids`,
- source `coding_area` (from `add-coding-agent-delegation`) with kind `low_space` or `cleanup`, a fixed title of that source, an empty `subject_ids` for `low_space` and the id of the cleanup approval in `subject_ids` for `cleanup`,
- source `integration` (from `add-self-built-integrations`) with kind `auto_disabled`, a fixed title of that source, the id of the disabled integration in `subject_ids`, and one notification for every user with the `ADMIN` role in the tenant of that integration.

A kind SHALL be accepted only with its own source, through a foreign key to the lookup table. A change that needs a new source or kind SHALL insert its pair with its own versioned migration and add it to this list. A body that is longer than 4000 characters SHALL be cut to 4000 characters with a visible note that it was cut and where the full text is (the run for a job result, the change records for a self-improvement report, the records in `subject_ids` for the other sources).

#### Scenario: Long result is cut with a note

- **WHEN** a job run's result has 6000 characters
- **THEN** the notification body has at most 4000 characters, ends with a note that it was cut, and names the run id

#### Scenario: Self-improvement report carries its subjects

- **WHEN** a notification of source `self_improvement` and kind `change` is created for one change record
- **THEN** reading the notification returns that change record's id in `subject_ids`

#### Scenario: Expired approval is reported

- **WHEN** a notification of source `approval` and kind `expired` is created for one expired approval request
- **THEN** reading the notification returns that request's id in `subject_ids`

#### Scenario: Kind of another source refused

- **WHEN** the allowed pairs of `add-scheduled-tasks` and `add-coding-agent-delegation` are stored, and a notification of source `scheduled_job` and kind `alert`, or of source `coding_area` and kind `expired`, is stored
- **THEN** the database refuses it with the named foreign key

#### Scenario: No pair of a later change in the first migration

- **WHEN** this change's migrations have run on an empty database and no later change has run
- **THEN** the lookup table of allowed pairs is empty and a notification of any source is refused

### Requirement: Notifications reach every channel that can reach the user

Every notification SHALL be readable through the notification API as soon as it is stored. Every alert of every change SHALL be created through the one notification service. In the same transaction that stores the notification, the agent SHALL offer it to every notification channel that is switched on in the deployment and can reach the notification's user, and the channel SHALL accept it into its own durable queue without a network call, so a rolled back caller sends nothing and a committed notification is never lost. The channel's queue SHALL send it in real time. Each channel SHALL be a separate implementation of one notification port that declares its name, whether it can reach a given user, and how it accepts a notification. A channel that cannot reach the user SHALL be recorded as `unavailable` for that notification. With no channel switched on, the notification SHALL still be stored and readable. Adding a channel SHALL NOT need a change to the code that creates notifications.

#### Scenario: Only the stored notification

- **WHEN** no notification channel is switched on and a notification is created
- **THEN** the notification is readable through `GET /api/v1/notifications` and no delivery is attempted

#### Scenario: Channel without a link

- **WHEN** the Discord channel is switched on but the user has no linked Discord account
- **THEN** the Discord delivery of that notification is recorded as `unavailable`

#### Scenario: Rolled back caller sends nothing

- **WHEN** a caller creates a notification and its transaction rolls back
- **THEN** neither the notification nor any delivery nor any message in a channel's queue exists

### Requirement: Deliveries are recorded, and the channel's queue is the one retry layer

The agent SHALL record each delivery of a notification to a channel with its state (`pending`, `delivered`, `failed` or `unavailable`), a short error code and the time of its last change. A delivery SHALL be `pending` once the channel accepted it into its queue. The retries of a delivery SHALL belong to the channel's own queue alone, so one message is retried by one layer: the notification service SHALL schedule no retry of its own. When the channel's queue reaches an end state, the channel SHALL report it once, and the delivery SHALL move from `pending` to `delivered` or `failed`. A second report SHALL change nothing. A failed delivery on one channel SHALL NOT stop the delivery on another.

#### Scenario: Channel queue delivers

- **WHEN** a channel accepts a notification and later reports that its queue delivered it
- **THEN** the delivery is `delivered`, and a second report of the same end state changes nothing

#### Scenario: Channel queue gives up

- **WHEN** a channel's queue reports that it gave up on a notification with an error code
- **THEN** the delivery is `failed` with that error code and the notification is still readable through the API

### Requirement: Every button is pressed through one action endpoint

A button shown with a notification or with an approval prompt on any channel SHALL carry an action type and a subject id, read by the agent from its own stored message, never from the press. Every press SHALL go through one action endpoint, which SHALL call the one handler registered for that action type with the tenant of the message bound and the identity of the user who pressed. A new kind of button SHALL add an action type and its handler, never a new endpoint. A press whose action type has no handler, because its module is off, SHALL change nothing. The notification `read_at` SHALL be the only seen marker of a notification and of the records it reports.

#### Scenario: Undo button of a report

- **WHEN** a notification carries one action of a test action type with a subject id, and the button of that action is pressed
- **THEN** the handler registered for that action type is called once with that subject id, the tenant of the notification and the identity of the user who pressed

#### Scenario: Seen through the notification

- **WHEN** the user marks a notification read
- **THEN** it no longer appears in `GET /api/v1/notifications?unread=true`, and the records in its `subject_ids` count as seen for every change that asks whether they were seen

### Requirement: The user reads notifications through REST

The agent SHALL expose `GET /api/v1/notifications` (newest first, with optional filters `unread`, `source` and `kind`, and cursor pagination with `limit` at most a configured maximum, default 100, and a configured default, default 20), `GET /api/v1/notifications/{id}` (with its deliveries per channel) and `POST /api/v1/notifications/{id}/read` (answering 204, again 204 when it is already read). The notification view SHALL hold `id`, `source`, `kind`, `title`, `body`, `jobId`, `firingId`, `runId`, `subjectIds`, `actions`, `createdAt` and `readAt`. Every call SHALL be limited to the caller's tenant and to the caller's own notifications, also for a caller with the `ADMIN` role, because a notification is addressed to one user. An id that does not exist or belongs to another user SHALL answer 404 with the code `notification_not_found`. Every error SHALL be the agent's RFC 7807 problem detail.

#### Scenario: Unread list

- **WHEN** the user has two unread notifications and one read notification and lists with `unread=true`
- **THEN** the response holds the two unread notifications, newest first

#### Scenario: Another user's notification is hidden

- **WHEN** an `ADMIN` reads a notification of another user of the same tenant
- **THEN** the response is 404

#### Scenario: Unknown id answers a problem body

- **WHEN** the user reads a notification id that does not exist
- **THEN** the response is 404 with `Content-Type: application/problem+json` and `code` `notification_not_found`

#### Scenario: Marking read twice

- **WHEN** the user marks one notification read and then marks it read again
- **THEN** both calls answer 204
- **AND** the time it was read is the time of the first call

### Requirement: Notifications are kept for a configured time

Notifications and their deliveries SHALL be deleted a configured retention period (default 30 days) after their creation, through a retention entry of the one shared retention task. A notification with a delivery that is still `pending` SHALL NOT be deleted. Every notification and delivery row SHALL carry the tenant it belongs to.

#### Scenario: Old notification removed

- **WHEN** a notification was created 31 days ago and all its deliveries are final, and the retention task runs
- **THEN** reading it answers 404

### Requirement: Notifications are measured and logged

The agent SHALL publish a counter of notifications created by source and kind and a counter of delivery states by channel and outcome. Metric tags SHALL NOT include a notification id, a user id, a tenant id or any text. One INFO log line SHALL be written per notification created and per delivery state change, with the notification id, the tenant id, the source, the kind, the channel and the outcome. The title and the body SHALL NOT be logged at INFO level or above.

#### Scenario: Failed delivery is counted

- **WHEN** a channel reports that its queue gave up on a delivery
- **THEN** the delivery counter with that channel and outcome `failed` grows by one, and the log line holds no body text
