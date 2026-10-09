## Purpose

Provides the background runs screens where the owner follows the runs of `add-agent-subagents` (subagent, scheduled, coding, approval, self review and integration runs) with their status, cost and live events, and cancels a run, plus the run status line inside a conversation.

## ADDED Requirements

### Requirement: Runs list shows the owner's runs
The app SHALL offer a runs screen reachable from the conversation list, filled from `GET /api/v1/runs` with cursor paging and an optional filter by `kind`. Each item SHALL show the run's kind, description, state, cost so far and last step. A run kind the app does not know SHALL be shown with its raw `kind` value and SHALL NOT fail the list.

#### Scenario: Filter by kind
- **WHEN** the owner picks the kind `scheduled` in the filter
- **THEN** the app SHALL read `GET /api/v1/runs?kind=scheduled` and show only those runs

#### Scenario: Unknown kind
- **WHEN** the list holds a run of a kind added by a later agent change
- **THEN** the item SHALL show that kind as text and the list SHALL render normally

### Requirement: Run detail follows the run live and can cancel it
The run detail SHALL show the run view of `GET /api/v1/runs/{id}`: state, kind, description, depth, provider and model, tokens, limits, cost so far, last step, start and finish times, the failure with its reason and `cancelledBy` when it failed or was cancelled, and the result when done. While the run is not final, the detail SHALL follow `GET /api/v1/runs/{id}/events` and update on every `subagent_status` event, and after a dropped connection SHALL reconnect with `Last-Event-ID` set to the last event id it received. The first reconnect SHALL wait `ASCEND_RUN_STREAM_RECONNECT_INITIAL_SECONDS` seconds (a build-time setting, default 1), each further failed attempt SHALL double the wait up to `ASCEND_RUN_STREAM_RECONNECT_MAX_SECONDS` seconds (a build-time setting, default 30), a received event SHALL reset the wait to the first one, and the app SHALL NOT stop trying while the run is not final and the screen is open. The stream SHALL be closed when the run is final or the screen is left. While the run is not final the detail SHALL show a Cancel button that, after a confirmation, sends `POST /api/v1/runs/{id}/cancel` and shows the `detail` of a refusal.

#### Scenario: Live update to done
- **WHEN** the owner watches a running run and the agent sends a `subagent_status` event with state `done`
- **THEN** the detail SHALL show state `done` and the result, hide the Cancel button and close the event stream

#### Scenario: Resume after a dropped connection
- **WHEN** the event stream drops after an event with id 7
- **THEN** the app SHALL reconnect with `Last-Event-ID: 7`

#### Scenario: Reconnect waits longer after each failure
- **WHEN** the event stream of a running run drops and seven reconnect attempts in a row fail
- **THEN** the app SHALL wait 1, 2, 4, 8, 16, 30 and 30 seconds before those attempts with the default settings
- **AND** the app SHALL keep trying while the run is not final and the screen is open

#### Scenario: Cancel
- **WHEN** the owner presses Cancel and confirms
- **THEN** the app SHALL send `POST /api/v1/runs/{id}/cancel` and show the cancelled state when the agent reports it

### Requirement: Run status line in the conversation
When a chat stream sends `run_started`, the app SHALL insert a compact run status line into the conversation with the run's description and state, SHALL update that line on each later `subagent_status` event for the same run id, and SHALL open the run detail when the line is tapped. The line SHALL NOT change the text of the assistant message.

#### Scenario: Background helper started in a chat
- **WHEN** a streamed turn sends `run_started` and then `subagent_status` with state `running`
- **THEN** the conversation SHALL show one run status line in state `running`, and tapping it SHALL open that run's detail
